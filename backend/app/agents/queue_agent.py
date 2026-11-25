"""Queue Agent: estimates prep wait times, peak congestion, and multi-canteen smart routing."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, Outlet


def get_queue_status(
    db: Session,
    outlet_id: int | None = None,
    organisation_id: int | None = None,
) -> dict:
    """Compute live queue load per outlet within tenant scope and recommend fastest OPEN routing."""
    stmt = select(Outlet).order_by(Outlet.id)
    if organisation_id is not None:
        stmt = stmt.where(Outlet.organisation_id == organisation_id)
    if outlet_id is not None:
        stmt = stmt.where(Outlet.id == outlet_id)
    outlets = db.execute(stmt).scalars().all()

    statuses = []
    for o in outlets:
        active_cnt = db.execute(
            select(func.count(Order.id)).where(
                Order.outlet_id == o.id,
                Order.is_sample.is_(False),
                Order.order_status.in_(("PLACED", "PREPARING")),
            )
        ).scalar_one()

        sample_rush_cnt = db.execute(
            select(func.count(Order.id)).where(
                Order.outlet_id == o.id,
                Order.is_sample.is_(True),
                Order.scheduled_slot == "11:00",
            )
        ).scalar_one()

        staff = max(1, o.active_staff)
        est_wait = round(o.avg_prep_minutes + (active_cnt * 3) / staff, 1)
        congestion = (
            "HIGH"
            if active_cnt >= 4 or sample_rush_cnt >= 2 or o.status == "BUSY"
            else "MODERATE"
            if active_cnt >= 2
            else "LOW"
        )
        statuses.append(
            {
                "outlet_id": o.id,
                "outlet_name": o.name,
                "location": o.location,
                "status": o.status,
                "active_staff": o.active_staff,
                "active_queue_orders": active_cnt,
                "estimated_wait_minutes": est_wait,
                "congestion_level": congestion,
                "batching_advice": (
                    f"{o.name} is currently CLOSED."
                    if o.status == "CLOSED"
                    else f"Batch similar quick-prep items at {o.name} to cut break bottlenecks."
                    if congestion != "LOW"
                    else f"{o.name} has smooth queue flow."
                ),
            }
        )

    open_statuses = [s for s in statuses if s["status"] != "CLOSED"]
    fastest = (
        min(open_statuses, key=lambda x: x["estimated_wait_minutes"])
        if open_statuses
        else (statuses[0] if statuses else None)
    )
    return {
        "agent": "Queue Agent",
        "outlet_queues": statuses,
        "recommended_fastest_outlet": fastest,
        "sample_peak_hours": ["11:00 AM Short Break", "01:00 PM Lunch Window"],
    }
