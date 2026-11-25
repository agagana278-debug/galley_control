"""Platform Administrator routes: multi-org approvals, cross-org governance, user provisioning, audit logs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, MenuItem, Order, Organisation, Outlet, Role, User
from app.services.audit_service import record_audit_log
from app.services.auth_service import (
    USERNAME_RE,
    hash_password,
    require_roles,
    validate_password_strength,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class OutletUpdateRequest(BaseModel):
    status: Literal["OPEN", "BUSY", "CLOSED"] | None = None
    active_staff: int | None = Field(default=None, ge=1, le=50)
    avg_prep_minutes: float | None = Field(default=None, ge=1.0, le=60.0)


class AdminCreateOutletRequest(BaseModel):
    organisation_id: int
    name: str = Field(..., min_length=2, max_length=120)
    location: str = Field(..., min_length=2, max_length=160)
    avg_prep_minutes: float = Field(default=8.0, ge=1.0, le=60.0)
    active_staff: int = Field(default=3, ge=1, le=50)


class OrganisationApprovalRequest(BaseModel):
    status: Literal["ACTIVE", "SUSPENDED", "REJECTED", "PENDING_APPROVAL"]


class AdminCreateManagerRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=32)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    role: Literal["outlet_manager", "student"] = "outlet_manager"
    organisation_id: int | None = None
    outlet_id: int | None = None


class AdminUpdateUserRequest(BaseModel):
    role: Literal["student", "outlet_manager", "admin"] | None = None
    organisation_id: int | None = None
    outlet_id: int | None = None
    is_active: bool | None = None
    manager_approval_status: Literal["APPROVED", "PENDING", "REJECTED"] | None = None


@router.get("/organisations")
def list_organisations(
    _admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """List all campus organisations and operational counts for platform governance."""
    orgs = db.execute(select(Organisation).order_by(Organisation.id.desc())).scalars().all()
    results = []
    for org in orgs:
        outlet_cnt = db.execute(
            select(func.count(Outlet.id)).where(Outlet.organisation_id == org.id)
        ).scalar_one()
        user_cnt = db.execute(
            select(func.count(User.id)).where(User.organisation_id == org.id)
        ).scalar_one()
        live_orders = db.execute(
            select(func.count(Order.id)).where(
                Order.organisation_id == org.id, Order.is_sample.is_(False)
            )
        ).scalar_one()
        results.append(
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "campus_location": org.campus_location,
                "contact_email": org.contact_email,
                "status": org.status,
                "outlet_count": outlet_cnt,
                "user_count": user_cnt,
                "live_orders": live_orders,
                "created_at": org.created_at.isoformat() if org.created_at else None,
            }
        )
    return {"organisations": results}


@router.patch("/organisations/{org_id}")
def update_organisation_status(
    org_id: int,
    payload: OrganisationApprovalRequest,
    request: Request,
    admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Approve, suspend, or reject an onboarded campus organisation."""
    org = db.execute(select(Organisation).where(Organisation.id == org_id)).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found.")

    org.status = payload.status
    if payload.status == "ACTIVE":
        org.approved_by_user_id = admin["id"]
        org.approved_at = datetime.now(timezone.utc)
        db.execute(
            update(User)
            .where(
                User.organisation_id == org.id,
                User.role == "outlet_manager",
                User.manager_approval_status == "PENDING",
            )
            .values(manager_approval_status="APPROVED")
        )
    elif payload.status == "REJECTED":
        db.execute(
            update(User)
            .where(
                User.organisation_id == org.id,
                User.role == "outlet_manager",
                User.manager_approval_status == "PENDING",
            )
            .values(manager_approval_status="REJECTED")
        )

    db.flush()
    record_audit_log(
        db,
        organisation_id=org.id,
        action="ORGANISATION_STATUS_UPDATED",
        resource_type="organisation",
        resource_id=org.id,
        actor_user_id=admin["id"],
        actor_role="admin",
        ip_address=request.client.host if request.client else None,
        details={"status": org.status, "slug": org.slug},
    )
    return {
        "organisation": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "status": org.status,
        }
    }


@router.get("/overview")
def get_admin_overview(
    organisation_id: int | None = None,
    _admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Return platform-wide or per-organisation overview (organisations, outlets, users, audits)."""
    orgs = db.execute(select(Organisation).order_by(Organisation.id)).scalars().all()
    org_lookup = {o.id: o.name for o in orgs}

    outlet_stmt = select(Outlet).order_by(Outlet.organisation_id, Outlet.id)
    if organisation_id is not None:
        outlet_stmt = outlet_stmt.where(Outlet.organisation_id == organisation_id)
    outlet_rows = db.execute(outlet_stmt).scalars().all()

    outlets = []
    for o in outlet_rows:
        menu_count = db.execute(
            select(func.count(MenuItem.id)).where(MenuItem.outlet_id == o.id)
        ).scalar_one()
        low_stock_count = db.execute(
            select(func.count(MenuItem.id)).where(
                MenuItem.outlet_id == o.id, MenuItem.stock_qty <= 5
            )
        ).scalar_one()
        open_orders = db.execute(
            select(func.count(Order.id)).where(
                Order.outlet_id == o.id,
                Order.is_sample.is_(False),
                Order.order_status.in_(("PLACED", "PREPARING")),
            )
        ).scalar_one()
        live_revenue = db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (Order.order_status != "CANCELLED", Order.total_amount),
                            else_=0.0,
                        )
                    ),
                    0.0,
                )
            ).where(Order.outlet_id == o.id, Order.is_sample.is_(False))
        ).scalar_one()
        outlets.append(
            {
                "id": o.id,
                "organisation_id": o.organisation_id,
                "organisation_name": org_lookup.get(o.organisation_id),
                "name": o.name,
                "location": o.location,
                "status": o.status,
                "avg_prep_minutes": o.avg_prep_minutes,
                "active_staff": o.active_staff,
                "menu_count": menu_count,
                "low_stock_count": low_stock_count,
                "open_orders": open_orders,
                "live_revenue": round(float(live_revenue or 0.0), 2),
            }
        )

    user_stmt = (
        select(User, Outlet.name, Organisation.name)
        .outerjoin(Outlet, Outlet.id == User.outlet_id)
        .outerjoin(Organisation, Organisation.id == User.organisation_id)
        .order_by(User.id)
    )
    if organisation_id is not None:
        user_stmt = user_stmt.where(User.organisation_id == organisation_id)
    user_rows = db.execute(user_stmt).all()
    users = [
        {
            "id": u.id,
            "organisation_id": u.organisation_id,
            "organisation_name": org_name or "Platform Global",
            "username": u.username,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "outlet_id": u.outlet_id,
            "outlet_name": oname,
            "is_active": bool(u.is_active),
            "manager_approval_status": u.manager_approval_status,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u, oname, org_name in user_rows
    ]

    audit_stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(35)
    if organisation_id is not None:
        audit_stmt = select(AuditLog).where(
            AuditLog.organisation_id == organisation_id
        ).order_by(AuditLog.id.desc()).limit(35)
    audits = db.execute(audit_stmt).scalars().all()
    audit_logs = [
        {
            "id": a.id,
            "organisation_id": a.organisation_id,
            "actor_user_id": a.actor_user_id,
            "actor_role": a.actor_role,
            "action": a.action,
            "resource_type": a.resource_type,
            "resource_id": a.resource_id,
            "ip_address": a.ip_address,
            "details_json": a.details_json,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in audits
    ]

    return {
        "organisations": [
            {
                "id": o.id,
                "name": o.name,
                "slug": o.slug,
                "campus_location": o.campus_location,
                "contact_email": o.contact_email,
                "status": o.status,
            }
            for o in orgs
        ],
        "outlets": outlets,
        "users": users,
        "audit_logs": audit_logs,
    }


@router.post("/outlets", status_code=status.HTTP_201_CREATED)
def create_platform_outlet(
    payload: AdminCreateOutletRequest,
    request: Request,
    admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Create an outlet under a chosen organisation (Platform Admin)."""
    org = db.execute(
        select(Organisation).where(Organisation.id == payload.organisation_id)
    ).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found.")
    new_outlet = Outlet(
        organisation_id=org.id,
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
        organisation_id=org.id,
        action="ADMIN_CREATED_OUTLET",
        resource_type="outlet",
        resource_id=new_outlet.id,
        actor_user_id=admin["id"],
        actor_role="admin",
        ip_address=request.client.host if request.client else None,
        details={"name": new_outlet.name, "organisation_id": org.id},
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


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_managed_user(
    payload: AdminCreateManagerRequest,
    request: Request,
    admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Provision an approved Outlet/Organisation Manager or Student tied to an organisation."""
    clean_username = payload.username.strip().lower()
    clean_email = str(payload.email).strip().lower()
    if not USERNAME_RE.match(clean_username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3–32 characters using letters, numbers, or underscores.",
        )
    validate_password_strength(payload.password)

    resolved_org_id = payload.organisation_id
    if payload.outlet_id is not None:
        outlet = db.execute(select(Outlet).where(Outlet.id == payload.outlet_id)).scalar_one_or_none()
        if not outlet:
            raise HTTPException(status_code=404, detail="Assigned outlet not found.")
        if resolved_org_id is not None and outlet.organisation_id != resolved_org_id:
            raise HTTPException(
                status_code=400,
                detail="Outlet does not belong to the specified organisation.",
            )
        resolved_org_id = outlet.organisation_id
    elif resolved_org_id is None:
        first_org = db.execute(select(Organisation).order_by(Organisation.id)).scalars().first()
        if not first_org:
            raise HTTPException(status_code=400, detail="organisation_id is required.")
        resolved_org_id = first_org.id
    else:
        org = db.execute(
            select(Organisation).where(Organisation.id == resolved_org_id)
        ).scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found.")

    dup = db.execute(
        select(User).where((User.email == clean_email) | (User.username == clean_username))
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="Username or email already exists.")

    role_obj = db.execute(select(Role).where(Role.name == payload.role)).scalar_one_or_none()
    new_user = User(
        organisation_id=resolved_org_id,
        username=clean_username,
        email=clean_email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        role_id=role_obj.id if role_obj else None,
        outlet_id=payload.outlet_id if payload.role == "outlet_manager" else None,
        is_active=True,
        manager_approval_status="APPROVED",
    )
    db.add(new_user)
    db.flush()

    record_audit_log(
        db,
        organisation_id=resolved_org_id,
        action="ADMIN_CREATED_USER",
        resource_type="user",
        resource_id=new_user.id,
        actor_user_id=admin["id"],
        actor_role="admin",
        ip_address=request.client.host if request.client else None,
        details={
            "role": payload.role,
            "organisation_id": resolved_org_id,
            "outlet_id": new_user.outlet_id,
        },
    )
    return {
        "user": {
            "id": new_user.id,
            "organisation_id": new_user.organisation_id,
            "username": new_user.username,
            "email": new_user.email,
            "full_name": new_user.full_name,
            "role": new_user.role,
            "outlet_id": new_user.outlet_id,
            "is_active": new_user.is_active,
        }
    }


@router.patch("/users/{user_id}")
def update_user_access(
    user_id: int,
    payload: AdminUpdateUserRequest,
    request: Request,
    admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Approve/assign outlet managers, update tenant binding, or activate/deactivate accounts."""
    target = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == admin["id"] and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Admin cannot deactivate own account.")
    if target.id == admin["id"] and payload.role and payload.role != "admin":
        raise HTTPException(status_code=400, detail="Admin cannot downgrade own role.")

    if payload.organisation_id is not None:
        org = db.execute(
            select(Organisation).where(Organisation.id == payload.organisation_id)
        ).scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found.")
        target.organisation_id = org.id

    if payload.role is not None:
        role_obj = db.execute(select(Role).where(Role.name == payload.role)).scalar_one_or_none()
        target.role = payload.role
        target.role_id = role_obj.id if role_obj else None

    if payload.outlet_id is not None:
        outlet = db.execute(select(Outlet).where(Outlet.id == payload.outlet_id)).scalar_one_or_none()
        if not outlet:
            raise HTTPException(status_code=404, detail="Outlet not found.")
        if target.organisation_id is not None and outlet.organisation_id != target.organisation_id:
            raise HTTPException(
                status_code=400,
                detail="Outlet does not belong to user's organisation.",
            )
        target.outlet_id = payload.outlet_id
    elif target.role != "outlet_manager":
        target.outlet_id = None

    if payload.is_active is not None:
        target.is_active = payload.is_active
    if payload.manager_approval_status is not None:
        target.manager_approval_status = payload.manager_approval_status

    db.flush()
    record_audit_log(
        db,
        organisation_id=target.organisation_id,
        action="USER_ACCESS_UPDATED",
        resource_type="user",
        resource_id=target.id,
        actor_user_id=admin["id"],
        actor_role="admin",
        ip_address=request.client.host if request.client else None,
        details={
            "role": target.role,
            "organisation_id": target.organisation_id,
            "outlet_id": target.outlet_id,
            "is_active": target.is_active,
        },
    )
    return {
        "user": {
            "id": target.id,
            "organisation_id": target.organisation_id,
            "username": target.username,
            "role": target.role,
            "outlet_id": target.outlet_id,
            "is_active": target.is_active,
            "manager_approval_status": target.manager_approval_status,
        }
    }


@router.patch("/outlets/{outlet_id}")
def update_outlet_config(
    outlet_id: int,
    payload: OutletUpdateRequest,
    request: Request,
    admin: dict = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Update operational status, active staff count, or average prep SLA for an outlet."""
    existing = db.execute(select(Outlet).where(Outlet.id == outlet_id)).scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Outlet not found.")

    if payload.status is not None:
        existing.status = payload.status
    if payload.active_staff is not None:
        existing.active_staff = payload.active_staff
    if payload.avg_prep_minutes is not None:
        existing.avg_prep_minutes = payload.avg_prep_minutes
    db.flush()

    record_audit_log(
        db,
        organisation_id=existing.organisation_id,
        action="OUTLET_CONFIG_UPDATED",
        resource_type="outlet",
        resource_id=existing.id,
        actor_user_id=admin["id"],
        actor_role="admin",
        ip_address=request.client.host if request.client else None,
        details={
            "status": existing.status,
            "active_staff": existing.active_staff,
            "avg_prep_minutes": existing.avg_prep_minutes,
        },
    )
    return {
        "outlet": {
            "id": existing.id,
            "organisation_id": existing.organisation_id,
            "name": existing.name,
            "location": existing.location,
            "status": existing.status,
            "avg_prep_minutes": existing.avg_prep_minutes,
            "active_staff": existing.active_staff,
        }
    }
