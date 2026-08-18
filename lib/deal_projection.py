"""Project derived deals into today's pipeline_cache.json shape (the seam)."""
from __future__ import annotations


def deals_to_pipeline_cache(deals: dict, fetched_at: str) -> dict:
    leads = []
    for email, d in deals.items():
        review = d.review or {}
        leads.append({
            "page_id": f"deal:{email}",
            "name": d.account_name,
            "contact": d.contact_emails[0] if d.contact_emails else "",
            "email": "" if email.startswith("unresolved:") else email,
            "status": d.stage,
            "priority": None,
            "last_contacted": d.last_event_at,
            "days_since_contact": None,
            "estimated_value": d.deal_value,
            "source": d.source,
            "stale": bool(review.get("needs") and review.get("kind") == "stale_check"),
        })
    return {"fetched_at": fetched_at, "leads": leads}
