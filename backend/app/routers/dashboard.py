"""Tenant-isolated Outlet/Organisation Manager and Platform Admin dashboard routes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, status, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.orchestrator import orchestrate_dashboard_summary
from app.database import get_db
from app.models import (
    AiRecommendation,
    InventoryMovement,
    MenuItem,
    Order,
    OrderItem,
    Organisation,
    Outlet,
    QrToken,
    Review,
    Role,
    SecurityEvent,
    User,
)
from app.schemas import RecommendationActionRequest
from app.services.audit_service import record_audit_log
from app.services.auth_service import (
    USERNAME_RE,
    hash_password,
    require_roles,
    validate_password_strength,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class StockUpdateRequest(BaseModel):
    stock_qty: int = Field(..., ge=0, le=500)


class CreateOutletRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    location: str = Field(..., min_length=2, max_length=160)
    avg_prep_minutes: float = Field(default=8.0, ge=1.0, le=60.0)
    active_staff: int = Field(default=3, ge=1, le=50)


class UpdateOrgOutletRequest(BaseModel):
    status: Literal["OPEN", "BUSY", "CLOSED"] | None = None
    active_staff: int | None = Field(default=None, ge=1, le=50)
    avg_prep_minutes: float | None = Field(default=None, ge=1.0, le=60.0)


class CreateMenuItemRequest(BaseModel):
    outlet_id: int
    name: str = Field(..., min_length=2, max_length=120)
    category: str = Field(..., min_length=2, max_length=64)
    price: float = Field(..., gt=0.0, le=5000.0)
    stock_qty: int = Field(default=20, ge=0, le=500)
    prep_minutes: int = Field(default=6, ge=1, le=60)
    is_veg: bool = True
    description: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=500)


class UpdateMenuItemRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = Field(default=None, min_length=2, max_length=64)
    price: float | None = Field(default=None, gt=0.0, le=5000.0)
    stock_qty: int | None = Field(default=None, ge=0, le=1000)
    prep_minutes: int | None = Field(default=None, ge=1, le=60)
    is_veg: bool | None = None
    is_available: bool | None = None
    description: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=500)


class OrgCreateOutletManagerRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=32)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    outlet_id: int


def _assert_org_outlet_access(
    db: Session,
    outlet_id: int,
    current_user: dict,
    *,
    require_org_manager: bool = False,
) -> Outlet:
    outlet = db.execute(select(Outlet).where(Outlet.id == outlet_id)).scalar_one_or_none()
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet not found.")
    if current_user["role"] == "admin":
        return outlet

    user_org_id = current_user.get("organisation_id")
    if outlet.organisation_id != user_org_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: outlet belongs to another organisation.",
        )

    assigned_oid = current_user.get("outlet_id")
    if require_org_manager and assigned_oid is not None:
        raise HTTPException(
            status_code=403,
            detail="This action requires Organisation Manager scope.",
        )
    if assigned_oid is not None and outlet.id != assigned_oid:
        raise HTTPException(
            status_code=403,
            detail="Access denied: restricted to your assigned outlet.",
        )
    return outlet


@router.get("/outlet")
def get_outlet_manager_dashboard(
    outlet_id: int | None = None,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Return outlet-scoped telemetry inside caller's organisation (supports org & outlet managers)."""
    role = current_user["role"]
    user_org_id = current_user.get("organisation_id")

    if role == "admin":
        if outlet_id is None:
            raise HTTPException(status_code=400, detail="Specify outlet_id for admin inspection.")
        outlet_row = db.execute(select(Outlet).where(Outlet.id == outlet_id)).scalar_one_or_none()
        if not outlet_row:
            raise HTTPException(status_code=404, detail="Outlet not found.")
        available_outlets = db.execute(
            select(Outlet).where(Outlet.organisation_id == outlet_row.organisation_id).order_by(Outlet.id)
        ).scalars().all()
    else:
        available_outlets = db.execute(
            select(Outlet).where(Outlet.organisation_id == user_org_id).order_by(Outlet.id)
        ).scalars().all()
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None:
            if outlet_id is not None and outlet_id != assigned_oid:
                raise HTTPException(status_code=403, detail="Cannot view another outlet's dashboard.")
            outlet_row = next((o for o in available_outlets if o.id == assigned_oid), None)
            available_outlets = [outlet_row] if outlet_row else []
        elif outlet_id is not None:
            outlet_row = next((o for o in available_outlets if o.id == outlet_id), None)
            if not outlet_row:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: outlet does not belong to your organisation.",
                )
        else:
            outlet_row = available_outlets[0] if available_outlets else None

    if not outlet_row:
        return {
            "organisation_id": user_org_id,
            "is_org_manager": current_user.get("is_org_manager", False),
            "available_outlets": [],
            "outlet": None,
            "metrics": {
                "active_queue": 0,
                "collected_today": 0,
                "low_stock_count": 0,
                "open_complaints": 0,
                "live_revenue": 0.0,
            },
            "orders": [],
            "menu_items": [],
            "reviews": [],
            "recommendations": [],
            "security_events": [],
        }

    target_outlet_id = outlet_row.id

    order_rows = db.execute(
        select(Order, QrToken.status.label("qr_status"), QrToken.scan_count)
        .outerjoin(QrToken, QrToken.order_id == Order.id)
        .where(
            Order.organisation_id == outlet_row.organisation_id,
            Order.outlet_id == target_outlet_id,
            Order.is_sample.is_(False),
        )
        .order_by(Order.id.desc())
        .limit(30)
    ).all()

    orders = []
    for o, q_status, q_scans in order_rows:
        item_rows = db.execute(
            select(OrderItem).where(OrderItem.order_id == o.id)
        ).scalars().all()
        orders.append(
            {
                "id": o.id,
                "organisation_id": o.organisation_id,
                "order_code": o.order_code,
                "outlet_id": o.outlet_id,
                "student_name": o.student_name,
                "group_code": o.group_code,
                "scheduled_slot": o.scheduled_slot,
                "total_amount": o.total_amount,
                "payment_status": o.payment_status,
                "order_status": o.order_status,
                "estimated_wait_minutes": o.estimated_wait_minutes,
                "qr_status": q_status,
                "scan_count": q_scans,
                "items": [
                    {
                        "menu_item_id": ir.menu_item_id,
                        "item_name": ir.item_name,
                        "quantity": ir.quantity,
                        "unit_price": ir.unit_price,
                    }
                    for ir in item_rows
                ],
            }
        )

    menu_rows = db.execute(
        select(MenuItem)
        .where(
            MenuItem.organisation_id == outlet_row.organisation_id,
            MenuItem.outlet_id == target_outlet_id,
        )
        .order_by(MenuItem.id)
    ).scalars().all()
    by_id = {m.id: m.name for m in menu_rows}
    menu_items = [
        {
            "id": m.id,
            "organisation_id": m.organisation_id,
            "outlet_id": m.outlet_id,
            "name": m.name,
            "description": m.description,
            "image_url": m.image_url,
            "category": m.category,
            "price": m.price,
            "stock_qty": m.stock_qty,
            "prep_minutes": m.prep_minutes,
            "is_veg": int(bool(m.is_veg)),
            "is_available": bool(m.is_available),
            "substitute_name": by_id.get(m.substitute_item_id),
        }
        for m in menu_rows
    ]

    rev_rows = db.execute(
        select(Review)
        .where(
            Review.organisation_id == outlet_row.organisation_id,
            Review.outlet_id == target_outlet_id,
        )
        .order_by(Review.is_sample.asc(), desc(Review.id))
        .limit(25)
    ).scalars().all()
    reviews = [
        {
            "id": r.id,
            "organisation_id": r.organisation_id,
            "outlet_id": r.outlet_id,
            "student_name": r.student_name,
            "rating": r.rating,
            "comment": r.comment,
            "sentiment": r.sentiment,
            "category": r.category,
            "is_resolved": int(bool(r.is_resolved)),
            "is_sample": int(bool(r.is_sample)),
        }
        for r in rev_rows
    ]

    rec_rows = db.execute(
        select(AiRecommendation)
        .where(
            AiRecommendation.organisation_id == outlet_row.organisation_id,
            AiRecommendation.outlet_id == target_outlet_id,
        )
        .order_by(AiRecommendation.is_sample.asc(), desc(AiRecommendation.id))
    ).scalars().all()
    recommendations = [
        {
            "id": rec.id,
            "source_agent": rec.source_agent,
            "outlet_id": rec.outlet_id,
            "outlet_name": outlet_row.name,
            "title": rec.title,
            "rationale": rec.rationale,
            "status": rec.status,
            "is_sample": int(bool(rec.is_sample)),
        }
        for rec in rec_rows
    ]

    sec_rows = db.execute(
        select(SecurityEvent, Order.order_code, Order.student_name)
        .join(Order, Order.id == SecurityEvent.order_id)
        .where(
            SecurityEvent.organisation_id == outlet_row.organisation_id,
            Order.outlet_id == target_outlet_id,
        )
        .order_by(desc(SecurityEvent.id))
        .limit(20)
    ).all()
    security_events = [
        {
            "id": ev.id,
            "event_type": ev.event_type,
            "risk_level": ev.risk_level,
            "ai_explanation": ev.ai_explanation,
            "order_code": oc,
            "student_name": sn,
        }
        for ev, oc, sn in sec_rows
    ]

    active_queue = sum(1 for o in orders if o["order_status"] in ("PLACED", "PREPARING"))
    collected_count = sum(1 for o in orders if o["order_status"] == "COLLECTED")
    low_stock_count = sum(1 for m in menu_items if m["stock_qty"] <= 5)
    open_complaints = sum(
        1 for r in reviews if not r["is_resolved"] and r["sentiment"] == "NEGATIVE"
    )
    revenue_today = round(
        sum(o["total_amount"] for o in orders if o["order_status"] != "CANCELLED"), 2
    )

    return {
        "organisation_id": outlet_row.organisation_id,
        "is_org_manager": current_user.get("is_org_manager", False),
        "available_outlets": [
            {
                "id": ao.id,
                "name": ao.name,
                "location": ao.location,
                "status": ao.status,
                "avg_prep_minutes": ao.avg_prep_minutes,
                "active_staff": ao.active_staff,
            }
            for ao in available_outlets
        ],
        "outlet": {
            "id": outlet_row.id,
            "organisation_id": outlet_row.organisation_id,
            "name": outlet_row.name,
            "location": outlet_row.location,
            "status": outlet_row.status,
            "avg_prep_minutes": outlet_row.avg_prep_minutes,
            "active_staff": outlet_row.active_staff,
        },
        "metrics": {
            "active_queue": active_queue,
            "collected_today": collected_count,
            "low_stock_count": low_stock_count,
            "open_complaints": open_complaints,
            "live_revenue": revenue_today,
        },
        "orders": orders,
        "menu_items": menu_items,
        "reviews": reviews,
        "recommendations": recommendations,
        "security_events": security_events,
    }


@router.get("/org-summary")
def get_organisation_summary(
    organisation_id: int | None = None,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Return 8-agent consolidated analytics strictly scoped to caller's organisation."""
    if current_user["role"] != "admin":
        if organisation_id is not None and organisation_id != current_user.get("organisation_id"):
            raise HTTPException(
                status_code=403,
                detail="Access denied: cannot view analytics of another organisation.",
            )
        if current_user.get("outlet_id") is not None:
            raise HTTPException(
                status_code=403,
                detail="Organisation-level analytics require Organisation Manager access.",
            )
        target_org_id = current_user.get("organisation_id")
    else:
        target_org_id = organisation_id

    return orchestrate_dashboard_summary(db, organisation_id=target_org_id)


@router.post("/outlets", status_code=status.HTTP_201_CREATED)
def create_org_outlet(
    payload: CreateOutletRequest,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Allow an Organisation Manager (outlet_id=None) to add an outlet inside their own organisation."""
    if current_user["role"] == "outlet_manager" and current_user.get("outlet_id") is not None:
        raise HTTPException(
            status_code=403,
            detail="Only an Organisation Manager or Platform Admin can add outlets.",
        )
    org_id = current_user.get("organisation_id")
    if not org_id:
        raise HTTPException(
            status_code=400,
            detail="Use /api/admin/outlets with organisation_id for platform admin creation.",
        )

    new_outlet = Outlet(
        organisation_id=org_id,
        name=payload.name.strip(),
        location=payload.location.strip(),
        status="OPEN",
        avg_prep_minutes=payload.avg_prep_minutes,
        active_staff=payload.active_staff,
    )
    db.add(new_outlet)
    db.flush()
    record_audit_log(
        db,
        organisation_id=org_id,
        action="OUTLET_CREATED",
        resource_type="outlet",
        resource_id=new_outlet.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"name": new_outlet.name},
    )
    return {
        "outlet": {
            "id": new_outlet.id,
            "organisation_id": new_outlet.organisation_id,
            "name": new_outlet.name,
            "location": new_outlet.location,
            "status": new_outlet.status,
            "avg_prep_minutes": new_outlet.avg_prep_minutes,
            "active_staff": new_outlet.active_staff,
        }
    }


@router.patch("/outlets/{outlet_id}")
def update_org_outlet(
    outlet_id: int,
    payload: UpdateOrgOutletRequest,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Allow an Organisation Manager or assigned Outlet Manager to configure outlet status and operational SLA."""
    outlet = _assert_org_outlet_access(
        db, outlet_id, current_user, require_org_manager=False
    )
    if payload.status is not None:
        outlet.status = payload.status
    if payload.active_staff is not None:
        outlet.active_staff = payload.active_staff
    if payload.avg_prep_minutes is not None:
        outlet.avg_prep_minutes = payload.avg_prep_minutes
    db.flush()
    record_audit_log(
        db,
        organisation_id=outlet.organisation_id,
        action="ORG_OUTLET_UPDATED",
        resource_type="outlet",
        resource_id=outlet.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"status": outlet.status, "active_staff": outlet.active_staff},
    )
    return {
        "outlet": {
            "id": outlet.id,
            "organisation_id": outlet.organisation_id,
            "name": outlet.name,
            "location": outlet.location,
            "status": outlet.status,
            "active_staff": outlet.active_staff,
            "avg_prep_minutes": outlet.avg_prep_minutes,
        }
    }


@router.post("/outlet/menu", status_code=status.HTTP_201_CREATED)
def add_menu_item_to_outlet(
    payload: CreateMenuItemRequest,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Add a new menu item to a permitted outlet within caller's organisation."""
    outlet = _assert_org_outlet_access(db, payload.outlet_id, current_user)
    item = MenuItem(
        organisation_id=outlet.organisation_id,
        outlet_id=outlet.id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        image_url=payload.image_url.strip() if payload.image_url else None,
        category=payload.category.strip(),
        price=round(payload.price, 2),
        stock_qty=payload.stock_qty,
        prep_minutes=payload.prep_minutes,
        is_veg=payload.is_veg,
        is_available=True,
    )
    db.add(item)
    db.flush()
    db.add(
        InventoryMovement(
            organisation_id=outlet.organisation_id,
            menu_item_id=item.id,
            outlet_id=outlet.id,
            delta_qty=payload.stock_qty,
            new_stock_qty=payload.stock_qty,
            reason="MENU_ITEM_CREATED",
            actor_user_id=current_user["id"],
        )
    )
    record_audit_log(
        db,
        organisation_id=outlet.organisation_id,
        action="MENU_ITEM_CREATED",
        resource_type="menu_item",
        resource_id=item.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"name": item.name, "outlet_id": outlet.id},
    )
    return {
        "menu_item": {
            "id": item.id,
            "organisation_id": item.organisation_id,
            "outlet_id": item.outlet_id,
            "name": item.name,
            "description": item.description,
            "image_url": item.image_url,
            "category": item.category,
            "price": item.price,
            "stock_qty": item.stock_qty,
            "prep_minutes": item.prep_minutes,
            "is_veg": int(bool(item.is_veg)),
            "is_available": True,
        }
    }


@router.patch("/outlet/menu/{item_id}")
def update_menu_item(
    item_id: int,
    payload: UpdateMenuItemRequest,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Allow permitted Outlet/Org Manager or Platform Admin to update menu item details."""
    item = db.execute(select(MenuItem).where(MenuItem.id == item_id)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found.")

    if current_user["role"] == "outlet_manager":
        if item.organisation_id != current_user.get("organisation_id"):
            raise HTTPException(
                status_code=403,
                detail="Access denied: menu item belongs to another organisation.",
            )
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None and item.outlet_id != assigned_oid:
            raise HTTPException(
                status_code=403,
                detail="Cannot modify menu items for another outlet.",
            )

    updates = {}
    if payload.name is not None and payload.name.strip():
        item.name = payload.name.strip()
        updates["name"] = item.name
    if payload.category is not None and payload.category.strip():
        item.category = payload.category.strip()
        updates["category"] = item.category
    if payload.price is not None:
        item.price = round(payload.price, 2)
        updates["price"] = item.price
    if payload.prep_minutes is not None:
        item.prep_minutes = payload.prep_minutes
        updates["prep_minutes"] = item.prep_minutes
    if payload.is_veg is not None:
        item.is_veg = bool(payload.is_veg)
        updates["is_veg"] = item.is_veg
    if payload.is_available is not None:
        item.is_available = bool(payload.is_available)
        updates["is_available"] = item.is_available
    if payload.description is not None:
        item.description = payload.description.strip()
        updates["description"] = item.description
    if payload.image_url is not None:
        item.image_url = payload.image_url.strip() if payload.image_url else None
        updates["image_url"] = item.image_url

    if payload.stock_qty is not None and payload.stock_qty != item.stock_qty:
        delta = payload.stock_qty - item.stock_qty
        item.stock_qty = payload.stock_qty
        db.add(
            InventoryMovement(
                organisation_id=item.organisation_id,
                menu_item_id=item.id,
                outlet_id=item.outlet_id,
                delta_qty=delta,
                new_stock_qty=payload.stock_qty,
                reason="MANUAL_MANAGER_UPDATE",
                actor_user_id=current_user["id"],
            )
        )
        updates["stock_qty"] = item.stock_qty
        updates["stock_delta"] = delta

    record_audit_log(
        db,
        organisation_id=item.organisation_id,
        action="MENU_ITEM_UPDATED",
        resource_type="menu_item",
        resource_id=item.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details=updates,
    )
    db.flush()
    return {
        "menu_item": {
            "id": item.id,
            "organisation_id": item.organisation_id,
            "outlet_id": item.outlet_id,
            "name": item.name,
            "description": item.description,
            "image_url": item.image_url,
            "category": item.category,
            "price": item.price,
            "stock_qty": item.stock_qty,
            "prep_minutes": item.prep_minutes,
            "is_veg": int(bool(item.is_veg)),
            "is_available": bool(item.is_available),
        }
    }


@router.post("/outlet/menu/{item_id}/image")
async def upload_menu_item_image(
    item_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Upload and set an image for a specific menu item."""
    item = db.execute(select(MenuItem).where(MenuItem.id == item_id)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found.")

    if current_user["role"] == "outlet_manager":
        if item.organisation_id != current_user.get("organisation_id"):
            raise HTTPException(
                status_code=403,
                detail="Access denied: menu item belongs to another organisation.",
            )
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None and item.outlet_id != assigned_oid:
            raise HTTPException(
                status_code=403,
                detail="Cannot modify menu items for another outlet.",
            )

    allowed_content_types = {"image/jpeg", "image/png", "image/webp", "image/avif"}
    ct = file.content_type or ""
    if ct.lower() not in allowed_content_types:
        raise HTTPException(
            status_code=400,
            detail="Invalid image format. Allowed formats: JPEG, PNG, WebP, AVIF.",
        )

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image file exceeds 5MB size limit.")

    ext = Path(file.filename or "image.jpg").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        ext = ".jpg"

    upload_dir = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "menu"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"menu_{item.id}_{int(time.time())}{ext}"
    target_path = upload_dir / filename

    with open(target_path, "wb") as f:
        f.write(contents)

    image_url = f"/static/uploads/menu/{filename}"
    item.image_url = image_url
    record_audit_log(
        db,
        organisation_id=item.organisation_id,
        action="MENU_IMAGE_UPLOADED",
        resource_type="menu_item",
        resource_id=item.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"filename": filename, "image_url": image_url},
    )
    db.flush()
    return {"item_id": item.id, "image_url": item.image_url}


@router.delete("/outlet/menu/{item_id}/image")
def delete_menu_item_image(
    item_id: int,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Remove or reset the custom image for a menu item."""
    item = db.execute(select(MenuItem).where(MenuItem.id == item_id)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found.")

    if current_user["role"] == "outlet_manager":
        if item.organisation_id != current_user.get("organisation_id"):
            raise HTTPException(
                status_code=403,
                detail="Access denied: menu item belongs to another organisation.",
            )
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None and item.outlet_id != assigned_oid:
            raise HTTPException(
                status_code=403,
                detail="Cannot modify menu items for another outlet.",
            )

    item.image_url = None
    record_audit_log(
        db,
        organisation_id=item.organisation_id,
        action="MENU_IMAGE_REMOVED",
        resource_type="menu_item",
        resource_id=item.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"item_name": item.name},
    )
    db.flush()
    return {"item_id": item.id, "image_url": None}


@router.post("/org/managers", status_code=status.HTTP_201_CREATED)
def create_org_outlet_manager(
    payload: OrgCreateOutletManagerRequest,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Allow an Organisation Manager to provision an outlet-assigned manager strictly inside their org."""
    outlet = _assert_org_outlet_access(
        db, payload.outlet_id, current_user, require_org_manager=True
    )
    clean_user = payload.username.strip().lower()
    clean_email = str(payload.email).strip().lower()
    if not USERNAME_RE.match(clean_user):
        raise HTTPException(status_code=400, detail="Invalid username format.")
    validate_password_strength(payload.password)

    dup = db.execute(
        select(User).where((User.email == clean_email) | (User.username == clean_user))
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="Username or email already exists.")

    mgr_role = db.execute(select(Role).where(Role.name == "outlet_manager")).scalar_one_or_none()
    user_obj = User(
        organisation_id=outlet.organisation_id,
        username=clean_user,
        email=clean_email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role="outlet_manager",
        role_id=mgr_role.id if mgr_role else None,
        outlet_id=outlet.id,
        is_active=True,
        manager_approval_status="APPROVED",
    )
    db.add(user_obj)
    db.flush()
    record_audit_log(
        db,
        organisation_id=outlet.organisation_id,
        action="ORG_CREATED_OUTLET_MANAGER",
        resource_type="user",
        resource_id=user_obj.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"outlet_id": outlet.id},
    )
    return {
        "user": {
            "id": user_obj.id,
            "organisation_id": user_obj.organisation_id,
            "username": user_obj.username,
            "email": user_obj.email,
            "outlet_id": user_obj.outlet_id,
        }
    }


@router.patch("/outlet/menu/{item_id}/stock")
def update_outlet_menu_stock(
    item_id: int,
    payload: StockUpdateRequest,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Allow permitted Outlet/Org Manager or Platform Admin to adjust menu stock quantities."""
    item = db.execute(select(MenuItem).where(MenuItem.id == item_id)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found.")

    if current_user["role"] == "outlet_manager":
        if item.organisation_id != current_user.get("organisation_id"):
            raise HTTPException(
                status_code=403,
                detail="Access denied: menu item belongs to another organisation.",
            )
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None and item.outlet_id != assigned_oid:
            raise HTTPException(
                status_code=403,
                detail="Cannot modify inventory for another outlet.",
            )

    delta = payload.stock_qty - item.stock_qty
    item.stock_qty = payload.stock_qty
    db.add(
        InventoryMovement(
            organisation_id=item.organisation_id,
            menu_item_id=item.id,
            outlet_id=item.outlet_id,
            delta_qty=delta,
            new_stock_qty=payload.stock_qty,
            reason="MANUAL_MANAGER_UPDATE",
            actor_user_id=current_user["id"],
        )
    )
    record_audit_log(
        db,
        organisation_id=item.organisation_id,
        action="STOCK_UPDATED",
        resource_type="menu_item",
        resource_id=item.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"item": item.name, "delta": delta, "new_stock_qty": payload.stock_qty},
    )
    db.flush()
    return {"item_id": item.id, "name": item.name, "stock_qty": item.stock_qty}


@router.get("/summary")
def get_dashboard_summary(
    organisation_id: int | None = None,
    _admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Return Platform Admin consolidated intelligence (cross-org or filtered to one org)."""
    return orchestrate_dashboard_summary(db, organisation_id=organisation_id)


@router.post("/recommendations/{rec_id}")
def act_on_recommendation(
    rec_id: int,
    payload: RecommendationActionRequest,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Human-in-the-loop recommendation decision strictly within tenant/outlet boundary."""
    rec = db.execute(
        select(AiRecommendation).where(AiRecommendation.id == rec_id)
    ).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found.")

    if current_user["role"] == "outlet_manager":
        if rec.organisation_id != current_user.get("organisation_id"):
            raise HTTPException(
                status_code=403,
                detail="Access denied: recommendation belongs to another organisation.",
            )
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None and rec.outlet_id != assigned_oid:
            raise HTTPException(
                status_code=403,
                detail="Cannot act on recommendations outside your assigned outlet.",
            )

    rec.status = payload.status
    rec.reviewed_by_user_id = current_user["id"]
    rec.reviewed_at = datetime.now(timezone.utc)
    record_audit_log(
        db,
        organisation_id=rec.organisation_id,
        action="RECOMMENDATION_DECISION",
        resource_type="ai_recommendation",
        resource_id=rec_id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"status": payload.status},
    )
    db.flush()
    return {"recommendation_id": rec_id, "status": payload.status}


@router.post("/security/{event_id}/resolve")
def resolve_security_event(
    event_id: int,
    admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Mark a security incident as reviewed/resolved by Platform Admin."""
    ev = db.execute(
        select(SecurityEvent).where(SecurityEvent.id == event_id)
    ).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Security event not found.")
    ev.resolved = True
    ev.resolved_by_user_id = admin["id"]
    record_audit_log(
        db,
        organisation_id=ev.organisation_id,
        action="SECURITY_EVENT_RESOLVED",
        resource_type="security_event",
        resource_id=event_id,
        actor_user_id=admin["id"],
        actor_role="admin",
    )
    db.flush()
    return {"event_id": event_id, "resolved": True}
