# Plan 4 — Internal Meeting Prep Recipes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the `prep` field on internal meeting cards in the Today tab (`brief_today.json`) using per-meeting recipes that deterministically gather data blocks and shape them with one LLM call.

**Architecture:** A new module `processors/meeting_prep_recipe.py` implements a catalog of four block-gather functions (`open_threads`, `last_session`, `project_next_actions`, `pipeline_sales`) and a `build_prep()` orchestrator that gathers a recipe's blocks, runs a single Claude call to shape them, and returns markdown. `processors/today_brief._meeting_dict` calls it for internal meetings that resolve to a recipe. Gathering is deterministic and non-fatal; only shaping uses an LLM. The legacy `processors/meeting_prep.py` (emailed-brief path) is untouched.

**Tech Stack:** Python 3, `anthropic` SDK, pytest. Reuses `lib.meetings`, `lib.identity`, `lib.tasks`, `processors.meeting_memory`, `lib.llm_logger`.

## Global Constraints

- **Non-fatal:** any exception in a block-gather → that block is dropped (logged, not raised); any exception in the LLM call → `prep` is `None` and the meeting still renders. Never raise out of `build_prep`.
- **No fabricated sections:** a block that finds no data returns `None`/empty and is dropped — never an empty-headed or invented section.
- **Deterministic gathering:** block gather functions make no LLM calls. Only `build_prep`'s synthesis step calls Claude, exactly once per meeting.
- **Model:** `config.get("ai_model", "claude-sonnet-4-6")`, `max_tokens=600`.
- **Internal domains:** `config.get("demo_scan", {}).get("internal_domains", ["teambuildr.com"])`.
- **Data dir:** `config.get("data_dir", "data")`. **Meeting index:** `config.get("meeting_index_file", "data/meeting_index.json")`.
- **Task capping defaults:** `expand_threshold=5`, `max_per_project=3`.
- **Caching:** reuse prep from the prior `brief_today.json` when `(meeting id, today's date, prep_hash)` all match; `prep_hash` = first 12 hex chars of `sha256(json.dumps(recipe, sort_keys=True))`.
- Only **Luke 1:1** gets a recipe in this pass. Meetings with no `prep_recipe` keep `prep: null` unchanged.

---

## File Structure

- **Create** `processors/meeting_prep_recipe.py` — block catalog + `build_prep()` + `prep_hash()`.
- **Modify** `processors/meeting_memory.py` — add `prep_recipe: Optional[dict] = None` to `MeetingConfig`.
- **Modify** `processors/today_brief.py` — wire prep into `_meeting_dict`; thread `config`/`storage`/`api_key`/meeting-configs/prior-brief through `build_today_brief` and `generate_and_write`; update docstring.
- **Modify** `main.py` — pass `api_key` into `generate_and_write`.
- **Modify** `data/meeting_index.json` — add the Luke 1:1 `prep_recipe`.
- **Create** `tests/test_meeting_prep_recipe.py` — block + orchestrator unit tests.
- **Modify** `tests/test_meeting_memory.py` — recipe-parsing test.
- **Modify** `tests/test_today_brief.py` — wiring + caching tests.

---

## Task 1: Add `prep_recipe` to `MeetingConfig`

**Files:**
- Modify: `processors/meeting_memory.py:9-20`
- Test: `tests/test_meeting_memory.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MeetingConfig` now accepts an optional `prep_recipe: Optional[dict] = None` (so `MeetingConfig(**m)` in `load_meeting_index` no longer raises `TypeError` when a JSON entry contains `prep_recipe`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_meeting_memory.py`:

```python
def test_load_meeting_index_parses_prep_recipe(tmp_path):
    from processors.meeting_memory import load_meeting_index
    p = tmp_path / "meeting_index.json"
    p.write_text(json.dumps({"meetings": [{
        "calendar_pattern": "luke / trent",
        "memory_file": "data/meeting_memory/luke_1on1.md",
        "nudge_subject": "1:1 notes?",
        "nudge_minutes_after": 5,
        "name": "Luke 1:1",
        "prep_recipe": {"blocks": ["open_threads"], "instruction": "Keep it short."},
    }]}))
    configs = load_meeting_index(str(p))
    assert len(configs) == 1
    assert configs[0].prep_recipe == {"blocks": ["open_threads"], "instruction": "Keep it short."}


def test_load_meeting_index_recipe_defaults_none(tmp_path):
    from processors.meeting_memory import load_meeting_index
    p = tmp_path / "meeting_index.json"
    p.write_text(json.dumps({"meetings": [{
        "calendar_pattern": "dev sync",
        "memory_file": "data/meeting_memory/dev_triage.md",
        "nudge_subject": "notes?",
        "nudge_minutes_after": 5,
        "name": "Dev Sync",
    }]}))
    configs = load_meeting_index(str(p))
    assert configs[0].prep_recipe is None
```

Ensure `import json` is present at the top of the test file (add if missing).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_meeting_memory.py::test_load_meeting_index_parses_prep_recipe -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'prep_recipe'`.

- [ ] **Step 3: Add the field**

In `processors/meeting_memory.py`, modify the dataclass (currently lines 9-20):

```python
@dataclass
class MeetingConfig:
    calendar_pattern: str
    memory_file: str
    nudge_subject: str
    nudge_minutes_after: int
    name: str = ""
    people_ids: list = field(default_factory=list)
    prep_recipe: Optional[dict] = None

    @property
    def meeting_id(self) -> str:
        return self.memory_file.rsplit("/", 1)[-1].removesuffix(".md")
```

`Optional` is already imported at the top of the file (`from typing import Optional`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_meeting_memory.py -v`
Expected: PASS (both new tests + existing ones).

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_memory.py tests/test_meeting_memory.py
git commit -m "feat: MeetingConfig accepts optional prep_recipe"
```

---

## Task 2: Module scaffold + `open_threads` and `last_session` blocks

**Files:**
- Create: `processors/meeting_prep_recipe.py`
- Test: `tests/test_meeting_prep_recipe.py`

**Interfaces:**
- Consumes: `lib.meetings.replay_local(data_dir) -> dict`, `lib.meetings.open_threads(meeting) -> list`, `processors.meeting_memory.MeetingConfig`, `processors.meeting_memory.load_last_session_summary(storage, key) -> str`.
- Produces:
  - `PrepContext` dataclass with fields `event`, `meeting_cfg`, `config`, `storage`.
  - `gather_open_threads(ctx, params: dict) -> Optional[str]`
  - `gather_last_session(ctx, params: dict) -> Optional[str]`
  - Every block-gather has signature `(ctx: PrepContext, params: dict) -> Optional[str]` and returns a titled markdown chunk or `None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_meeting_prep_recipe.py`:

```python
import json
from dataclasses import dataclass
from types import SimpleNamespace

import processors.meeting_prep_recipe as mpr
from processors.meeting_memory import MeetingConfig


class FakeStorage:
    """Minimal storage: dict-backed read/read_json."""
    def __init__(self, files=None, json_files=None):
        self._files = files or {}
        self._json = json_files or {}

    def read(self, key, default=None):
        return self._files.get(key, default)

    def read_json(self, key, default=None):
        return self._json.get(key, default if default is not None else {})

    def write_json(self, key, value):
        self._json[key] = value


def _event(summary="Luke / Trent", attendees=None):
    details = attendees or []
    return SimpleNamespace(
        id="evt1",
        summary=summary,
        attendees=[d["email"] for d in details],
        attendee_details=details,
        declined=False,
    )


def _cfg(**over):
    base = dict(
        calendar_pattern="luke / trent",
        memory_file="data/meeting_memory/luke_1on1.md",
        nudge_subject="1:1?",
        nudge_minutes_after=5,
        name="Luke 1:1",
    )
    base.update(over)
    return MeetingConfig(**base)


def test_gather_open_threads_renders_open_only(monkeypatch):
    meeting_state = {"luke_1on1": {
        "id": "luke_1on1",
        "threads": [
            {"text": "Ship onboarding v2", "person_id": "luke-green", "closed": False},
            {"text": "Old resolved thing", "person_id": None, "closed": True},
        ],
        "sessions": [],
    }}
    monkeypatch.setattr(mpr.meetings_lib, "replay_local", lambda data_dir: meeting_state)
    ctx = mpr.PrepContext(event=_event(), meeting_cfg=_cfg(), config={"data_dir": "data"}, storage=FakeStorage())
    out = mpr.gather_open_threads(ctx, {})
    assert "Open Threads" in out
    assert "Ship onboarding v2" in out
    assert "Old resolved thing" not in out


def test_gather_open_threads_none_when_no_meeting(monkeypatch):
    monkeypatch.setattr(mpr.meetings_lib, "replay_local", lambda data_dir: {})
    ctx = mpr.PrepContext(event=_event(), meeting_cfg=_cfg(), config={}, storage=FakeStorage())
    assert mpr.gather_open_threads(ctx, {}) is None


def test_gather_last_session_reads_md_summary():
    storage = FakeStorage(files={
        "meeting_memory/luke_1on1.md": "# Luke 1:1\n\n## Session Log\n\n### 2026-07-28\nTalked roadmap.\n"
    })
    ctx = mpr.PrepContext(event=_event(), meeting_cfg=_cfg(), config={}, storage=storage)
    out = mpr.gather_last_session(ctx, {})
    assert "Last Session" in out
    assert "Talked roadmap." in out


def test_gather_last_session_none_when_absent():
    ctx = mpr.PrepContext(event=_event(), meeting_cfg=_cfg(), config={}, storage=FakeStorage())
    assert mpr.gather_last_session(ctx, {}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_meeting_prep_recipe.py -v`
Expected: FAIL — `AttributeError: module 'processors.meeting_prep_recipe' has no attribute ...` / import error.

- [ ] **Step 3: Create the module with the two blocks**

Create `processors/meeting_prep_recipe.py`:

```python
"""Per-meeting prep recipes for the Today tab.

Deterministic block gathering + one LLM synthesis call. Non-fatal throughout:
a failing block is dropped; a failing synthesis yields None. The legacy
processors/meeting_prep.py (emailed brief) is intentionally not reused.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from lib import meetings as meetings_lib
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_meeting_prep_recipe.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep_recipe.py tests/test_meeting_prep_recipe.py
git commit -m "feat: open_threads + last_session prep blocks"
```

---

## Task 3: `project_next_actions` block (attendee selection + task capping)

**Files:**
- Modify: `processors/meeting_prep_recipe.py`
- Test: `tests/test_meeting_prep_recipe.py`

**Interfaces:**
- Consumes: `lib.identity` (`is_internal`, `load_people`, `build_lookup`, `resolve`), `lib.tasks.get_open_tasks(storage) -> list`, projects from `storage.read_json("projects_registry.json")`.
- Produces: `gather_project_next_actions(ctx, params: dict) -> Optional[str]`. `params` keys: `expand_threshold` (default 5), `max_per_project` (default 3). Also produces helper `_select_project_tasks(open_tasks, project_id, expand_threshold, max_per_project) -> list`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_meeting_prep_recipe.py`:

```python
def _projects(*projs):
    return {"version": 1, "projects": list(projs)}


def test_project_next_actions_selects_by_attendee_membership():
    people = [{"id": "luke-green", "email": "luke@teambuildr.com", "canonical_name": "Luke Green", "aliases": []}]
    projects = _projects(
        {"id": "p-onb", "canonical_name": "Onboarding", "status": "active",
         "members": [{"id": "luke-green", "role": "contact"}]},
        {"id": "p-other", "canonical_name": "Unrelated", "status": "active",
         "members": [{"id": "someone-else", "role": "owner"}]},
    )
    storage = FakeStorage(json_files={
        "people_registry.json": {"version": 1, "people": people},
        "projects_registry.json": projects,
    })
    tasks = [
        {"id": "t1", "title": "Draft flow", "status": "open", "project_id": "p-onb", "due_date": "2026-08-10", "horizon": None},
    ]
    import processors.meeting_prep_recipe as m
    m_get = m.tasks_lib.get_open_tasks
    try:
        m.tasks_lib.get_open_tasks = lambda s: tasks
        ctx = m.PrepContext(
            event=_event(attendees=[{"email": "luke@teambuildr.com", "name": "Luke Green"}]),
            meeting_cfg=_cfg(),
            config={"demo_scan": {"internal_domains": ["teambuildr.com"]}},
            storage=storage,
        )
        out = m.gather_project_next_actions(ctx, {})
    finally:
        m.tasks_lib.get_open_tasks = m_get
    assert "Onboarding" in out
    assert "Draft flow" in out
    assert "Unrelated" not in out


def test_project_next_actions_none_when_no_membership():
    storage = FakeStorage(json_files={
        "people_registry.json": {"version": 1, "people": []},
        "projects_registry.json": _projects(
            {"id": "p1", "canonical_name": "X", "status": "active", "members": []}),
    })
    import processors.meeting_prep_recipe as m
    ctx = m.PrepContext(
        event=_event(attendees=[{"email": "ext@other.com", "name": "Ext"}]),
        meeting_cfg=_cfg(),
        config={"demo_scan": {"internal_domains": ["teambuildr.com"]}},
        storage=storage,
    )
    assert m.gather_project_next_actions(ctx, {}) is None


def test_select_project_tasks_shows_all_at_or_below_threshold():
    import processors.meeting_prep_recipe as m
    tasks = [{"id": f"t{i}", "title": f"T{i}", "status": "open", "project_id": "p", "due_date": f"2026-08-0{i}", "horizon": None} for i in range(1, 6)]
    sel = m._select_project_tasks(tasks, "p", expand_threshold=5, max_per_project=3)
    assert len(sel) == 5


def test_select_project_tasks_caps_and_sorts_by_nearest_when_over_threshold():
    import processors.meeting_prep_recipe as m
    tasks = [
        {"id": "t1", "title": "far", "status": "open", "project_id": "p", "due_date": "2026-12-01", "horizon": None},
        {"id": "t2", "title": "near", "status": "open", "project_id": "p", "due_date": "2026-08-05", "horizon": None},
        {"id": "t3", "title": "mid", "status": "open", "project_id": "p", "due_date": "2026-09-01", "horizon": None},
        {"id": "t4", "title": "horizon-only", "status": "open", "project_id": "p", "due_date": None, "horizon": "2026-08-07"},
        {"id": "t5", "title": "none", "status": "open", "project_id": "p", "due_date": None, "horizon": None},
        {"id": "t6", "title": "nearest", "status": "open", "project_id": "p", "due_date": "2026-08-01", "horizon": None},
    ]
    sel = m._select_project_tasks(tasks, "p", expand_threshold=5, max_per_project=3)
    assert [t["title"] for t in sel] == ["nearest", "near", "horizon-only"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_meeting_prep_recipe.py -k "project_next_actions or select_project_tasks" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'gather_project_next_actions'`.

- [ ] **Step 3: Implement the block**

Add to `processors/meeting_prep_recipe.py` (imports at top, functions below the existing blocks):

```python
from lib import identity, tasks as tasks_lib

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_meeting_prep_recipe.py -k "project_next_actions or select_project_tasks" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep_recipe.py tests/test_meeting_prep_recipe.py
git commit -m "feat: project_next_actions block with attendee selection + task capping"
```

---

## Task 4: `pipeline_sales` block

**Files:**
- Modify: `processors/meeting_prep_recipe.py`
- Test: `tests/test_meeting_prep_recipe.py`

**Interfaces:**
- Consumes: `storage.read_json("... pipeline cache path ...")`; `processors.meeting_prep._format_demos_line() -> str` (reused for the demos line).
- Produces: `gather_pipeline_sales(ctx, params: dict) -> Optional[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_meeting_prep_recipe.py`:

```python
def test_pipeline_sales_renders_stage_breakdown(monkeypatch):
    import processors.meeting_prep_recipe as m
    monkeypatch.setattr(m, "_format_demos_line", lambda: "• Demos MTD: 12")
    storage = FakeStorage(json_files={
        "pipeline_cache.json": {"leads": [
            {"name": "Acme", "status": "Demo Scheduled", "stale": False},
            {"name": "Beta", "status": "Demo Scheduled", "stale": True},
            {"name": "Gamma", "status": "Proposal", "stale": False},
        ]},
    })
    ctx = m.PrepContext(event=_event(), meeting_cfg=_cfg(),
                        config={"pipeline": {"cache_path": "pipeline_cache.json"}}, storage=storage)
    out = m.gather_pipeline_sales(ctx, {})
    assert "Pipeline" in out
    assert "Demo Scheduled (2)" in out
    assert "Demos MTD: 12" in out


def test_pipeline_sales_none_when_empty(monkeypatch):
    import processors.meeting_prep_recipe as m
    monkeypatch.setattr(m, "_format_demos_line", lambda: "• Demos MTD: (unavailable)")
    storage = FakeStorage(json_files={"pipeline_cache.json": {"leads": []}})
    ctx = m.PrepContext(event=_event(), meeting_cfg=_cfg(),
                        config={"pipeline": {"cache_path": "pipeline_cache.json"}}, storage=storage)
    assert m.gather_pipeline_sales(ctx, {}) is None
```

Note: the demos line is stubbed via `monkeypatch.setattr` on the module attribute, so the block must reference it as a module-level name (imported at top), not via `meeting_prep._format_demos_line` inline.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_meeting_prep_recipe.py -k pipeline_sales -v`
Expected: FAIL — no attribute `gather_pipeline_sales`.

- [ ] **Step 3: Implement the block**

Add to `processors/meeting_prep_recipe.py`:

```python
from processors.meeting_prep import _format_demos_line
```

and the block:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_meeting_prep_recipe.py -k pipeline_sales -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep_recipe.py tests/test_meeting_prep_recipe.py
git commit -m "feat: pipeline_sales prep block"
```

---

## Task 5: `build_prep` orchestrator + `prep_hash` (synthesis, non-fatal)

**Files:**
- Modify: `processors/meeting_prep_recipe.py`
- Test: `tests/test_meeting_prep_recipe.py`

**Interfaces:**
- Consumes: all four `gather_*` functions; `anthropic.Anthropic`; `lib.llm_logger.log_usage`.
- Produces:
  - `_BLOCKS: dict[str, callable]` registry mapping block name → gather function.
  - `_normalize_block(entry) -> tuple[str, dict]` — accepts a string or `{"block": name, ...params}`.
  - `gather_blocks(recipe: dict, ctx: PrepContext) -> str` — concatenated non-empty block outputs (empty string if none).
  - `prep_hash(recipe: dict) -> str` — 12-hex-char sha256 of the canonical recipe.
  - `build_prep(event, meeting_cfg, config, storage, api_key) -> Optional[str]` — returns markdown prep or `None`. Never raises.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_meeting_prep_recipe.py`:

```python
def test_normalize_block_string_and_object():
    import processors.meeting_prep_recipe as m
    assert m._normalize_block("open_threads") == ("open_threads", {})
    assert m._normalize_block({"block": "project_next_actions", "max_per_project": 2}) == (
        "project_next_actions", {"max_per_project": 2})


def test_gather_blocks_drops_empty_and_unknown(monkeypatch):
    import processors.meeting_prep_recipe as m
    monkeypatch.setitem(m._BLOCKS, "a", lambda ctx, params: "## A\nalpha")
    monkeypatch.setitem(m._BLOCKS, "b", lambda ctx, params: None)
    ctx = m.PrepContext(event=_event(), meeting_cfg=_cfg(), config={}, storage=FakeStorage())
    out = m.gather_blocks({"blocks": ["a", "b", "unknown"]}, ctx)
    assert "alpha" in out
    assert out.count("##") == 1  # only block a contributed


def test_gather_blocks_isolates_block_exception(monkeypatch):
    import processors.meeting_prep_recipe as m
    def boom(ctx, params):
        raise RuntimeError("nope")
    monkeypatch.setitem(m._BLOCKS, "boom", boom)
    monkeypatch.setitem(m._BLOCKS, "ok", lambda ctx, params: "## OK\nfine")
    ctx = m.PrepContext(event=_event(), meeting_cfg=_cfg(), config={}, storage=FakeStorage())
    out = m.gather_blocks({"blocks": ["boom", "ok"]}, ctx)
    assert "fine" in out


def test_prep_hash_stable_and_sensitive():
    import processors.meeting_prep_recipe as m
    r1 = {"blocks": ["open_threads"], "instruction": "x"}
    r2 = {"instruction": "x", "blocks": ["open_threads"]}  # key order differs
    assert m.prep_hash(r1) == m.prep_hash(r2)
    assert m.prep_hash(r1) != m.prep_hash({"blocks": ["open_threads"], "instruction": "y"})


def test_build_prep_none_when_no_recipe():
    import processors.meeting_prep_recipe as m
    assert m.build_prep(_event(), _cfg(prep_recipe=None), {}, FakeStorage(), "key") is None


def test_build_prep_none_when_no_blocks_produce(monkeypatch):
    import processors.meeting_prep_recipe as m
    monkeypatch.setitem(m._BLOCKS, "empty", lambda ctx, params: None)
    called = {"n": 0}
    monkeypatch.setattr(m, "_synthesize", lambda *a, **k: (called.__setitem__("n", called["n"] + 1) or "SHOULD NOT"))
    out = m.build_prep(_event(), _cfg(prep_recipe={"blocks": ["empty"]}), {}, FakeStorage(), "key")
    assert out is None
    assert called["n"] == 0  # no LLM call when nothing gathered


def test_build_prep_synthesizes_when_blocks_present(monkeypatch):
    import processors.meeting_prep_recipe as m
    monkeypatch.setitem(m._BLOCKS, "a", lambda ctx, params: "## A\nalpha")
    captured = {}
    def fake_synth(context, instruction, event_summary, config, api_key):
        captured["context"] = context
        captured["instruction"] = instruction
        return "PREP OUTPUT"
    monkeypatch.setattr(m, "_synthesize", fake_synth)
    recipe = {"blocks": ["a"], "instruction": "focus X"}
    out = m.build_prep(_event(), _cfg(prep_recipe=recipe), {}, FakeStorage(), "key")
    assert out == "PREP OUTPUT"
    assert "alpha" in captured["context"]
    assert captured["instruction"] == "focus X"


def test_build_prep_returns_none_on_synth_error(monkeypatch):
    import processors.meeting_prep_recipe as m
    monkeypatch.setitem(m._BLOCKS, "a", lambda ctx, params: "## A\nalpha")
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(m, "_synthesize", boom)
    out = m.build_prep(_event(), _cfg(prep_recipe={"blocks": ["a"]}), {}, FakeStorage(), "key")
    assert out is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_meeting_prep_recipe.py -k "normalize or gather_blocks or prep_hash or build_prep" -v`
Expected: FAIL — missing attributes.

- [ ] **Step 3: Implement the orchestrator**

Add to `processors/meeting_prep_recipe.py`:

```python
import hashlib
import json

import anthropic

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
```

- [ ] **Step 4: Run the full module test file**

Run: `python -m pytest tests/test_meeting_prep_recipe.py -v`
Expected: PASS (all tests across Tasks 2–5).

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep_recipe.py tests/test_meeting_prep_recipe.py
git commit -m "feat: build_prep orchestrator + prep_hash + block registry"
```

---

## Task 6: Wire prep into `today_brief` with caching; thread `api_key` from `main.py`

**Files:**
- Modify: `processors/today_brief.py` (docstring line 1-6; `_meeting_dict` 43-58; `build_today_brief` 61-69; `generate_and_write` 72-81)
- Modify: `main.py:52-58` (the `generate_and_write(...)` call)
- Test: `tests/test_today_brief.py`

**Interfaces:**
- Consumes: `processors.meeting_prep_recipe.build_prep(event, meeting_cfg, config, storage, api_key)`, `processors.meeting_prep_recipe.prep_hash(recipe)`, `processors.meeting_memory.load_meeting_index(path)`, `processors.meeting_memory.find_meeting_for_event(event, configs)`.
- Produces: `generate_and_write(config, events, storage, today, generated_at, api_key)` (new trailing param); each internal meeting dict may carry non-null `prep` plus a `prep_hash` sibling field.

- [ ] **Step 1: Write the failing tests**

These reuse the file's **existing** helpers: `_ev(eid, title, details, declined=False)` (top of `tests/test_today_brief.py`) and `LocalStorage`. Add `import json` to the top of the file if not present. Append:

```python
def _internal_ev(eid, title="Luke / Trent"):
    return _ev(eid, title, [{"email": "luke@teambuildr.com", "name": "Luke Green"}])


def _write_index(tmp_path, recipe):
    idx = tmp_path / "meeting_index.json"
    idx.write_text(json.dumps({"meetings": [{
        "calendar_pattern": "luke / trent",
        "memory_file": "data/meeting_memory/luke_1on1.md",
        "nudge_subject": "1:1?", "nudge_minutes_after": 5, "name": "Luke 1:1",
        "prep_recipe": recipe,
    }]}))
    return str(idx)


def test_internal_meeting_with_recipe_gets_prep(monkeypatch, tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    recipe = {"blocks": ["open_threads"], "instruction": "x"}
    idx_path = _write_index(tmp_path, recipe)

    calls = {"n": 0}
    monkeypatch.setattr(tb.meeting_prep_recipe, "build_prep",
                        lambda event, cfg, config, storage_, api_key: (calls.__setitem__("n", calls["n"] + 1) or "PREP TEXT"))

    config = {"meeting_index_file": idx_path, "demo_scan": {"internal_domains": ["teambuildr.com"]}}
    brief = tb.generate_and_write(config, [_internal_ev("m1")], storage,
                                  today="2026-08-04", generated_at="2026-08-04T12:00:00Z", api_key="key")
    m = next(x for x in brief["meetings"] if x["id"] == "m1")
    assert m["prep"] == "PREP TEXT"
    assert m["prep_hash"] == tb.meeting_prep_recipe.prep_hash(recipe)
    assert calls["n"] == 1


def test_prep_reused_from_prior_brief_when_hash_matches(monkeypatch, tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    recipe = {"blocks": ["open_threads"], "instruction": "x"}
    idx_path = _write_index(tmp_path, recipe)
    phash = tb.meeting_prep_recipe.prep_hash(recipe)
    # prior brief for the SAME day with a matching hash → cache hit
    storage.write_json("brief_today.json", {"date": "2026-08-04",
        "meetings": [{"id": "m1", "prep": "CACHED", "prep_hash": phash}]})

    def boom(*a, **k):
        raise AssertionError("build_prep should not be called on cache hit")
    monkeypatch.setattr(tb.meeting_prep_recipe, "build_prep", boom)

    config = {"meeting_index_file": idx_path, "demo_scan": {"internal_domains": ["teambuildr.com"]}}
    brief = tb.generate_and_write(config, [_internal_ev("m1")], storage,
                                  today="2026-08-04", generated_at="2026-08-04T12:00:00Z", api_key="key")
    m = next(x for x in brief["meetings"] if x["id"] == "m1")
    assert m["prep"] == "CACHED"


def test_prep_regenerates_when_hash_differs(monkeypatch, tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    recipe = {"blocks": ["open_threads"], "instruction": "NEW"}
    idx_path = _write_index(tmp_path, recipe)
    # prior brief carries a STALE hash → must re-run build_prep
    storage.write_json("brief_today.json", {"date": "2026-08-04",
        "meetings": [{"id": "m1", "prep": "OLD", "prep_hash": "staleeeeeeee"}]})
    monkeypatch.setattr(tb.meeting_prep_recipe, "build_prep",
                        lambda *a, **k: "FRESH")
    config = {"meeting_index_file": idx_path, "demo_scan": {"internal_domains": ["teambuildr.com"]}}
    brief = tb.generate_and_write(config, [_internal_ev("m1")], storage,
                                  today="2026-08-04", generated_at="2026-08-04T12:00:00Z", api_key="key")
    m = next(x for x in brief["meetings"] if x["id"] == "m1")
    assert m["prep"] == "FRESH"


def test_external_meeting_prep_stays_none(monkeypatch, tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    idx_path = _write_index(tmp_path, {"blocks": ["open_threads"]})
    monkeypatch.setattr(tb.meeting_prep_recipe, "build_prep",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no prep for external")))
    config = {"meeting_index_file": idx_path, "demo_scan": {"internal_domains": ["teambuildr.com"]}}
    ev = _ev("x1", "Prospect sync", [{"email": "buyer@acme.com", "name": "Buyer"}])
    brief = tb.generate_and_write(config, [ev], storage,
                                  today="2026-08-04", generated_at="2026-08-04T12:00:00Z", api_key="key")
    assert brief["meetings"][0]["prep"] is None
```

The external meeting's summary ("Prospect sync") does not match the `luke / trent` pattern anyway, but the assertion guards the `has_external` short-circuit in `_prep_for_event` regardless.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_today_brief.py -k "prep" -v`
Expected: FAIL — `generate_and_write()` takes no `api_key` / `today_brief` has no attribute `meeting_prep_recipe`.

- [ ] **Step 3: Update `today_brief.py`**

Replace the docstring's determinism line (lines 1-6) — change:

```python
Deterministic (no LLM in Plan 2): assembles today's meetings and the <=3
```

to:

```python
Assembles today's meetings and the <=3 tasks needing attention, and provisions
registry stubs for external attendees (Plan 1). Block gathering and task/meeting
assembly are deterministic; internal-meeting prep (Plan 4) adds one LLM synthesis
call per meeting that has a recipe. Written to the git-anchored registry.
```

Add imports near the top (after the existing `from lib import ...`):

```python
from processors import meeting_prep_recipe
from processors.meeting_memory import load_meeting_index, find_meeting_for_event
```

Replace `_meeting_dict` (lines 43-58) with a version that accepts a prep helper result:

```python
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
```

Replace `build_today_brief` (lines 61-69) to compute prep per internal meeting, with caching. **The new params are optional with defaults** so the existing Plan 2 test `test_build_today_brief_skips_declined_and_shapes_payload` (which calls with only 5 args) stays green:

```python
def build_today_brief(events, needs_items, internal_domains, today, generated_at,
                      config=None, storage=None, api_key="") -> dict:
    config = config or {}
    active = [ev for ev in events if not getattr(ev, "declined", False)]

    meeting_configs = load_meeting_index(config.get("meeting_index_file", "data/meeting_index.json"))
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
        "what_moved": [],
    }


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
```

Note: `_meeting_dict` recomputes `has_external` from `ev.attendees` for its `kind` field, and `_prep_for_event` recomputes it to short-circuit — this small duplication keeps each function independently readable and is not a correctness issue.

Update `generate_and_write` (lines 72-81) to take `api_key` and pass the new args:

```python
def generate_and_write(config: dict, events, storage, today: str, generated_at: str, api_key: str = "") -> dict:
    internal_domains = config.get("demo_scan", {}).get("internal_domains", _DEFAULT_INTERNAL_DOMAINS)
    active_events = [ev for ev in events if not getattr(ev, "declined", False)]
    provision_from_events(active_events, storage, config, today)
    needs = rank_needs(tasks_lib.get_due_or_surfaced(storage, today=today), today)
    brief = build_today_brief(active_events, needs, internal_domains, today, generated_at,
                              config, storage, api_key)
    storage.write_json("brief_today.json", brief)
    return brief
```

- [ ] **Step 4: Update `main.py` to pass `api_key`**

In `main.py`, the call at lines 52-58 becomes:

```python
            generate_and_write(
                config,
                collected.today_events,
                registry_storage(config),
                today=date.today().isoformat(),
                generated_at=datetime.now(timezone.utc).isoformat(),
                api_key=api_key,
            )
```

(`api_key` is already defined at `main.py:35`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_today_brief.py -v`
Expected: PASS (new prep tests + existing Plan 2 tests).

- [ ] **Step 6: Commit**

```bash
git add processors/today_brief.py main.py tests/test_today_brief.py
git commit -m "feat: wire internal meeting prep into today_brief with daily caching"
```

---

## Task 7: Seed the Luke 1:1 recipe + end-to-end check

**Files:**
- Modify: `data/meeting_index.json` (the `Luke 1:1` entry)
- Test: `tests/test_meeting_prep_recipe.py` (one integration-style test with all blocks stubbed at the boundary)

**Interfaces:**
- Consumes: everything above.
- Produces: a live recipe on the Luke 1:1 config.

- [ ] **Step 1: Add the recipe to `data/meeting_index.json`**

In the `"Luke 1:1"` entry (currently lines 33-40), add a `prep_recipe` key:

```json
    {
      "calendar_pattern": "luke / trent",
      "memory_file": "data/meeting_memory/luke_1on1.md",
      "nudge_subject": "1:1 notes?",
      "nudge_minutes_after": 5,
      "name": "Luke 1:1",
      "people_ids": [],
      "prep_recipe": {
        "blocks": [
          "open_threads",
          "last_session",
          {"block": "project_next_actions", "expand_threshold": 5, "max_per_project": 3},
          "pipeline_sales"
        ],
        "instruction": "Walk through each project below in turn — these are the ones I keep Luke informed on. For each, give a one-line high-level status backed by its open tasks (the tasks are the signal of what I'm working on next), and call out any blocker. This is my update to Luke, project by project."
      }
    }
```

- [ ] **Step 2: Verify the config parses and the recipe is discoverable (write the test)**

Append to `tests/test_meeting_prep_recipe.py`:

```python
def test_seeded_luke_recipe_parses_and_matches_calendar_event():
    from processors.meeting_memory import load_meeting_index, find_meeting_for_event
    configs = load_meeting_index("data/meeting_index.json")
    ev = _event(summary="Luke / Trent")
    cfg = find_meeting_for_event(ev, configs)
    assert cfg is not None
    assert cfg.name == "Luke 1:1"
    assert cfg.prep_recipe is not None
    names = [b if isinstance(b, str) else b["block"] for b in cfg.prep_recipe["blocks"]]
    assert names == ["open_threads", "last_session", "project_next_actions", "pipeline_sales"]
```

- [ ] **Step 3: Run it (and it should pass immediately, since the config edit is the implementation)**

Run: `python -m pytest tests/test_meeting_prep_recipe.py::test_seeded_luke_recipe_parses_and_matches_calendar_event -v`
Expected: PASS. If it fails on JSON parse, fix the edit in `data/meeting_index.json`.

- [ ] **Step 4: Full regression + JSON lint**

Run:
```bash
python -c "import json; json.load(open('data/meeting_index.json')); print('meeting_index.json OK')"
python -m pytest tests/test_meeting_prep_recipe.py tests/test_meeting_memory.py tests/test_today_brief.py -v
```
Expected: JSON OK; all tests PASS.

- [ ] **Step 5: Local smoke (no email, no send)**

Run: `python main.py --no-email`
Then inspect the generated brief:
```bash
python -c "import json; b=json.load(open('data/brief_today.json')); [print(m['title'], '->', 'PREP' if m.get('prep') else 'none') for m in b['meetings']]"
```
Expected: the run completes; if a "Luke / Trent" meeting is on today's calendar it prints `PREP` (given `ANTHROPIC_API_KEY` is set and Luke is a member of ≥1 active project). If no Luke meeting today, this is a no-op — that's fine.

- [ ] **Step 6: Commit**

```bash
git add data/meeting_index.json tests/test_meeting_prep_recipe.py
git commit -m "feat: seed Luke 1:1 prep recipe"
```

---

## Self-Review Notes (for the implementer)

- **`prep_hash` field on meeting dicts:** only internal meetings with a recipe carry `prep_hash`; external and recipe-less meetings omit it (keeps the schema minimal). The Today-tab UI ignores unknown fields, so this is safe.
- **Storage keys:** blocks read via `storage.read_json`/`storage.read` with **storage-relative** keys (leading `data/` stripped). `replay_local` reads the working tree directly by `data_dir` (matches the legacy `meeting_prep.py` pattern).
- **Source split is intentional:** `open_threads` comes from `meetings.jsonl` (live registry), `last_session` from the `meeting_memory/*.md` session log — both per the approved spec. Either being empty just drops that block.
- **Non-fatal is layered:** per-block try/except in `gather_blocks`, plus a top-level try/except in `build_prep`, plus the existing try/except around `generate_and_write` in `main.py` — three independent guards so prep can never break the brief.
