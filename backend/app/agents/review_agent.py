"""Review & Feedback Agent: sentiment scoring, 5-category triage, recurring issue detection, and resolution tracking."""

from __future__ import annotations

import json
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Outlet, Review
from app.services.llm_client import generate_llm_text

CATEGORIES = ("Food Quality", "Hygiene", "Pricing", "Service", "Waiting Time")

CATEGORY_KEYWORDS = {
    "Waiting Time": ("wait", "waited", "slow", "delay", "late", "queue", "line", "minutes", "break", "long"),
    "Food Quality": ("taste", "cold", "stale", "fresh", "spicy", "salty", "burnt", "delicious", "tasty", "quality"),
    "Hygiene": ("clean", "dirty", "hygiene", "neat", "mess", "hair", "fly", "table", "counter"),
    "Pricing": ("price", "expensive", "cost", "overpriced", "cheap", "worth", "value", "rupees"),
    "Service": ("staff", "rude", "helpful", "polite", "service", "friendly", "behav"),
}


def classify_review_rule_based(rating: int, comment: str) -> dict:
    """Deterministic fallback classifier for sentiment and the 5 feedback categories."""
    text = comment.lower()
    if rating <= 2 or any(w in text for w in ("bad", "worst", "terrible", "slow", "waited", "cold", "dirty", "jammed")):
        sentiment = "NEGATIVE"
    elif rating >= 4 and not any(w in text for w in ("but", "slow", "issue", "late")):
        sentiment = "POSITIVE"
    else:
        sentiment = "NEUTRAL"

    best_cat = "Service"
    best_hits = 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        hits = sum(1 for k in kws if k in text)
        if hits > best_hits:
            best_hits = hits
            best_cat = cat

    return {"sentiment": sentiment, "category": best_cat}


def analyze_review_with_ai(rating: int, comment: str) -> dict:
    """Use configured LLM when available; fall back cleanly to deterministic classifier."""
    fallback = classify_review_rule_based(rating, comment)
    raw = generate_llm_text(
        (
            "Classify the campus canteen review strictly as JSON with keys 'sentiment' "
            "(one of POSITIVE, NEUTRAL, NEGATIVE) and 'category' "
            "(one of: Food Quality, Hygiene, Pricing, Service, Waiting Time). Output JSON only."
        ),
        f"Rating: {rating}/5. Review: {comment}",
        max_tokens=80,
    )
    if not raw:
        return fallback
    try:
        cleaned = raw.strip().strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        parsed = json.loads(cleaned)
        sent = parsed.get("sentiment", fallback["sentiment"]).upper()
        cat = parsed.get("category", fallback["category"])
        if sent not in ("POSITIVE", "NEUTRAL", "NEGATIVE"):
            sent = fallback["sentiment"]
        if cat not in CATEGORIES:
            cat = fallback["category"]
        return {"sentiment": sent, "category": cat}
    except Exception:
        return fallback


def get_feedback_intelligence(
    db: Session,
    outlet_id: int | None = None,
    organisation_id: int | None = None,
) -> dict:
    """Aggregate sentiment distribution, 5-category counts, and complaints within tenant scope."""
    stmt = (
        select(Review, Outlet.name.label("outlet_name"))
        .join(Outlet, Outlet.id == Review.outlet_id)
        .order_by(Review.is_sample.asc(), Review.id.desc())
    )
    if organisation_id is not None:
        stmt = stmt.where(Review.organisation_id == organisation_id)
    if outlet_id is not None:
        stmt = stmt.where(Review.outlet_id == outlet_id)

    rows = db.execute(stmt).all()
    reviews = [
        {
            "id": r.id,
            "outlet_id": r.outlet_id,
            "outlet_name": oname,
            "order_id": r.order_id,
            "student_name": r.student_name,
            "rating": r.rating,
            "comment": r.comment,
            "sentiment": r.sentiment,
            "category": r.category,
            "is_resolved": int(bool(r.is_resolved)),
            "is_sample": int(bool(r.is_sample)),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r, oname in rows
    ]

    sentiment_counts = {"POSITIVE": 0, "NEUTRAL": 0, "NEGATIVE": 0}
    category_counts = {c: 0 for c in CATEGORIES}
    outlet_cat_issues: dict[tuple[int, str, str], int] = {}

    for rev in reviews:
        sentiment_counts[rev["sentiment"]] = sentiment_counts.get(rev["sentiment"], 0) + 1
        cat = rev["category"] if rev["category"] in category_counts else "Service"
        category_counts[cat] += 1
        if rev["sentiment"] in ("NEGATIVE", "NEUTRAL") and rev["is_resolved"] == 0:
            key = (rev["outlet_id"], rev["outlet_name"], cat)
            outlet_cat_issues[key] = outlet_cat_issues.get(key, 0) + 1

    recurring = [
        {
            "outlet_id": oid,
            "outlet_name": oname,
            "category": cat,
            "open_complaints": cnt,
        }
        for (oid, oname, cat), cnt in outlet_cat_issues.items()
        if cnt >= 2
    ]

    avg_rating = round(sum(r["rating"] for r in reviews) / len(reviews), 2) if reviews else 0.0
    resolved_cnt = sum(1 for r in reviews if r["is_resolved"] == 1)

    return {
        "agent": "Review & Feedback Agent",
        "outlet_scope_id": outlet_id,
        "total_reviews": len(reviews),
        "live_reviews": sum(1 for r in reviews if r["is_sample"] == 0),
        "sample_reviews": sum(1 for r in reviews if r["is_sample"] == 1),
        "avg_rating": avg_rating,
        "resolved_count": resolved_cnt,
        "sentiment_breakdown": sentiment_counts,
        "category_breakdown": category_counts,
        "recurring_complaints": recurring,
        "recent_reviews": reviews[:20],
        "reviews": reviews[:25],
    }
