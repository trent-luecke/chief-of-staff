"""Filter analyzed Avoma transcripts down to countable OS demos and map to
engine-ingest records."""

from __future__ import annotations

_INTERNAL_DOMAIN = "@teambuildr.com"


def _split_participants(participants: list[str]) -> tuple[list[str], list[str]]:
    names = [p for p in (participants or []) if p and "@" not in p]
    emails = [p for p in (participants or []) if p and "@" in p]
    return names, emails


def _split_attendees(attendees: list[dict]) -> tuple[list[str], list[str]]:
    """Prospect names/emails from structured attendees, dropping internal reps.

    An attendee is internal (a rep) when their email is on the TeamBuildr domain;
    such rows are excluded from both lists so the rep's address never becomes a
    deal key. Attendees without an email can't be classified — kept as names.
    """
    names, emails = [], []
    for a in attendees or []:
        email = (a.get("email") or "").strip()
        name = (a.get("name") or "").strip()
        if email.lower().endswith(_INTERNAL_DOMAIN):
            continue
        if name:
            names.append(name)
        if email:
            emails.append(email)
    return names, emails


def detect_demos(transcripts: list, counted_reps: set[str]) -> list[dict]:
    """Return engine demo records for demo+os_interested calls.

    A transcript qualifies when call_type=='demo' AND os_interested is true.
    rep_name in counted_reps is kept as-is; an unresolved rep is bucketed
    "Unassigned" (still counted). Other reps' demos (e.g. Quinn, if ever
    resolved) are dropped.
    """
    records = []
    for t in transcripts:
        if t.call_type != "demo" or not t.os_interested:
            continue
        rep = getattr(t, "rep_name", "") or ""
        if rep and rep not in counted_reps:
            continue  # a resolved non-counted rep (e.g. Quinn) — drop
        attendees = getattr(t, "attendees", None)
        if attendees:
            names, emails = _split_attendees(attendees)
        else:
            names, emails = _split_participants(getattr(t, "participants", []))
        records.append({
            "avoma_uuid": t.uuid,
            "rep": rep if rep in counted_reps else "Unassigned",
            "start_at": t.start_at,
            "title": t.title,
            "invitee_names": names,
            "invitee_emails": emails,
        })
    return records
