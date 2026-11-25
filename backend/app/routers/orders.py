"""Tenant-isolated order placement, tracking, group orders, queue preparation, and cancellation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderItem, Outlet, QrToken
from app.schemas import OrderCreateRequest, RefundRequest
from app.services.audit_service import record_audit_log
from app.services.auth_service import get_current_user, require_roles
from app.services.qr_service import render_qr_base64
from app.services.rules_engine import (
    evaluate_cancellation_and_refund,
    place_order_and_issue_qr,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("/checkout")
def checkout_order(
    payload: OrderCreateRequest,
    current_user: dict = Depends(require_roles("student", "admin")),
    db: Session = Depends(get_db),
):
    """Place an order strictly inside caller's organisation and issue single-use QR pass."""
    org_scope = None if current_user["role"] == "admin" else current_user.get("organisation_id")
    return place_order_and_issue_qr(
        db, payload, user_id=current_user["id"], organisation_scope_id=org_scope
    )


@router.get("")
def list_orders(
    include_sample: bool = False,
    outlet_id: int | None = None,
    organisation_id: int | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List orders strictly scoped by server-verified organisation, role, and outlet."""
    stmt = (
        select(
            Order,
            Outlet.name.label("outlet_name"),
            QrToken.token.label("qr_token"),
            QrToken.status.label("qr_status"),
            QrToken.scan_count.label("scan_count"),
        )
        .join(Outlet, Outlet.id == Order.outlet_id)
        .outerjoin(QrToken, QrToken.order_id == Order.id)
    )

    if not include_sample:
        stmt = stmt.where(Order.is_sample.is_(False))

    role = current_user["role"]
    user_org_id = current_user.get("organisation_id")

    if role != "admin" and organisation_id is not None and organisation_id != user_org_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: cannot view orders from another organisation.",
        )

    if role == "student":
        stmt = stmt.where(
            Order.organisation_id == user_org_id,
            (Order.user_id == current_user["id"])
            | (
                Order.user_id.is_(None)
                & (func.lower(Order.student_name) == current_user["full_name"].lower())
            ),
        )
    elif role == "outlet_manager":
        stmt = stmt.where(Order.organisation_id == user_org_id)
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None:
            if outlet_id is not None and outlet_id != assigned_oid:
                raise HTTPException(status_code=403, detail="Cannot view orders of another outlet.")
            stmt = stmt.where(Order.outlet_id == assigned_oid)
        elif outlet_id is not None:
            outlet_obj = db.execute(select(Outlet).where(Outlet.id == outlet_id)).scalar_one_or_none()
            if not outlet_obj or outlet_obj.organisation_id != user_org_id:
                raise HTTPException(status_code=403, detail="Outlet does not belong to your organisation.")
            stmt = stmt.where(Order.outlet_id == outlet_id)
    else:
        if organisation_id is not None:
            stmt = stmt.where(Order.organisation_id == organisation_id)
        if outlet_id is not None:
            stmt = stmt.where(Order.outlet_id == outlet_id)

    rows = db.execute(stmt.order_by(Order.id.desc()).limit(50)).all()

    results = []
    for ord_obj, outlet_name, qr_token, qr_status, scan_count in rows:
        item_rows = db.execute(
            select(OrderItem).where(OrderItem.order_id == ord_obj.id)
        ).scalars().all()
        order_dict = {
            "id": ord_obj.id,
            "organisation_id": ord_obj.organisation_id,
            "order_code": ord_obj.order_code,
            "outlet_id": ord_obj.outlet_id,
            "user_id": ord_obj.user_id,
            "student_name": ord_obj.student_name,
            "group_code": ord_obj.group_code,
            "scheduled_slot": ord_obj.scheduled_slot,
            "total_amount": ord_obj.total_amount,
            "payment_status": ord_obj.payment_status,
            "order_status": ord_obj.order_status,
            "estimated_wait_minutes": ord_obj.estimated_wait_minutes,
            "is_sample": int(bool(ord_obj.is_sample)),
            "created_at": ord_obj.created_at.isoformat() if ord_obj.created_at else None,
            "outlet_name": outlet_name,
            "qr_token": qr_token,
            "qr_status": qr_status,
            "scan_count": scan_count,
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
        if role in ("student", "admin") and qr_token:
            order_dict["qr_image"] = render_qr_base64(qr_token)
        results.append(order_dict)

    return {"orders": results}


@router.get("/group/{group_code}")
def get_group_orders(
    group_code: str,
    organisation_id: int | None = None,
    current_user: dict = Depends(require_roles("student", "admin")),
    db: Session = Depends(get_db),
):
    """Return combined orders linked to a group code strictly inside caller's organisation."""
    clean_code = group_code.strip().upper()
    stmt = (
        select(Order, Outlet.name.label("outlet_name"))
        .join(Outlet, Outlet.id == Order.outlet_id)
        .where(Order.group_code == clean_code, Order.is_sample.is_(False))
    )
    if current_user["role"] == "admin":
        if organisation_id is not None:
            stmt = stmt.where(Order.organisation_id == organisation_id)
    else:
        stmt = stmt.where(Order.organisation_id == current_user.get("organisation_id"))

    rows = db.execute(stmt.order_by(Order.id.desc())).all()
    members = [
        {
            "id": o.id,
            "organisation_id": o.organisation_id,
            "order_code": o.order_code,
            "student_name": o.student_name,
            "total_amount": o.total_amount,
            "order_status": o.order_status,
            "estimated_wait_minutes": o.estimated_wait_minutes,
            "outlet_name": oname,
        }
        for o, oname in rows
    ]
    return {
        "group_code": clean_code,
        "member_count": len(members),
        "combined_total": round(sum(m["total_amount"] for m in members), 2),
        "orders": members,
    }


@router.post("/{order_id}/cancel")
def cancel_or_refund_order(
    order_id: int,
    payload: RefundRequest,
    current_user: dict = Depends(require_roles("student", "admin")),
    db: Session = Depends(get_db),
):
    """Evaluate cancellation and simulated refund eligibility inside caller's organisation."""
    org_scope = None if current_user["role"] == "admin" else current_user.get("organisation_id")
    if current_user["role"] == "student":
        owner = db.execute(select(Order).where(Order.id == order_id)).scalar_one_or_none()
        if owner:
            if owner.organisation_id != org_scope:
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: order belongs to another organisation.",
                )
            if owner.user_id is not None and owner.user_id != current_user["id"]:
                raise HTTPException(
                    status_code=403,
                    detail="You can only cancel or request refunds for your own orders.",
                )
    return evaluate_cancellation_and_refund(
        db,
        order_id,
        payload.reason,
        actor_user_id=current_user["id"],
        organisation_scope_id=org_scope,
    )


@router.post("/{order_id}/prepare")
def mark_order_preparing(
    order_id: int,
    current_user: dict = Depends(require_roles("outlet_manager", "admin")),
    db: Session = Depends(get_db),
):
    """Transition a PLACED order to PREPARING strictly within permitted tenant/outlet scope."""
    order = db.execute(select(Order).where(Order.id == order_id)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if current_user["role"] == "outlet_manager":
        if order.organisation_id != current_user.get("organisation_id"):
            raise HTTPException(
                status_code=403,
                detail="Access denied: order belongs to another organisation.",
            )
        assigned_oid = current_user.get("outlet_id")
        if assigned_oid is not None and order.outlet_id != assigned_oid:
            raise HTTPException(
                status_code=403,
                detail="Cannot modify orders belonging to another outlet.",
            )

    if order.order_status != "PLACED":
        raise HTTPException(
            status_code=400,
            detail=f"Order {order.order_code} is currently '{order.order_status}' and cannot move to PREPARING.",
        )
    order.order_status = "PREPARING"
    record_audit_log(
        db,
        organisation_id=order.organisation_id,
        action="ORDER_MARKED_PREPARING",
        resource_type="order",
        resource_id=order.id,
        actor_user_id=current_user["id"],
        actor_role=current_user["role"],
        details={"order_code": order.order_code},
    )
    db.flush()
    return {"order_id": order.id, "order_code": order.order_code, "order_status": "PREPARING"}
