"""Per-meeting prep recipes for the Today tab.

Deterministic block gathering + one LLM synthesis call. Non-fatal throughout:
a failing block is dropped; a failing synthesis yields None. The legacy
processors/meeting_prep.py (emailed brief) is intentionally not reused.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from lib import identity, meetings as meetings_lib, tasks as tasks_lib
from processors.meeting_memory import load_last_session_summary

log = logging.getLogger(__name__)


@dataclass
class PrepContext:
    event: object          # collectors.calendar.CalendarEvent (duck-typed in tests)
    meeting_cfg: object    # processors.meeting_memory.MeetingConfig
    config: dict
    storage: object


def gather_open_threads(ctx: PrepContext, params: dict) -> Optional[str]:
    data_dir = ctx.config.get("data_dir", "data")
    state = meetings_lib.replay_local(data_dir)
    mtg = state.get(ctx.meeting_cfg.meeting_id)
    if not mtg:
        return None
    threads = meetings_lib.open_threads(mtg)
    if not threads:
        return None
    lines = ["## Open Threads"]
    for t in threads:
        owner = f" (→ {t['person_id']})" if t.get("person_id") else ""
        lines.append(f"- {t.get('text', '')}{owner}")
    return "\n".join(lines)


def gather_last_session(ctx: PrepContext, params: dict) -> Optional[str]:
    key = ctx.meeting_cfg.memory_file
    if key.startswith("data/"):
        key = key[len("data/"):]
    summary = load_last_session_summary(ctx.storage, key)
    if not summary or not summary.strip():
        return None
    return "## Last Session\n" + summary.strip()


_FAR_FUTURE = "9999-12-31"


def _task_sort_key(task: dict) -> str:
    return task.get("due_date") or task.get("horizon") or _FAR_FUTURE


def _select_project_tasks(open_tasks: list, project_id: str, expand_threshold: int, max_per_project: int) -> list:
    proj_tasks = [t for t in open_tasks if t.get("project_id") == project_id]
    if len(proj_tasks) <= expand_threshold:
        return sorted(proj_tasks, key=_task_sort_key)
    return sorted(proj_tasks, key=_task_sort_key)[:max_per_project]


def gather_project_next_actions(ctx: PrepContext, params: dict) -> Optional[str]:
    expand_threshold = params.get("expand_threshold", 5)
    max_per_project = params.get("max_per_project", 3)
    internal_domains = ctx.config.get("demo_scan", {}).get("internal_domains", ["teambuildr.com"])

    people = identity.load_people(ctx.storage)
    email_index, alias_list = identity.build_lookup(people)
    attendee_pids = set()
    for d in (getattr(ctx.event, "attendee_details", None) or []):
        email = d.get("email", "")
        if not identity.is_internal(email, internal_domains):
            continue
        pid = identity.resolve(d.get("name", ""), email, email_index, alias_list)
        if pid:
            attendee_pids.add(pid)
    if not attendee_pids:
        return None

    projects = ctx.storage.read_json("projects_registry.json", default={}).get("projects", [])
    selected = [
        p for p in projects
        if p.get("status") == "active"
        and any(m.get("id") in attendee_pids for m in p.get("members", []))
    ]
    if not selected:
        return None

    open_tasks = tasks_lib.get_open_tasks(ctx.storage)

    rendered = []
    for p in selected:
        proj_tasks = _select_project_tasks(open_tasks, p["id"], expand_threshold, max_per_project)
        if not proj_tasks:
            continue
        soonest = min((_task_sort_key(t) for t in proj_tasks), default=_FAR_FUTURE)
        rendered.append((soonest, p, proj_tasks))
    if not rendered:
        return None

    rendered.sort(key=lambda r: r[0])
    lines = ["## Project Next-Actions"]
    for _, p, proj_tasks in rendered:
        lines.append(f"### {p.get('canonical_name', p['id'])}")
        for t in proj_tasks:
            when = t.get("due_date") or t.get("horizon")
            suffix = f" (due {when})" if when else ""
            lines.append(f"- {t.get('title', '')}{suffix}")
    return "\n".join(lines)
