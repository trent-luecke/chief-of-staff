"""Per-meeting prep recipes for the Today tab.

Deterministic block gathering + one LLM synthesis call. Non-fatal throughout:
a failing block is dropped; a failing synthesis yields None. The legacy
processors/meeting_prep.py (emailed brief) is intentionally not reused.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic

from lib import identity, meetings as meetings_lib, tasks as tasks_lib
from processors.meeting_prep import _format_demos_line

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
    data_dir = ctx.config.get("data_dir", "data")
    state = meetings_lib.replay_local(data_dir)
    mtg = state.get(ctx.meeting_cfg.meeting_id)
    if not mtg:
        return None
    body = meetings_lib.last_session(mtg)
    if not body or not body.strip():
        return None
    return "## Last Session\n" + body.strip()


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


def gather_pipeline_sales(ctx: PrepContext, params: dict) -> Optional[str]:
    cache_path = ctx.config.get("pipeline", {}).get("cache_path", "data/pipeline_cache.json")
    # storage-relative key: drop a leading data/ if present
    key = cache_path[len("data/"):] if cache_path.startswith("data/") else cache_path
    cache = ctx.storage.read_json(key, default={})
    leads = cache.get("leads", [])
    if not leads:
        return None
    by_status: dict = {}
    for lead in leads:
        by_status.setdefault(lead.get("status") or "Unknown", []).append(lead)
    lines = [f"## Pipeline ({len(leads)} total)"]
    for status, group in sorted(by_status.items()):
        stale = sum(1 for l in group if l.get("stale"))
        tail = f" [{stale} stale]" if stale else ""
        lines.append(f"- {status} ({len(group)}){tail}")
    lines.append(_format_demos_line())
    return "\n".join(lines)


_BLOCKS = {
    "open_threads": gather_open_threads,
    "last_session": gather_last_session,
    "project_next_actions": gather_project_next_actions,
    "pipeline_sales": gather_pipeline_sales,
}

_SYSTEM = (
    "You are Trent Luecke's AI Chief of Staff preparing him for a recurring internal meeting. "
    "Using only the gathered context below, produce a short, skimmable prep in markdown bullets. "
    "Do not invent facts not present in the context. No preamble."
)


def _normalize_block(entry) -> tuple:
    if isinstance(entry, str):
        return entry, {}
    params = {k: v for k, v in entry.items() if k != "block"}
    return entry.get("block"), params


def gather_blocks(recipe: dict, ctx: PrepContext) -> str:
    chunks = []
    for entry in recipe.get("blocks", []):
        name, params = _normalize_block(entry)
        fn = _BLOCKS.get(name)
        if fn is None:
            log.warning("unknown prep block %r (meeting %s)", name, getattr(ctx.meeting_cfg, "name", "?"))
            continue
        try:
            out = fn(ctx, params)
        except Exception:
            log.exception("prep block %r failed (meeting %s)", name, getattr(ctx.meeting_cfg, "name", "?"))
            continue
        if out and out.strip():
            chunks.append(out.strip())
    return "\n\n".join(chunks)


def prep_hash(recipe: dict) -> str:
    canonical = json.dumps(recipe, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _synthesize(context: str, instruction: str, event_summary: str, config: dict, api_key: str) -> str:
    model = config.get("ai_model", "claude-sonnet-4-6")
    steer = f"\n\nExtra instruction for this meeting: {instruction}" if instruction else ""
    user = f"Meeting: {event_summary}{steer}\n\nGathered context:\n{context}"
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model, max_tokens=600, system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    try:
        from lib.llm_logger import log_usage
        log_usage("meeting_prep_recipe", resp.usage, model)
    except Exception:
        pass
    if not resp.content:
        raise ValueError("empty synthesis response")
    return resp.content[0].text.strip()


def build_prep(event, meeting_cfg, config: dict, storage, api_key: str) -> Optional[str]:
    recipe = getattr(meeting_cfg, "prep_recipe", None)
    if not recipe:
        return None
    ctx = PrepContext(event=event, meeting_cfg=meeting_cfg, config=config, storage=storage)
    try:
        context = gather_blocks(recipe, ctx)
        if not context.strip():
            return None
        return _synthesize(context, recipe.get("instruction", ""),
                           getattr(event, "summary", ""), config, api_key)
    except Exception:
        log.exception("build_prep failed (meeting %s)", getattr(meeting_cfg, "name", "?"))
        return None
