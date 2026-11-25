"""Tenant-scoped catalog overview and development-only demo-reset routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import MenuItem, Outlet
from app.seed_data import reset_database
from app.services.auth_service import get_current_user, require_roles

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/catalog/overview")
def get_catalog_overview(
    organisation_id: int | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return outlets and menu items strictly scoped to user's organisation (admin may filter)."""
    if current_user["role"] == "admin":
        target_org_id = organisation_id
    else:
        target_org_id = current_user.get("organisation_id")
        if organisation_id is not None and organisation_id != target_org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: cannot view catalog for another organisation.",
            )

    outlet_stmt = select(Outlet).order_by(Outlet.id)
    item_stmt = (
        select(MenuItem, Outlet.name.label("outlet_name"))
        .join(Outlet, Outlet.id == MenuItem.outlet_id)
        .order_by(MenuItem.outlet_id, MenuItem.id)
    )
    if target_org_id is not None:
        outlet_stmt = outlet_stmt.where(Outlet.organisation_id == target_org_id)
        item_stmt = item_stmt.where(MenuItem.organisation_id == target_org_id)

    outlets = db.execute(outlet_stmt).scalars().all()
    item_rows = db.execute(item_stmt).all()

    by_id = {mi.id: mi for mi, _ in item_rows}
    items = []
    for mi, oname in item_rows:
        sub = by_id.get(mi.substitute_item_id) if mi.substitute_item_id else None
        items.append(
            {
                "id": mi.id,
                "organisation_id": mi.organisation_id,
                "outlet_id": mi.outlet_id,
                "outlet_name": oname,
                "name": mi.name,
                "description": mi.description,
                "image_url": mi.image_url,
                "category": mi.category,
                "price": mi.price,
                "stock_qty": mi.stock_qty,
                "prep_minutes": mi.prep_minutes,
                "is_veg": int(bool(mi.is_veg)),
                "is_available": bool(mi.is_available),
                "substitute_item_id": mi.substitute_item_id,
                "substitute_name": sub.name if sub else None,
                "substitute_price": sub.price if sub else None,
            }
        )

    return {
        "organisation_id": target_org_id,
        "outlets": [
            {
                "id": o.id,
                "organisation_id": o.organisation_id,
                "name": o.name,
                "location": o.location,
                "status": o.status,
                "avg_prep_minutes": o.avg_prep_minutes,
                "active_staff": o.active_staff,
            }
            for o in outlets
        ],
        "menu_items": items,
    }


@router.post("/demo/reset")
def reset_demo_state(_admin: dict = Depends(require_roles("admin"))):
    """Reset operational tables to dev sample state (permanently disabled in production)."""
    if settings.is_production or not settings.effective_demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo reset is disabled in production mode.",
        )
    reset_database()
    return {"status": "reset_complete", "message": "Database restored to clean seeded demo state."}
