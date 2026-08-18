"""Fold DealEvents into current email-keyed deals."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from lib.deal_crosswalk import domain_to_name


@dataclass
class Deal:
    email: str
    account_name: str = ""
    rep: str = ""
    demo_date: str | None = None
    trial_start_date: str | None = None
    cycle_start: str | None = None
    close_date: str | None = None
    outcome: str = "open"
    stage: str = ""
    contact_emails: list = field(default_factory=list)
    source: str = ""
    deal_value: float | None = None
    lost_reason: str = ""
    provenance: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)
    last_event_at: str | None = None


def _days_since(iso: str, today: str) -> int:
    try:
        return (date.fromisoformat(today[:10]) - date.fromisoformat(iso[:10])).days
    except (ValueError, TypeError):
        return 0


def build_deals(events: list, crosswalk: dict, today: str, stale_days: int = 45) -> dict:
    by_email: dict[str, list] = {}
    for e in events:
        by_email.setdefault(e.email, []).append(e)

    deals: dict[str, Deal] = {}
    for email, evs in by_email.items():
        d = Deal(email=email)
        contacts: list[str] = []
        ambiguous_reason = None
        for e in evs:
            if e.kind == "demo":
                ts = e.timestamp or None
                if ts and (d.demo_date is None or ts < d.demo_date):
                    d.demo_date = ts
                for c in e.payload.get("contact_emails", []) or []:
                    if c not in contacts:
                        contacts.append(c)
                if e.rep:
                    d.rep = e.rep
                if e.payload.get("ambiguous_reason"):
                    ambiguous_reason = e.payload["ambiguous_reason"]
            if e.timestamp and (d.last_event_at is None or e.timestamp > d.last_event_at):
                d.last_event_at = e.timestamp

        d.contact_emails = contacts
        d.cycle_start = d.demo_date  # min(trial, demo) == demo in Phase 1a
        d.outcome = "open"
        d.stage = "demoed"
        d.account_name = "" if email.startswith("unresolved:") else (crosswalk.get(email) or domain_to_name(email))

        if ambiguous_reason:
            d.review = {"needs": True, "kind": "ambiguous", "reason": ambiguous_reason,
                        "proposed": {"email": email, "account_name": d.account_name, "rep": d.rep}}
        elif d.cycle_start and _days_since(d.cycle_start, today) >= stale_days:
            d.review = {"needs": True, "kind": "stale_check", "reason": "aged_%dd" % stale_days}
        else:
            d.review = {"needs": False}

        deals[email] = d
    return deals
