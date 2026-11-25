"""Tenant-isolated student reviews and feedback-to-action routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.orchestrator import orchestrate_review_to_action
from app.agents.review_agent import get_feedback_intelligence
from app.database import get_db
from app.models import Outlet, Review
from app.schemas import ReviewCreateRequest
from app.services.audit_service import record_audit_log
from app.services.auth_service import get_current_user, require_roles

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("")
def list_reviews(
    organisation_id: int | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return Review & Feedback breakdown strictly within caller's organisation."""
    role = current_user["role"]
    if role == "admin":
        org_scope = organisation_id
        outlet_scope = None
    else:
        org_scope = current_user.get("organisation_id")
        if organisation_id is not None and organisation_id != org_scope:
            raise HTTPException(
                status_code=403,
                detail="Access denied: cannot view reviews of another organisation.",
            )
        outlet_scope = current_user.get("outlet_id") if role == "outlet_manager" else None

    return get_feedback_intelligence(db, outlet_id=outlet_scope, organisation_id=org_scope)


@router.post("")
def submit_review(
    payload: ReviewCreateRequest,
    current_user: dict = Depends(require_roles("student", "admin")),
    db: Session = Depends(get_db),
):
    """Submit a student review for an outlet inside the caller's own organisation."""
    outlet = db.execute(select(Outlet).where(Outlet.id == payload.outlet_id)).scalar_one_or_none()
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet not found.")
    if (
        current_user["role"] != "admin"
        and outlet.organisation_id != current_user.get("organisation_id")
    ):
        raise HTTPException(
            status_code=403,
            detail="Access denied: cannot submit a review for another organisation's outlet.",
        )

    return orchestrate_review_to_action(
        db,
        payload.outlet_id,
        payload.order_id,
        payload.student_name,
        payload.rating,
        payload.comment,
        user_id=current_user["id"],
    )


@router.post("/{review_id}/resolve")
def resolve_review_issue(
    review_id: int,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Track that a reported review complaint has been resolved within caller's tenant/outlet."""
    row = db.execute(select(Review).where(Review.id == review_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Review not found.")

    if current_user["role"] == "outlet_manager":
        if row.organisation_id != current_user.get("organisation_id"):
            raise HTTPException(
                status_code=403,
                detail="Access denied: review belongs to another organisation.",
            )
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None and row.outlet_id != assigned_oid:
            raise HTTPException(
                status_code=403,
                detail="Cannot resolve reviews belonging to another outlet.",
            )

    row.is_resolved = True
    row.resolved_by_user_id = current_user["id"]
    row.resolved_at = datetime.now(timezone.utc)
    record_audit_log(
        db,
        organisation_id=row.organisation_id,
        action="REVIEW_RESOLVED",
        resource_type="review",
        resource_id=review_id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
    )
    db.flush()
    return {"review_id": review_id, "is_resolved": True}
