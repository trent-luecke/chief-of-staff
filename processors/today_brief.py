"""Generate the pre-computed Today brief (brief_today.json).

Deterministic (no LLM in Plan 2): assembles today's meetings and the <=3
tasks needing attention, and provisions registry stubs for external attendees
(Plan 1). Written to the git-anchored registry via registry_storage.
"""
from __future__ import annotations

from lib import identity, tasks as tasks_lib
from processors.attendee_provisioner import provision_from_events

_DEFAULT_INTERNAL_DOMAINS = ["teambuildr.com"]
_NEEDS_CAP = 3
_RANK = {"overdue": 0, "due": 1, "horizon": 2}


def _reason(task: dict, today: str) -> str:
    due = task.get("due_date")
    if due and due < today:
        return "overdue"
    if due and due == today:
        return "due"
    return "horizon"


def rank_needs(task_list: list, today: str, cap: int = _NEEDS_CAP) -> list:
    items = [
        {
            "id": t["id"],
            "title": t.get("title", ""),
            "reason": _reason(t, today),
            "due_date": t.get("due_date"),
            "project_id": t.get("project_id"),
        }
        for t in task_list
    ]
    items.sort(key=lambda x: (_RANK[x["reason"]], x["due_date"] or "9999-12-31"))
    return items[:cap]


def _meeting_dict(ev, internal_domains: list) -> dict:
    has_external = any(
        not identity.is_internal(email, internal_domains) for email in ev.attendees
    )
    return {
        "id": ev.id,
        "title": ev.summary,
        "start": ev.start.isoformat() if ev.start else None,
        "end": ev.end.isoformat() if ev.end else None,
        "kind": "external" if has_external else "internal",
        "attendees": [
            {"email": d.get("email", ""), "name": d.get("name", "")}
            for d in (ev.attendee_details or [])
        ],
        "prep": None,
    }


def build_today_brief(events, needs_items, internal_domains, today: str, generated_at: str) -> dict:
    meetings = [_meeting_dict(ev, internal_domains) for ev in events if not getattr(ev, "declined", False)]
    return {
        "date": today,
        "generated_at": generated_at,
        "meetings": meetings,
        "needs_today": needs_items,
        "what_moved": [],
    }


def generate_and_write(config: dict, events, storage, today: str, generated_at: str) -> dict:
    internal_domains = config.get("demo_scan", {}).get("internal_domains", _DEFAULT_INTERNAL_DOMAINS)
    # Plan 1: provision stubs for unresolved external attendees (writes people_registry.json)
    provision_from_events(events, storage, config, today)
    needs = rank_needs(tasks_lib.get_due_or_surfaced(storage, today=today), today)
    brief = build_today_brief(events, needs, internal_domains, today, generated_at)
    storage.write_json("brief_today.json", brief)
    return brief
