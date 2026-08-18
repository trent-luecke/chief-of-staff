"""Turn analyzed Avoma demo transcripts into email-keyed DealEvents."""
from __future__ import annotations

from lib.deal_events import DealEvent, make_event_id
from lib.email_norm import normalize_email

_GENERIC_LOCALS = {"info", "sales", "office", "admin", "contact", "hello", "team", "support"}


def _domain(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else ""


def normalize_demo_events(transcripts: list) -> list[DealEvent]:
    events: list[DealEvent] = []
    for t in transcripts:
        if getattr(t, "call_type", "") != "demo" or not getattr(t, "os_interested", False):
            continue
        uuid = getattr(t, "uuid", "")
        prospects: list[str] = []
        for a in getattr(t, "attendees", []) or []:
            ne = normalize_email(a.get("email"))
            if ne and ne not in prospects:
                prospects.append(ne)

        reason = None
        if not prospects:
            reason = "no_email"
            primary = f"unresolved:{uuid}"
        else:
            if len({_domain(e) for e in prospects}) > 1:
                reason = "multi_domain"
            elif all(e.split("@", 1)[0] in _GENERIC_LOCALS for e in prospects):
                reason = "generic_inbox"
            primary = prospects[0]

        events.append(DealEvent(
            event_id=make_event_id("demo", uuid, primary),
            email=primary,
            email_raw="",
            kind="demo",
            timestamp=getattr(t, "start_at", ""),
            account_name="",
            rep=getattr(t, "rep_name", "") or "",
            source="avoma",
            payload={
                "avoma_uuid": uuid,
                "contact_emails": prospects,
                "ambiguous_reason": reason,
                "title": getattr(t, "title", ""),
            },
        ))
    return events
