"""Support Agent: policy guidance, complaint triage, and structured fallback food assistance."""

from __future__ import annotations

from app.agents.review_agent import classify_review_rule_based


def handle_support_query(
    message: str,
    ordering_ctx: dict,
    queue_ctx: dict,
    user_role: str = "student",
    orders_ctx: list[dict] | None = None,
    inventory_ctx: dict | None = None,
    feedback_ctx: dict | None = None,
    outlet_ctx: dict | None = None,
) -> dict:
    """Assemble grounded guidance from live database records when LLM is unavailable or as tool helper."""
    q = (message or "").lower()
    is_complaint = any(
        w in q for w in ("late", "slow", "cold", "refund", "bad", "dirty", "issue", "problem", "complain")
    )
    is_procedure = any(
        w in q for w in ("how to", "pickup", "qr", "cancel", "pay", "procedure", "work", "order status")
    )

    if any(w in q for w in ("my order", "order status", "where is my order", "ord-")) and orders_ctx is not None:
        if not orders_ctx:
            return {
                "agent": "Support Agent",
                "intent": "ORDER_LOOKUP",
                "reply": "You do not have any recent live orders in your account yet. Add items from the menu to place an order and receive a single-use QR pass.",
            }
        latest = orders_ctx[0]
        return {
            "agent": "Support Agent",
            "intent": "ORDER_LOOKUP",
            "reply": (
                f"Your most recent order is {latest['order_code']} at {latest['outlet_name']}: "
                f"status is {latest['order_status']} (QR pass: {latest.get('qr_status', 'N/A')}), "
                f"total ₹{latest['total_amount']}, estimated wait ~{latest['estimated_wait_minutes']} minutes."
            ),
        }

    if user_role in ("outlet_manager", "admin") and any(
        w in q for w in ("stock", "inventory", "review", "feedback", "bottleneck", "analytics", "performance", "improve")
    ):
        bits = []
        if inventory_ctx:
            bits.append(
                f"Inventory snapshot: {inventory_ctx['out_of_stock_count']} out-of-stock "
                f"({', '.join(inventory_ctx['out_of_stock_items']) or 'none'}) and "
                f"{inventory_ctx['low_stock_count']} low-stock item(s)."
            )
        if feedback_ctx:
            bits.append(
                f"Feedback summary: {feedback_ctx['total_reviews']} review(s), average rating {feedback_ctx['avg_rating']}/5, "
                f"{len(feedback_ctx.get('recurring_complaints', []))} recurring issue cluster(s)."
            )
        if outlet_ctx and outlet_ctx.get("outlets"):
            top_o = outlet_ctx["outlets"][0]
            bits.append(
                f"Outlet check ({top_o['outlet_name']}): bottleneck='{top_o['bottleneck']}'. "
                f"Suggested action: {top_o['recommended_action']}"
            )
        if bits:
            return {
                "agent": "Outlet Performance + Inventory + Review Agents",
                "intent": "OPERATIONS_INSIGHT",
                "reply": " ".join(bits),
            }

    if is_complaint:
        triage = classify_review_rule_based(2, message)
        return {
            "agent": "Support Agent",
            "intent": "COMPLAINT_TRIAGE",
            "category": triage["category"],
            "reply": (
                f"Your concern matches category '{triage['category']}'. "
                "For uncollected PLACED/PREPARING orders, you can cancel directly in Live Order Tracking for an immediate simulated refund and stock restoration; "
                "for collected orders or quality/hygiene complaints, submit a review on that outlet so the Review & Outlet Performance Agents escalate it to the manager."
            ),
        }

    if is_procedure:
        return {
            "agent": "Support Agent",
            "intent": "PROCEDURE_HELP",
            "reply": (
                "Ordering & pickup flow: 1) Select one campus outlet and add available items to your cart; "
                "2) Choose a time slot and complete simulated checkout to generate your single-use QR pass; "
                "3) Present the QR pass at that outlet counter when ready—each QR works once and is invalidated immediately after collection."
            ),
        }

    items = ordering_ctx.get("available_items", [])
    subs = ordering_ctx.get("unavailable_with_substitutes", [])
    fastest = queue_ctx.get("recommended_fastest_outlet")

    parts = []
    if items:
        top_names = ", ".join(
            f"{i['name']} (₹{int(i['price'])}, ~{i['prep_minutes']}m at {i['outlet_name']})"
            for i in items[:3]
        )
        parts.append(f"Available menu matches right now: {top_names}.")
    else:
        parts.append("No in-stock items matched those exact filters right now.")
    if subs:
        s0 = subs[0]
        parts.append(
            f"Note: {s0['item']} is currently out of stock—recommended substitute is {s0['substitute']} (₹{int(s0['substitute_price'])})."
        )
    if fastest:
        parts.append(
            f"Fastest open outlet queue right now: {fastest['outlet_name']} (~{fastest['estimated_wait_minutes']}m wait, {fastest['congestion_level']} congestion)."
        )

    return {
        "agent": "Support Agent",
        "intent": "FOOD_ASSISTANCE",
        "reply": " ".join(parts),
    }
