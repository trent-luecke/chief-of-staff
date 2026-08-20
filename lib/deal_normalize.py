"""Turn analyzed Avoma demo transcripts into email-keyed DealEvents."""
from __future__ import annotations

from datetime import datetime

from lib.deal_crosswalk import FREE_EMAIL_DOMAINS
from lib.deal_events import DealEvent, make_event_id
from lib.email_norm import normalize_email

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y")


def parse_money(raw: str | None) -> float | None:
    """'$1,200' -> 1200.0; blank/non-numeric -> None."""
    if raw is None:
        return None
    s = str(raw).strip().replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_close_date(raw: str | None) -> str | None:
    """Tolerant close-date parse to ISO 'YYYY-MM-DD'; unparseable -> None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None

_GENERIC_LOCALS = {"info", "sales", "office", "admin", "contact", "hello", "team", "support"}

# Automated / non-prospect senders that ride on meeting invites — never a deal.
_NOREPLY_MARKERS = ("no-reply", "noreply", "no_reply", "donotreply", "do-not-reply", "donot-reply")
_VENDOR_DOMAINS = {"zoom.us", "zoom.com", "calendar.google.com", "google.com", "calendly.com"}


def _domain(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else ""


def _is_automated(email: str) -> bool:
    """True for no-reply / meeting-platform addresses that are never prospects."""
    local, _, domain = email.partition("@")
    if any(m in local for m in _NOREPLY_MARKERS):
        return True
    return domain in _VENDOR_DOMAINS


def normalize_demo_events(transcripts: list) -> list[DealEvent]:
    events: list[DealEvent] = []
    for t in transcripts:
        if getattr(t, "call_type", "") != "demo" or not getattr(t, "os_interested", False):
            continue
        uuid = getattr(t, "uuid", "")
        prospects: list[str] = []
        for a in getattr(t, "attendees", []) or []:
            ne = normalize_email(a.get("email"))
            if ne and not _is_automated(ne) and ne not in prospects:
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
            elif all(_domain(e) in FREE_EMAIL_DOMAINS for e in prospects):
                reason = "free_email"
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


def normalize_sale_events(rows: list[dict]) -> list[DealEvent]:
    """Turn Sales Tracker rows into email-keyed `sale` DealEvents. Rows without
    a valid external email or a parseable close date are skipped."""
    events: list[DealEvent] = []
    for r in rows:
        raw_email = r.get("customer_email", "") or ""
        email = normalize_email(raw_email)
        if not email:
            continue
        close = parse_close_date(r.get("date"))
        if not close:
            continue
        total_raw = r.get("total_sale", "") or ""
        value = parse_money(total_raw)
        native_id = f"{close}|{email}|{total_raw}"
        events.append(DealEvent(
            event_id=make_event_id("sale", native_id, email),
            email=email,
            email_raw=raw_email,
            kind="sale",
            timestamp=close,
            account_name=r.get("customer_name", "") or "",
            rep=r.get("salesperson", "") or "",
            source=r.get("source", "") or "",
            payload={"deal_value": value},
        ))
    return events
