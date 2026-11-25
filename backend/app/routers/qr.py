"""Tenant-isolated QR verification and security-event feed routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, SecurityEvent
from app.schemas import QRVerifyRequest
from app.services.auth_service import require_roles
from app.services.rules_engine import verify_and_collect_qr

router = APIRouter(prefix="/api/qr", tags=["qr-security"])


@router.post("/verify")
def verify_qr(
    payload: QRVerifyRequest,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Verify a scanned QR token strictly inside caller's organisation & assigned outlet."""
    role = current_user["role"]
    org_scope = None if role == "admin" else current_user.get("organisation_id")
    outlet_scope = current_user.get("outlet_id") if role == "outlet_manager" else None
    return verify_and_collect_qr(
        db,
        payload.token,
        organisation_scope_id=org_scope,
        outlet_scope_id=outlet_scope,
        verified_by_user_id=current_user["id"],
    )


@router.get("/security-events")
def list_security_events(
    organisation_id: int | None = None,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Return recorded security events strictly isolated by organisation & outlet scope."""
    role = current_user["role"]
    user_org_id = current_user.get("organisation_id")

    if role == "outlet_manager":
        if organisation_id is not None and organisation_id != user_org_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: cannot view security logs for another organisation.",
            )
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None:
            rows = db.execute(
                select(SecurityEvent, Order.order_code, Order.student_name)
                .join(Order, Order.id == SecurityEvent.order_id)
                .where(
                    SecurityEvent.organisation_id == user_org_id,
                    Order.outlet_id == assigned_oid,
                )
                .order_by(SecurityEvent.id.desc())
                .limit(40)
            ).all()
        else:
            rows = db.execute(
                select(SecurityEvent, Order.order_code, Order.student_name)
                .outerjoin(Order, Order.id == SecurityEvent.order_id)
                .where(SecurityEvent.organisation_id == user_org_id)
                .order_by(SecurityEvent.id.desc())
                .limit(40)
            ).all()
    else:
        stmt = (
            select(SecurityEvent, Order.order_code, Order.student_name)
            .outerjoin(Order, Order.id == SecurityEvent.order_id)
        )
        if organisation_id is not None:
            stmt = stmt.where(SecurityEvent.organisation_id == organisation_id)
        rows = db.execute(stmt.order_by(SecurityEvent.id.desc()).limit(40)).all()

    return {
        "events": [
            {
                "id": ev.id,
                "organisation_id": ev.organisation_id,
                "order_id": ev.order_id,
                "token": ev.token,
                "event_type": ev.event_type,
                "risk_level": ev.risk_level,
                "ai_explanation": ev.ai_explanation,
                "requires_human_review": int(bool(ev.requires_human_review)),
                "resolved": int(bool(ev.resolved)),
                "order_code": order_code,
                "student_name": student_name,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev, order_code, student_name in rows
        ]
    }
