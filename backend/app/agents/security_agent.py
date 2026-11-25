"""Security Agent: analyses transaction/QR anomalies and summarises human-readable risk briefs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, SecurityEvent
from app.services.llm_client import generate_llm_text


def get_security_summary(
    db: Session,
    outlet_id: int | None = None,
    organisation_id: int | None = None,
) -> dict:
    """Summarize security events strictly within tenant & outlet scope."""
    stmt = (
        select(SecurityEvent, Order.order_code, Order.student_name, Order.outlet_id)
        .outerjoin(Order, Order.id == SecurityEvent.order_id)
    )
    if organisation_id is not None:
        stmt = stmt.where(SecurityEvent.organisation_id == organisation_id)
    if outlet_id is not None:
        stmt = stmt.where(Order.outlet_id == outlet_id)
    rows = db.execute(stmt.order_by(SecurityEvent.id.desc()).limit(25)).all()
    events = [
        {
            "id": ev.id,
            "order_id": ev.order_id,
            "token": ev.token,
            "event_type": ev.event_type,
            "risk_level": ev.risk_level,
            "ai_explanation": ev.ai_explanation,
            "requires_human_review": int(bool(ev.requires_human_review)),
            "resolved": int(bool(ev.resolved)),
            "order_code": order_code,
            "student_name": student_name,
            "outlet_id": oid,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev, order_code, student_name, oid in rows
    ]

    high_risk = sum(1 for e in events if e["risk_level"] == "HIGH")
    open_reviews = sum(1 for e in events if e["requires_human_review"] == 1 and e["resolved"] == 0)

    brief = None
    if events:
        latest = events[0]
        llm_summary = generate_llm_text(
            "You are the Security Agent of a campus canteen system. Never claim to authorise payments or refunds. Briefly explain the latest security incident in 2 sentences for a canteen supervisor.",
            f"Latest event: {latest['event_type']} (risk={latest['risk_level']}). Details: {latest['ai_explanation']}",
            max_tokens=140,
        )
        brief = llm_summary or latest["ai_explanation"]

    return {
        "agent": "Security Agent",
        "total_events": len(events),
        "high_risk_count": high_risk,
        "pending_human_reviews": open_reviews,
        "latest_brief": brief or "No transaction or QR security anomalies recorded.",
        "events": events,
    }
