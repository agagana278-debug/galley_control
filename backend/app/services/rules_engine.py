"""Tenant-isolated deterministic business rules for ordering, QR security, and refunds."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    InventoryMovement,
    MenuItem,
    Order,
    OrderItem,
    Outlet,
    QrToken,
    SecurityEvent,
)
from app.schemas import OrderCreateRequest
from app.services.audit_service import record_audit_log
from app.services.qr_service import generate_qr_token, render_qr_base64


def compute_queue_eta(db: Session, outlet_id: int, max_item_prep: int) -> int:
    """Calculate deterministic wait ETA from active queued orders and item prep time."""
    active_orders = db.execute(
        select(func.count(Order.id)).where(
            Order.outlet_id == outlet_id,
            Order.is_sample.is_(False),
            Order.order_status.in_(("PLACED", "PREPARING")),
        )
    ).scalar_one()

    staff_val = db.execute(
        select(Outlet.active_staff).where(Outlet.id == outlet_id)
    ).scalar_one_or_none()
    staff = max(1, int(staff_val or 2))
    queue_delay = round((active_orders * 3) / staff)
    return max(2, max_item_prep + queue_delay)


def place_order_and_issue_qr(
    db: Session,
    payload: OrderCreateRequest,
    user_id: int | None = None,
    organisation_scope_id: int | None = None,
) -> dict:
    """Validate tenant ownership, stock, simulated payment, persist order, and issue QR."""
    outlet = db.execute(
        select(Outlet).where(Outlet.id == payload.outlet_id)
    ).scalar_one_or_none()
    if not outlet:
        raise HTTPException(status_code=404, detail="Selected outlet not found.")

    if organisation_scope_id is not None and outlet.organisation_id != organisation_scope_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: selected outlet belongs to another organisation.",
        )

    tenant_org_id = outlet.organisation_id
    if outlet.status == "CLOSED":
        raise HTTPException(
            status_code=400,
            detail=f"{outlet.name} is currently CLOSED and not accepting orders.",
        )

    resolved_items: list[tuple[MenuItem, int]] = []
    total_amount = 0.0
    max_prep = 2

    for req_item in payload.items:
        item = db.execute(
            select(MenuItem).where(MenuItem.id == req_item.menu_item_id)
        ).scalar_one_or_none()
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Menu item {req_item.menu_item_id} does not exist.",
            )
        if item.organisation_id != tenant_org_id:
            raise HTTPException(
                status_code=403,
                detail="Menu item belongs to another organisation.",
            )
        if item.outlet_id != payload.outlet_id:
            raise HTTPException(
                status_code=400,
                detail=f"{item.name} belongs to another outlet. Keep items within one outlet per checkout.",
            )
        if not item.is_available or item.stock_qty < req_item.quantity:
            substitute = None
            if item.substitute_item_id:
                sub = db.execute(
                    select(MenuItem).where(MenuItem.id == item.substitute_item_id)
                ).scalar_one_or_none()
                if (
                    sub
                    and sub.organisation_id == tenant_org_id
                    and sub.is_available
                    and sub.stock_qty >= req_item.quantity
                ):
                    substitute = {
                        "id": sub.id,
                        "name": sub.name,
                        "price": sub.price,
                        "stock_qty": sub.stock_qty,
                    }
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"{item.name} is out of stock (available: {item.stock_qty}).",
                    "unavailable_item_id": item.id,
                    "unavailable_item_name": item.name,
                    "substitute": substitute,
                },
            )

        total_amount = round(total_amount + (item.price * req_item.quantity), 2)
        max_prep = max(max_prep, item.prep_minutes)
        resolved_items.append((item, req_item.quantity))

    if not payload.simulate_payment_success:
        db.add(
            SecurityEvent(
                organisation_id=tenant_org_id,
                event_type="SIMULATED_PAYMENT_FAILED",
                risk_level="LOW",
                ai_explanation=(
                    f"Simulated payment declined for {payload.student_name} at {outlet.name} "
                    f"(amount ₹{total_amount:.2f}). Order was not confirmed and stock was untouched."
                ),
                requires_human_review=False,
            )
        )
        db.commit()
        raise HTTPException(
            status_code=402,
            detail="Simulated payment failed. Stock preserved; retry checkout.",
        )

    eta_minutes = compute_queue_eta(db, payload.outlet_id, max_prep)
    order_code = f"ORD-{secrets.token_hex(3).upper()}"
    group_code = payload.group_code.strip().upper() if payload.group_code else None
    scheduled_slot = payload.scheduled_slot.strip() if payload.scheduled_slot else "ASAP"

    new_order = Order(
        organisation_id=tenant_org_id,
        order_code=order_code,
        outlet_id=payload.outlet_id,
        user_id=user_id,
        student_name=payload.student_name.strip(),
        group_code=group_code,
        scheduled_slot=scheduled_slot,
        total_amount=total_amount,
        payment_status="PAID_SIMULATED",
        order_status="PLACED",
        estimated_wait_minutes=eta_minutes,
        is_sample=False,
    )
    db.add(new_order)
    db.flush()

    item_summaries = []
    for item, qty in resolved_items:
        updated = db.execute(
            update(MenuItem)
            .where(and_(MenuItem.id == item.id, MenuItem.stock_qty >= qty))
            .values(stock_qty=MenuItem.stock_qty - qty)
        )
        if updated.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient stock for {item.name} due to concurrent order.",
            )
        db.refresh(item)
        db.add(
            InventoryMovement(
                organisation_id=tenant_org_id,
                menu_item_id=item.id,
                outlet_id=item.outlet_id,
                delta_qty=-qty,
                new_stock_qty=item.stock_qty,
                reason=f"ORDER_PLACED:{order_code}",
                actor_user_id=user_id,
            )
        )
        db.add(
            OrderItem(
                organisation_id=tenant_org_id,
                order_id=new_order.id,
                menu_item_id=item.id,
                item_name=item.name,
                quantity=qty,
                unit_price=item.price,
            )
        )
        item_summaries.append(
            {
                "menu_item_id": item.id,
                "item_name": item.name,
                "quantity": qty,
                "unit_price": item.price,
            }
        )

    qr_token = generate_qr_token(order_code)
    db.add(
        QrToken(
            organisation_id=tenant_org_id,
            order_id=new_order.id,
            token=qr_token,
            status="ACTIVE",
            scan_count=0,
        )
    )
    record_audit_log(
        db,
        organisation_id=tenant_org_id,
        action="ORDER_PLACED",
        resource_type="order",
        resource_id=new_order.id,
        actor_user_id=user_id,
        details={"order_code": order_code, "outlet_id": payload.outlet_id, "total": total_amount},
    )
    db.flush()

    return {
        "order_id": new_order.id,
        "organisation_id": tenant_org_id,
        "order_code": order_code,
        "outlet_id": payload.outlet_id,
        "outlet_name": outlet.name,
        "student_name": new_order.student_name,
        "group_code": group_code,
        "scheduled_slot": scheduled_slot,
        "total_amount": total_amount,
        "payment_status": "PAID_SIMULATED",
        "order_status": "PLACED",
        "estimated_wait_minutes": eta_minutes,
        "items": item_summaries,
        "qr_token": qr_token,
        "qr_status": "ACTIVE",
        "qr_image": render_qr_base64(qr_token),
    }


def verify_and_collect_qr(
    db: Session,
    token: str,
    organisation_scope_id: int | None = None,
    outlet_scope_id: int | None = None,
    verified_by_user_id: int | None = None,
) -> dict:
    """Deterministically verify single-use QR pickup within tenant & outlet scope."""
    clean_token = token.strip()
    row = db.execute(
        select(QrToken, Order, Outlet.name)
        .join(Order, Order.id == QrToken.order_id)
        .join(Outlet, Outlet.id == Order.outlet_id)
        .where(QrToken.token == clean_token)
    ).first()

    if not row:
        explanation = (
            f"Unrecognised QR token '{clean_token}' scanned. Token does not exist in database; "
            "rejected deterministically to prevent counterfeit pickup."
        )
        db.add(
            SecurityEvent(
                organisation_id=organisation_scope_id,
                token=clean_token,
                event_type="INVALID_QR_ATTEMPT",
                risk_level="MEDIUM",
                ai_explanation=explanation,
                requires_human_review=True,
            )
        )
        record_audit_log(
            db,
            organisation_id=organisation_scope_id,
            action="QR_REJECTED_INVALID",
            resource_type="qr_token",
            resource_id=clean_token,
            actor_user_id=verified_by_user_id,
        )
        return {
            "valid": False,
            "reason": "INVALID_TOKEN",
            "risk_level": "MEDIUM",
            "message": "Invalid QR code. No matching order found.",
            "explanation": explanation,
        }

    qr_row, order_row, outlet_name = row

    if organisation_scope_id is not None and order_row.organisation_id != organisation_scope_id:
        raise HTTPException(
            status_code=403,
            detail="Tenant scope mismatch: QR pass belongs to another organisation.",
        )

    if outlet_scope_id is not None and order_row.outlet_id != outlet_scope_id:
        raise HTTPException(
            status_code=403,
            detail=f"Outlet scope mismatch: pass belongs to {outlet_name}, not your assigned outlet.",
        )

    if qr_row.status == "ACTIVE":
        now = datetime.now(timezone.utc)
        updated = db.execute(
            update(QrToken)
            .where(and_(QrToken.id == qr_row.id, QrToken.status == "ACTIVE"))
            .values(
                status="COLLECTED",
                scan_count=QrToken.scan_count + 1,
                collected_at=now,
                verified_by_user_id=verified_by_user_id,
            )
        )
        if updated.rowcount == 1:
            order_row.order_status = "COLLECTED"
            record_audit_log(
                db,
                organisation_id=order_row.organisation_id,
                action="QR_COLLECTED",
                resource_type="order",
                resource_id=order_row.id,
                actor_user_id=verified_by_user_id,
                details={"order_code": order_row.order_code},
            )
            db.flush()
            return {
                "valid": True,
                "reason": "COLLECTED_OK",
                "risk_level": "NONE",
                "message": f"Order {order_row.order_code} verified and marked COLLECTED.",
                "explanation": "Single-use QR validated by backend rules and permanently invalidated.",
                "order": {
                    "order_id": order_row.id,
                    "order_code": order_row.order_code,
                    "student_name": order_row.student_name,
                    "outlet_name": outlet_name,
                    "total_amount": order_row.total_amount,
                    "token": clean_token,
                },
            }

    qr_row.scan_count += 1
    if qr_row.status == "CANCELLED":
        event_type = "CANCELLED_QR_ATTEMPT"
        risk_level = "MEDIUM"
        msg = f"Order {order_row.order_code} was cancelled/refunded. Collection rejected."
        explanation = (
            f"QR token {clean_token} belongs to cancelled order {order_row.order_code} "
            f"({order_row.student_name}). Deterministic backend blocked pickup after cancellation."
        )
    else:
        event_type = "DUPLICATE_QR_REUSE"
        risk_level = "HIGH"
        msg = f"DUPLICATE QR BLOCKED: Order {order_row.order_code} was already collected!"
        explanation = (
            f"Security Guard flagged attempt #{qr_row.scan_count} on already-collected "
            f"token {clean_token} for {order_row.order_code} ({order_row.student_name} at {outlet_name}, "
            f"collected at {qr_row.collected_at}). Escalated for supervisor awareness."
        )

    db.add(
        SecurityEvent(
            organisation_id=order_row.organisation_id,
            order_id=order_row.id,
            token=clean_token,
            event_type=event_type,
            risk_level=risk_level,
            ai_explanation=explanation,
            requires_human_review=True,
        )
    )
    record_audit_log(
        db,
        organisation_id=order_row.organisation_id,
        action=f"QR_BLOCKED_{event_type}",
        resource_type="order",
        resource_id=order_row.id,
        actor_user_id=verified_by_user_id,
        details={"token": clean_token},
    )
    db.flush()

    return {
        "valid": False,
        "reason": event_type,
        "risk_level": risk_level,
        "message": msg,
        "explanation": explanation,
        "order": {
            "order_id": order_row.id,
            "order_code": order_row.order_code,
            "student_name": order_row.student_name,
            "outlet_name": outlet_name,
            "total_amount": order_row.total_amount,
            "token": clean_token,
            "collected_at": qr_row.collected_at.isoformat() if qr_row.collected_at else None,
        },
    }


def evaluate_cancellation_and_refund(
    db: Session,
    order_id: int,
    reason: str,
    actor_user_id: int | None = None,
    organisation_scope_id: int | None = None,
) -> dict:
    """Apply deterministic refund rules strictly within caller's tenant boundary."""
    row = db.execute(
        select(Order, QrToken)
        .outerjoin(QrToken, QrToken.order_id == Order.id)
        .where(Order.id == order_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found.")

    order, qr_tok = row
    if organisation_scope_id is not None and order.organisation_id != organisation_scope_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: order belongs to another organisation.",
        )

    if order.order_status == "CANCELLED":
        return {
            "order_id": order_id,
            "decision": "ALREADY_CANCELLED",
            "refund_approved": False,
            "requires_human_review": False,
            "message": f"Order {order.order_code} was already cancelled earlier.",
        }

    if order.order_status == "COLLECTED" or (qr_tok and qr_tok.status == "COLLECTED"):
        explanation = (
            f"Refund request denied automated approval for {order.order_code} "
            f"({order.student_name}, ₹{order.total_amount:.2f}) because QR token was already collected. "
            f"Reason given: '{reason}'. Escalated for human manager verification."
        )
        db.add(
            SecurityEvent(
                organisation_id=order.organisation_id,
                order_id=order_id,
                token=qr_tok.token if qr_tok else None,
                event_type="COLLECTED_ORDER_REFUND_ESCALATION",
                risk_level="HIGH",
                ai_explanation=explanation,
                requires_human_review=True,
            )
        )
        db.flush()
        return {
            "order_id": order_id,
            "decision": "ESCALATED_FOR_HUMAN_REVIEW",
            "refund_approved": False,
            "requires_human_review": True,
            "message": "Order already collected. Automated refund blocked; escalated to Canteen Manager.",
            "explanation": explanation,
        }

    prior_cancels = db.execute(
        select(func.count(Order.id)).where(
            Order.organisation_id == order.organisation_id,
            Order.student_name == order.student_name,
            Order.order_status == "CANCELLED",
            Order.is_sample.is_(False),
        )
    ).scalar_one()

    if prior_cancels >= 2:
        explanation = (
            f"Unusual cancellation pattern detected for {order.student_name} "
            f"({prior_cancels + 1} cancellations). Order {order.order_code} (₹{order.total_amount:.2f}) "
            "held for human manager approval before simulated refund."
        )
        db.add(
            SecurityEvent(
                organisation_id=order.organisation_id,
                order_id=order_id,
                token=qr_tok.token if qr_tok else None,
                event_type="REPEATED_REFUND_PATTERN",
                risk_level="MEDIUM",
                ai_explanation=explanation,
                requires_human_review=True,
            )
        )
        db.flush()
        return {
            "order_id": order_id,
            "decision": "ESCALATED_FOR_HUMAN_REVIEW",
            "refund_approved": False,
            "requires_human_review": True,
            "message": "Repeated cancellations detected. Simulated refund held for manager approval.",
            "explanation": explanation,
        }

    order.order_status = "CANCELLED"
    order.payment_status = "REFUNDED_SIMULATED"
    if qr_tok:
        qr_tok.status = "CANCELLED"

    items = db.execute(
        select(OrderItem).where(OrderItem.order_id == order_id)
    ).scalars().all()
    for it in items:
        menu_item = db.execute(
            select(MenuItem).where(MenuItem.id == it.menu_item_id)
        ).scalar_one_or_none()
        if menu_item:
            menu_item.stock_qty += it.quantity
            db.add(
                InventoryMovement(
                    organisation_id=order.organisation_id,
                    menu_item_id=menu_item.id,
                    outlet_id=menu_item.outlet_id,
                    delta_qty=it.quantity,
                    new_stock_qty=menu_item.stock_qty,
                    reason=f"ORDER_CANCELLED:{order.order_code}",
                    actor_user_id=actor_user_id,
                )
            )

    record_audit_log(
        db,
        organisation_id=order.organisation_id,
        action="ORDER_CANCELLED",
        resource_type="order",
        resource_id=order.id,
        actor_user_id=actor_user_id,
        details={"order_code": order.order_code, "reason": reason},
    )
    db.flush()

    return {
        "order_id": order_id,
        "decision": "REFUND_APPROVED_SIMULATED",
        "refund_approved": True,
        "requires_human_review": False,
        "message": f"Order {order.order_code} cancelled. Simulated refund of ₹{order.total_amount:.2f} processed & QR invalidated.",
        "explanation": f"Uncollected order cancelled cleanly under deterministic policy. Reason: {reason}",
    }
