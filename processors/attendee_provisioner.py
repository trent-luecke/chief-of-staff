"""Auto-provision registry stubs for external attendees of today's small meetings.

For each external attendee on today's calendar who does not already resolve to a
registry person, create a lightweight stub so a home exists before the post-call
transcript is processed. Guards: skip internal attendees; skip events with >= 6
attendees. Writes the git-anchored registry via storage.write_json.
"""
from __future__ import annotations

from lib import identity

DEFAULT_INTERNAL_DOMAINS = ["teambuildr.com"]
MAX_ATTENDEES = 6  # events with this many or more are skipped


def classify_attendees(attendees, internal_domains) -> tuple:
    """Return (internal_emails, external_emails)."""
    internal, external = [], []
    for email in attendees:
        if identity.is_internal(email, internal_domains):
            internal.append(email)
        else:
            external.append(email)
    return internal, external


def _display_name(email: str, detail_by_email: dict) -> str:
    name = (detail_by_email.get(email) or "").strip()
    return name if name else identity.name_from_email(email)


def stubs_for_events(events, people, internal_domains, today: str, max_attendees: int = MAX_ATTENDEES) -> tuple:
    """Pure: return (new_stubs, updated_people). Does not touch storage."""
    people = list(people)
    email_index, _ = identity.build_lookup(people)
    existing_ids = {p["id"] for p in people}
    new_stubs: list = []
    created_emails: set = set()

    for ev in events:
        attendees = getattr(ev, "attendees", []) or []
        if len(attendees) >= max_attendees:
            continue
        detail_by_email = {
            d["email"]: d.get("name", "") for d in getattr(ev, "attendee_details", []) or []
        }
        _, external = classify_attendees(attendees, internal_domains)
        for email in external:
            key = email.strip().lower()
            if identity.find_by_email(email, email_index) is not None:
                continue
            if key in created_emails:
                continue
            name = _display_name(email, detail_by_email)
            pid = identity.unique_id(identity.slugify(name) or key, existing_ids)
            stub = {
                "id": pid,
                "canonical_name": name,
                "aliases": [email],
                "email": email,
                "type": "unknown",
                "pipeline_record": None,
                "people_file": None,
                "created": today,
                "last_seen": today,
                "provenance": f"auto:calendar {today} meeting:{ev.summary}",
            }
            new_stubs.append(stub)
            people.append(stub)
            existing_ids.add(pid)
            email_index[key] = pid
            created_emails.add(key)

    return new_stubs, people


def provision_from_events(events, storage, config: dict, today: str) -> list:
    """Load registry, create stubs for unresolved external attendees, write back.

    Returns the list of newly created stub records (may be empty).
    """
    internal_domains = config.get("demo_scan", {}).get("internal_domains", DEFAULT_INTERNAL_DOMAINS)
    data = storage.read_json(identity.REGISTRY_KEY, default={"version": 1, "people": []})
    people = data.get("people", [])
    new_stubs, updated = stubs_for_events(events, people, internal_domains, today)
    if new_stubs:
        data["people"] = updated
        data.setdefault("version", 1)
        storage.write_json(identity.REGISTRY_KEY, data)
    return new_stubs
