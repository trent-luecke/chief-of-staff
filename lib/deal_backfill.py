"""Transform a pipeline_cache.json snapshot into `seed` DealEvents.

One-shot Notion backfill: each cache lead becomes one seed event carrying its
imported stage/outcome + provenance. Pure and total; keyed on the Notion
page_id so re-runs are idempotent on the fold."""
from __future__ import annotations

from lib.deal_events import DealEvent, make_event_id
from lib.deal_status_map import map_notion_status
from lib.email_norm import normalize_email


def normalize_seed_events(leads: list[dict], import_ts: str) -> list[DealEvent]:
    events: list[DealEvent] = []
    for lead in leads:
        page_id = lead.get("page_id")
        if not page_id:
            continue  # no stable id -> can't key or dedup; skip (caller counts)
        email = normalize_email(lead.get("email"))
        key = email or f"notion:{page_id}"
        stage, outcome = map_notion_status(lead.get("status"))
        last_contacted = lead.get("last_contacted") or None
        events.append(DealEvent(
            event_id=make_event_id("seed", str(page_id), key),
            email=key,
            email_raw=lead.get("email") or "",
            kind="seed",
            timestamp=last_contacted or import_ts,
            account_name=lead.get("name") or "",
            rep="",
            source="notion-backfill",
            payload={
                "stage": stage,
                "outcome": outcome,
                "import_ts": import_ts,
                "estimated_value": lead.get("estimated_value"),
                "source": lead.get("source"),
                "priority": lead.get("priority"),
                "contact": lead.get("contact") or "",
                "page_id": page_id,
                "last_contacted": last_contacted,
            },
        ))
    return events
