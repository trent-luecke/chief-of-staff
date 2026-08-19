"""Generate the pre-computed Today brief (brief_today.json).

Assembles today's meetings and the <=3 tasks needing attention, and provisions
registry stubs for external attendees (Plan 1). Block gathering and task/meeting
assembly are deterministic; internal-meeting prep (Plan 4) adds one LLM synthesis
call per meeting that has a recipe. Written to the git-anchored registry.
"""
from __future__ import annotations

from lib import identity, tasks as tasks_lib
from lib.deal_crosswalk import load_crosswalk
from lib.deal_events import load_events
from lib.deal_fold import build_deals, build_deals_to_review
from processors.attendee_provisioner import provision_from_events
from processors import meeting_prep_recipe
from processors.meeting_memory import load_meeting_index, find_meeting_for_event

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
    ranked = []
    for t in task_list:
        reason = _reason(t, today)
        sort_date = t.get("due_date") if reason in ("overdue", "due") else t.get("horizon")
        item = {
            "id": t["id"],
            "title": t.get("title", ""),
            "reason": reason,
            "due_date": t.get("due_date"),
            "project_id": t.get("project_id"),
        }
        ranked.append((_RANK[reason], sort_date or "9999-12-31", item))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [item for _, _, item in ranked[:cap]]


def _meeting_dict(ev, internal_domains: list, prep: str | None = None, prep_hash: str | None = None) -> dict:
    has_external = any(
        not identity.is_internal(email, internal_domains) for email in ev.attendees
    )
    d = {
        "id": ev.id,
        "title": ev.summary,
        "start": ev.start.isoformat() if ev.start else None,
        "end": ev.end.isoformat() if ev.end else None,
        "kind": "external" if has_external else "internal",
        "attendees": [
            {"email": a.get("email", ""), "name": a.get("name", "")}
            for a in (ev.attendee_details or [])
        ],
        "prep": prep,
    }
    if prep_hash is not None:
        d["prep_hash"] = prep_hash
    return d


def _prep_for_event(ev, internal_domains, meeting_configs, config, storage, api_key, prior_by_id):
    has_external = any(not identity.is_internal(e, internal_domains) for e in ev.attendees)
    if has_external:
        return None, None
    cfg = find_meeting_for_event(ev, meeting_configs)
    if not cfg or not getattr(cfg, "prep_recipe", None):
        return None, None
    phash = meeting_prep_recipe.prep_hash(cfg.prep_recipe)
    cached = prior_by_id.get(ev.id)
    if cached and cached.get("prep_hash") == phash and cached.get("prep") is not None:
        return cached["prep"], phash
    prep = meeting_prep_recipe.build_prep(ev, cfg, config, storage, api_key)
    return prep, phash


def _deal_review_summary(storage, today: str, stale_days: int = 45) -> dict:
    if storage is None:
        return {"counts": {"identity": 0, "stale": 0, "total": 0}}
    deals = build_deals(load_events(storage), load_crosswalk(storage), today, stale_days=stale_days)
    review = build_deals_to_review(deals)
    return {"counts": review["counts"]}  # email is read-only: counts + "open Today" link


def build_today_brief(events, needs_items, internal_domains, today: str, generated_at: str,
                      config=None, storage=None, api_key="") -> dict:
    config = config or {}
    active = [ev for ev in events if not getattr(ev, "declined", False)]

    meeting_configs = load_meeting_index(config.get("meeting_index_file") or "data/meeting_index.json")
    prior = storage.read_json("brief_today.json", default={}) if storage is not None else {}
    prior_by_id = {m.get("id"): m for m in prior.get("meetings", [])} if prior.get("date") == today else {}

    meetings = []
    for ev in active:
        prep, phash = _prep_for_event(ev, internal_domains, meeting_configs, config, storage,
                                      api_key, prior_by_id)
        meetings.append(_meeting_dict(ev, internal_domains, prep=prep, prep_hash=phash))

    return {
        "date": today,
        "generated_at": generated_at,
        "meetings": meetings,
        "needs_today": needs_items,
        "deals_to_review": _deal_review_summary(storage, today),
        "what_moved": [],
    }


def generate_and_write(config: dict, events, storage, today: str, generated_at: str, api_key: str = "") -> dict:
    internal_domains = config.get("demo_scan", {}).get("internal_domains", _DEFAULT_INTERNAL_DOMAINS)
    # Filter declined meetings once; use for both provisioning and assembly
    active_events = [ev for ev in events if not getattr(ev, "declined", False)]
    # Plan 1: provision stubs for unresolved external attendees (writes people_registry.json)
    provision_from_events(active_events, storage, config, today)
    needs = rank_needs(tasks_lib.get_due_or_surfaced(storage, today=today), today)
    brief = build_today_brief(active_events, needs, internal_domains, today, generated_at,
                              config, storage, api_key)
    storage.write_json("brief_today.json", brief)
    return brief
