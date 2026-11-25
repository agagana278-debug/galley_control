"""Ordering Agent: fuzzy/spelling-tolerant menu lookup, availability, pricing, and smart substitutes."""

from __future__ import annotations

import difflib
import re
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MenuItem, Outlet

SYNONYMS = {
    "chai": "tea ginger chai",
    "tea": "ginger chai",
    "coffe": "cold coffee",
    "cofee": "cold coffee",
    "panir": "paneer roll",
    "noodels": "veg hakka noodles",
    "noodle": "veg hakka noodles",
    "friedrice": "veg fried rice",
    "dhosa": "masala dosa",
    "sandwitch": "grilled cheese sandwich",
    "sandwich": "grilled cheese sandwich",
    "maggie": "maggi masala bowl",
    "magi": "maggi masala bowl",
    "soda": "fresh lime soda",
    "wrap": "chicken tikka wrap",
}


def _expand_query(query_text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", (query_text or "").lower()))
    expanded = set(tokens)
    for t in tokens:
        if t in SYNONYMS:
            expanded.update(SYNONYMS[t].split())
    return expanded


def _fuzzy_score(tokens: set[str], target_text: str) -> float:
    if not tokens:
        return 0.0
    words = re.findall(r"[a-z0-9]+", target_text.lower())
    best = 0.0
    for qt in tokens:
        if len(qt) <= 2:
            continue
        if qt in target_text.lower():
            best += 1.0
            continue
        for w in words:
            ratio = difflib.SequenceMatcher(None, qt, w).ratio()
            if ratio >= 0.72:
                best += ratio
                break
    return best


def query_menu_options(
    db: Session,
    query_text: str,
    outlet_id: int | None = None,
    organisation_id: int | None = None,
) -> dict:
    """Search live database menu items with dietary, budget, tenant, and typo-tolerant matching."""
    q = (query_text or "").lower()
    tokens = _expand_query(q)
    veg_only = any(w in q for w in ("veg", "vegetarian", "paneer", "dosa", "idli"))
    max_price = None
    budget_match = re.search(r"(?:under|below|max|less than|within|rs\.?|₹)\s*(\d+)", q)
    if budget_match:
        max_price = float(budget_match.group(1))

    stmt = (
        select(MenuItem, Outlet.name.label("outlet_name"), Outlet.status.label("outlet_status"))
        .join(Outlet, Outlet.id == MenuItem.outlet_id)
        .order_by(MenuItem.prep_minutes.asc(), MenuItem.price.asc())
    )
    if organisation_id is not None:
        stmt = stmt.where(
            MenuItem.organisation_id == organisation_id,
            Outlet.organisation_id == organisation_id,
        )
    if outlet_id is not None:
        stmt = stmt.where(MenuItem.outlet_id == outlet_id)
    if veg_only and "non-veg" not in q and "chicken" not in q and "egg" not in q:
        stmt = stmt.where(MenuItem.is_veg.is_(True))
    if max_price is not None:
        stmt = stmt.where(MenuItem.price <= max_price)

    rows = db.execute(stmt).all()

    # Preload substitutes by id
    sub_ids = {mi.substitute_item_id for mi, _, _ in rows if mi.substitute_item_id}
    subs_by_id: dict[int, MenuItem] = {}
    if sub_ids:
        for s in db.execute(select(MenuItem).where(MenuItem.id.in_(sub_ids))).scalars().all():
            subs_by_id[s.id] = s

    records = []
    for mi, outlet_name, outlet_status in rows:
        sub = subs_by_id.get(mi.substitute_item_id) if mi.substitute_item_id else None
        score = _fuzzy_score(tokens, f"{mi.name} {mi.category} {outlet_name}")
        records.append(
            {
                "id": mi.id,
                "outlet_id": mi.outlet_id,
                "outlet_name": outlet_name,
                "outlet_status": outlet_status,
                "name": mi.name,
                "category": mi.category,
                "price": mi.price,
                "stock_qty": mi.stock_qty,
                "prep_minutes": mi.prep_minutes,
                "is_veg": bool(mi.is_veg),
                "is_available": bool(mi.is_available),
                "substitute_item_id": mi.substitute_item_id,
                "substitute_name": sub.name if sub else None,
                "substitute_price": sub.price if sub else None,
                "_match_score": score,
            }
        )

    # Sort primarily by fuzzy match relevance when a specific dish keyword exists, then prep/price
    if any(r["_match_score"] > 0.7 for r in records):
        records.sort(key=lambda r: (-r["_match_score"], r["prep_minutes"], r["price"]))

    for r in records:
        r.pop("_match_score", None)

    in_stock = [
        r
        for r in records
        if r["stock_qty"] > 0 and r["is_available"] and r["outlet_status"] != "CLOSED"
    ]
    out_of_stock = [r for r in records if r["stock_qty"] <= 0 or not r["is_available"]]

    return {
        "agent": "Ordering Agent",
        "filters": {"veg_only": veg_only, "max_price": max_price, "outlet_id": outlet_id},
        "available_items": in_stock[:8],
        "unavailable_with_substitutes": [
            {
                "item": item["name"],
                "outlet_name": item["outlet_name"],
                "substitute": item["substitute_name"],
                "substitute_price": item["substitute_price"],
            }
            for item in out_of_stock
            if item["substitute_name"]
        ],
    }
