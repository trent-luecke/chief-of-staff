# Project as a First-Class Entity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Project entity with full CRUD, reply-gated Slack linking, a link index, and brief integration.

**Architecture:**
- `data/projects_registry.json` mirrors the people registry pattern.
- `lib/tasks.py` converts from whole-file JSON to a JSONL event log (`data/tasks.jsonl`) — three event types: `create`, `complete`, `edit`. This is the prerequisite for everything else; it fixes the git-merge seam and absorbs `project_id` + `collaborators` into the `create` event schema.
- Project→observation links live in `data/project_observation_links.jsonl` (JSONL event log, same rationale: Slack confirmation routes through Actions, making it a two-writer file).
- `project_ids` is **not** stamped on observations — the link index is the single mechanism for that relationship.
- Project link candidates are flagged from Avoma Phase 2 Slack threads, stored in `data/project_link_candidates.json` (local-only, single writer → plain JSON is safe). Confirmation in-thread appends a link event and resolves the candidate.
- A minimal Flask server (`tools/server.py`) serves the entity UI and mediates task writes locally. The Actions pipeline uses the same `lib/tasks.py` API — the JSONL backend makes concurrent appends git-safe.

**Tech Stack:** Python 3, Flask (`pip install flask`), vanilla JS / File System Access API (existing pattern), `anthropic` SDK (existing), `pytest`.

**Known deferred debt:** JSONL log compaction (tasks and link index both grow forever; compaction is a future pass).

---

## File Map

**New files:**
- `lib/projects.py` — project registry load/save/find/update
- `lib/project_candidates.py` — read/write `data/project_link_candidates.json`
- `lib/project_links.py` — JSONL event log for project→observation links
- `tools/server.py` — Flask server: serves entity UI + task/project CRUD API
- `tests/test_projects.py`
- `tests/test_project_candidates.py`
- `tests/test_project_links.py`

**Modified files:**
- `lib/tasks.py` — full rewrite: JSON → JSONL event log; adds `project_id` + `collaborators` to create event
- `processors/avoma_phase2.py` — add `propose_project_link` tool; add Slack link-confirmation handler
- `processors/avoma_thread_state.py` — add `pending_project_link` field to thread state schema
- `tools/registry_ui.html` — add Projects tab; entity-attached task panels; task writes via Flask API
- `main.py` / brief assembly — add project context section
- `tests/test_tasks.py` — update for JSONL backend + new fields
- `tests/test_avoma_phase2.py` — cover propose_project_link + confirmation flow

**Removed from earlier draft:**
- `lib/tasks_db.py` — not written (SQLite un-decided)
- `scripts/sync_tasks_to_db.py` — not written
- `processors/memory_observer.py` changes — `project_ids` field dropped entirely

---

## Task 1: Project Registry — `lib/projects.py`

**Files:**
- Create: `lib/projects.py`
- Create: `tests/test_projects.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_projects.py
import pytest
from lib.storage import LocalStorage
from lib.projects import (
    add_project, get_project, list_projects,
    find_project_by_alias, update_project,
    project_context_for_brief,
)


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_add_project_minimal(tmp_path):
    p = add_project(_s(tmp_path), canonical_name="Nicole Campaign")
    assert p["canonical_name"] == "Nicole Campaign"
    assert p["id"] == "nicole-campaign"
    assert p["status"] == "active"
    assert p["members"] == []
    assert p["aliases"] == []


def test_add_project_with_aliases_and_members(tmp_path):
    p = add_project(
        _s(tmp_path),
        canonical_name="Customer Outreach 2026",
        aliases=["marketing push"],
        members=[{"person_id": "nicole-foley", "role": "owner"}],
    )
    assert "marketing push" in p["aliases"]
    assert p["members"][0]["role"] == "owner"


def test_add_project_deduplicates_slug(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Demo")
    p2 = add_project(s, canonical_name="Demo")
    assert p2["id"] == "demo-2"


def test_get_project_found(tmp_path):
    s = _s(tmp_path)
    added = add_project(s, canonical_name="Alpha")
    assert get_project(s, added["id"])["id"] == added["id"]


def test_get_project_missing(tmp_path):
    assert get_project(_s(tmp_path), "nope") is None


def test_list_projects_empty(tmp_path):
    assert list_projects(_s(tmp_path)) == []


def test_list_projects(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Alpha")
    add_project(s, canonical_name="Beta")
    assert len(list_projects(s)) == 2


def test_list_projects_filter_status(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Active One", status="active")
    add_project(s, canonical_name="Archived", status="archived")
    assert len(list_projects(s, status="active")) == 1


def test_find_by_alias(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Nicole Campaign", aliases=["marketing push"])
    assert find_project_by_alias(s, "marketing push") is not None
    assert find_project_by_alias(s, "unknown") is None


def test_find_by_alias_case_insensitive(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Demo Push", aliases=["Demo Push"])
    assert find_project_by_alias(s, "demo push") is not None


def test_find_by_canonical_name(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Exact Match")
    assert find_project_by_alias(s, "Exact Match") is not None


def test_update_project(tmp_path):
    s = _s(tmp_path)
    p = add_project(s, canonical_name="Draft")
    updated = update_project(s, p["id"], {"status": "archived"})
    assert updated["status"] == "archived"
    assert get_project(s, p["id"])["status"] == "archived"


def test_update_project_missing(tmp_path):
    assert update_project(_s(tmp_path), "nope", {"status": "archived"}) is None


def test_persisted_across_loads(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Persist Me")
    s2 = LocalStorage(base_dir=str(tmp_path))
    assert list_projects(s2)[0]["canonical_name"] == "Persist Me"


def test_project_context_for_brief_empty(tmp_path):
    assert project_context_for_brief(_s(tmp_path)) == []


def test_project_context_for_brief_with_open_task(tmp_path):
    from lib.tasks import add_task
    s = _s(tmp_path)
    add_project(s, canonical_name="Nicole Campaign")
    add_task(s, "Follow up", project_id="nicole-campaign")
    ctx = project_context_for_brief(s)
    assert len(ctx) == 1
    assert ctx[0]["project"]["id"] == "nicole-campaign"
    assert len(ctx[0]["open_tasks"]) == 1
    assert ctx[0]["linked_obs"] == []
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_projects.py -v
```
Expected: `ImportError` for `lib.projects`.

- [ ] **Step 3: Implement `lib/projects.py`**

```python
# lib/projects.py
import json
import re
from datetime import date, timedelta
from typing import Optional

_PROJECTS_KEY = "projects_registry.json"


def _load(storage) -> dict:
    return storage.read_json(_PROJECTS_KEY, default={"version": 1, "projects": []})


def _save(storage, data: dict) -> None:
    storage.write_json(_PROJECTS_KEY, data)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _unique_id(base: str, existing_ids: set) -> str:
    if base not in existing_ids:
        return base
    for i in range(2, 100):
        candidate = f"{base}-{i}"
        if candidate not in existing_ids:
            return candidate
    return base


def add_project(
    storage,
    canonical_name: str,
    aliases: Optional[list] = None,
    status: str = "active",
    members: Optional[list] = None,
) -> dict:
    data = _load(storage)
    existing_ids = {p["id"] for p in data["projects"]}
    project_id = _unique_id(_slug(canonical_name), existing_ids)
    project = {
        "id": project_id,
        "canonical_name": canonical_name,
        "aliases": aliases or [],
        "status": status,
        "members": members or [],
        "created": date.today().isoformat(),
        "last_seen": date.today().isoformat(),
    }
    data["projects"].append(project)
    _save(storage, data)
    return project


def get_project(storage, project_id: str) -> Optional[dict]:
    for p in _load(storage)["projects"]:
        if p["id"] == project_id:
            return p
    return None


def list_projects(storage, status: Optional[str] = None) -> list:
    projects = _load(storage)["projects"]
    if status is not None:
        projects = [p for p in projects if p.get("status") == status]
    return projects


def find_project_by_alias(storage, alias: str) -> Optional[dict]:
    alias_lower = alias.lower()
    for p in _load(storage)["projects"]:
        if alias_lower == p["canonical_name"].lower():
            return p
        if alias_lower in [a.lower() for a in p.get("aliases", [])]:
            return p
    return None


def update_project(storage, project_id: str, updates: dict) -> Optional[dict]:
    data = _load(storage)
    for p in data["projects"]:
        if p["id"] == project_id:
            p.update(updates)
            p["last_seen"] = date.today().isoformat()
            _save(storage, data)
            return p
    return None


def project_context_for_brief(storage, observation_days: int = 14) -> list[dict]:
    """Active projects with open tasks and recently linked observations.

    Returns list of:
      {"project": {...}, "open_tasks": [...], "linked_obs": [...]}
    """
    from lib.tasks import get_open_tasks
    from lib.project_links import get_links_for_project

    active = list_projects(storage, status="active")
    if not active:
        return []

    cutoff = (date.today() - timedelta(days=observation_days)).isoformat()
    all_tasks = get_open_tasks(storage)

    results = []
    for project in active:
        pid = project["id"]
        p_tasks = [t for t in all_tasks if t.get("project_id") == pid]
        all_links = get_links_for_project(storage, pid)
        recent_links = [lk for lk in all_links if lk.get("obs_date", "") >= cutoff]
        results.append({
            "project": project,
            "open_tasks": p_tasks,
            "linked_obs": recent_links,
        })
    return results
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_projects.py -v
```
Expected: `test_project_context_for_brief_with_open_task` will fail because `lib/project_links` doesn't exist yet. All other tests PASS. That failure is expected — fix it after Task 4.

- [ ] **Step 5: Commit passing tests only**

```bash
git add lib/projects.py tests/test_projects.py
git commit -m "feat: add project registry (lib/projects.py)"
```

---

## Task 2: Tasks → JSONL Event Log

**Files:**
- Rewrite: `lib/tasks.py`
- Modify: `tests/test_tasks.py`

This replaces the whole-file-rewrite JSON pattern with an append-only event log. The public API (`add_task`, `complete_task`, `get_open_tasks`, `get_recent_completions`) is unchanged. The storage key changes from `tasks.json` to `tasks.jsonl`. Three event types: `create`, `complete`, `edit`.

`project_id` and `collaborators` are introduced here as fields on the `create` event. An `edit` event patches any field, including `project_id`, after creation.

On first read, if `tasks.jsonl` does not exist but `tasks.json` does, a one-time migration converts existing records to `create` (and `complete`) events.

- [ ] **Step 1: Write the failing tests**

Replace the contents of `tests/test_tasks.py` with:

```python
import json
import pytest
from lib.storage import LocalStorage
from lib.tasks import add_task, complete_task, get_open_tasks, get_recent_completions, edit_task


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


# --- Basic create/read ---

def test_add_task_minimal(tmp_path):
    task = add_task(_s(tmp_path), "Send deck")
    assert task["title"] == "Send deck"
    assert task["status"] == "open"
    assert task["source"] == "telegram"
    assert task["project_id"] is None
    assert task["collaborators"] == []
    assert task["metadata"] == {}


def test_add_task_with_project_id(tmp_path):
    task = add_task(_s(tmp_path), "Follow up", project_id="nicole-campaign")
    assert task["project_id"] == "nicole-campaign"


def test_add_task_with_collaborators(tmp_path):
    task = add_task(_s(tmp_path), "Prep slides", collaborators=["nicole-foley"])
    assert task["collaborators"] == ["nicole-foley"]


def test_add_task_with_metadata(tmp_path):
    meta = {"avoma_uuid": "abc", "thread_ts": "ts.123"}
    task = add_task(_s(tmp_path), "Follow up", source="avoma", metadata=meta)
    assert task["metadata"] == meta
    assert task["source"] == "avoma"


def test_get_open_tasks_empty(tmp_path):
    assert get_open_tasks(_s(tmp_path)) == []


def test_get_open_tasks_returns_open(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Task A")
    add_task(s, "Task B")
    tasks = get_open_tasks(s)
    assert len(tasks) == 2
    assert all(t["status"] == "open" for t in tasks)


def test_add_task_metadata_persisted(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Check in", source="avoma", metadata={"avoma_uuid": "xyz"})
    assert get_open_tasks(s)[0]["metadata"]["avoma_uuid"] == "xyz"


# --- Complete ---

def test_complete_task(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Send deck")
    result = complete_task(s, "Send deck")
    assert result is not None
    assert result["status"] == "completed"
    assert get_open_tasks(s) == []


def test_complete_task_partial_match(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Send the deck to Acme")
    assert complete_task(s, "deck to Acme") is not None


def test_complete_task_missing(tmp_path):
    assert complete_task(_s(tmp_path), "nonexistent") is None


def test_get_recent_completions(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Done task")
    complete_task(s, "Done task")
    assert len(get_recent_completions(s, days=7)) == 1


# --- Edit ---

def test_edit_task_project_id(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Unlinked task")
    edited = edit_task(s, task["id"], {"project_id": "nicole-campaign"})
    assert edited["project_id"] == "nicole-campaign"
    assert get_open_tasks(s)[0]["project_id"] == "nicole-campaign"


def test_edit_task_collaborators(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Solo task")
    edit_task(s, task["id"], {"collaborators": ["luke-martin"]})
    assert get_open_tasks(s)[0]["collaborators"] == ["luke-martin"]


def test_edit_task_missing(tmp_path):
    assert edit_task(_s(tmp_path), "t-nope", {"project_id": "x"}) is None


# --- JSONL format on disk ---

def test_events_are_appended_as_jsonl(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Check format")
    complete_task(s, "Check format")
    lines = (tmp_path / "tasks.jsonl").read_text().strip().splitlines()
    events = [json.loads(l) for l in lines]
    assert events[0]["event"] == "create"
    assert events[1]["event"] == "complete"
    assert events[0]["task_id"] == task["id"]
    assert events[1]["task_id"] == task["id"]


def test_edit_appends_edit_event(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Edit me")
    edit_task(s, task["id"], {"project_id": "proj-x"})
    lines = (tmp_path / "tasks.jsonl").read_text().strip().splitlines()
    events = [json.loads(l) for l in lines]
    assert events[1]["event"] == "edit"
    assert events[1]["patch"]["project_id"] == "proj-x"


# --- Migration from tasks.json ---

def test_migration_from_legacy_json(tmp_path):
    import json as _json
    (tmp_path / "tasks.json").write_text(_json.dumps({"tasks": [
        {"id": "t-old", "title": "Migrated task", "status": "open",
         "created_at": "2026-01-01", "due_date": None, "source": "telegram",
         "completed_at": None, "metadata": {}}
    ]}))
    s = _s(tmp_path)
    tasks = get_open_tasks(s)
    assert tasks[0]["title"] == "Migrated task"
    assert tasks[0]["project_id"] is None
    assert tasks[0]["collaborators"] == []
    # jsonl should now exist
    assert (tmp_path / "tasks.jsonl").exists()


def test_migration_preserves_completed_status(tmp_path):
    import json as _json
    (tmp_path / "tasks.json").write_text(_json.dumps({"tasks": [
        {"id": "t-done", "title": "Completed task", "status": "completed",
         "created_at": "2026-01-01", "due_date": None, "source": "telegram",
         "completed_at": "2026-01-02", "metadata": {}}
    ]}))
    s = _s(tmp_path)
    assert get_open_tasks(s) == []
    assert len(get_recent_completions(s, days=9999)) == 1


# --- Legacy record without project fields (post-migration safety) ---

def test_legacy_record_without_project_fields(tmp_path):
    s = _s(tmp_path)
    # Simulate a create event written before project_id was added
    (tmp_path / "tasks.jsonl").write_text(
        '{"event": "create", "task_id": "t-old", "title": "Old", '
        '"source": "telegram", "created_at": "2026-01-01", '
        '"due_date": null, "metadata": {}}\n'
    )
    tasks = get_open_tasks(s)
    assert tasks[0].get("project_id") is None
    assert tasks[0].get("collaborators", []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tasks.py -v
```
Expected: failures on `edit_task` import and JSONL-format tests. Existing pass/fail split is fine — note what's passing before the rewrite.

- [ ] **Step 3: Rewrite `lib/tasks.py`**

```python
# lib/tasks.py
import json
import uuid
from datetime import date, timedelta
from typing import Optional

_KEY = "tasks.jsonl"
_LEGACY_KEY = "tasks.json"


def _migrate_if_needed(storage) -> None:
    """One-time migration: tasks.json → tasks.jsonl create/complete events."""
    if storage.exists(_KEY):
        return
    legacy = storage.read_json(_LEGACY_KEY, default=None)
    if not legacy:
        return
    lines = []
    for t in legacy.get("tasks", []):
        create_event = {
            "event": "create",
            "task_id": t["id"],
            "title": t["title"],
            "source": t.get("source", "telegram"),
            "created_at": t.get("created_at", date.today().isoformat()),
            "due_date": t.get("due_date"),
            "metadata": t.get("metadata") or {},
            "project_id": t.get("project_id"),
            "collaborators": t.get("collaborators") or [],
        }
        lines.append(json.dumps(create_event))
        if t.get("status") == "completed":
            complete_event = {
                "event": "complete",
                "task_id": t["id"],
                "completed_at": t.get("completed_at") or date.today().isoformat(),
            }
            lines.append(json.dumps(complete_event))
    storage.write(_KEY, "\n".join(lines) + ("\n" if lines else ""))


def _replay(storage) -> dict:
    """Replay the event log and return current task state keyed by task_id."""
    _migrate_if_needed(storage)
    content = storage.read(_KEY) or ""
    tasks = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        task_id = event.get("task_id")
        if not task_id:
            continue
        etype = event["event"]
        if etype == "create":
            tasks[task_id] = {
                "id": task_id,
                "title": event["title"],
                "status": "open",
                "created_at": event["created_at"],
                "due_date": event.get("due_date"),
                "source": event.get("source", "telegram"),
                "completed_at": None,
                "metadata": event.get("metadata") or {},
                "project_id": event.get("project_id"),
                "collaborators": event.get("collaborators") or [],
            }
        elif etype == "complete" and task_id in tasks:
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["completed_at"] = event["completed_at"]
        elif etype == "edit" and task_id in tasks:
            tasks[task_id].update(event.get("patch", {}))
    return tasks


def _append(storage, event: dict) -> None:
    storage.append_line(_KEY, json.dumps(event))


def add_task(
    storage,
    title: str,
    source: str = "telegram",
    due_date: Optional[str] = None,
    metadata: Optional[dict] = None,
    project_id: Optional[str] = None,
    collaborators: Optional[list] = None,
) -> dict:
    _migrate_if_needed(storage)
    task_id = f"t-{uuid.uuid4().hex[:6]}"
    today = date.today().isoformat()
    event = {
        "event": "create",
        "task_id": task_id,
        "title": title,
        "source": source,
        "created_at": today,
        "due_date": due_date,
        "metadata": metadata if metadata is not None else {},
        "project_id": project_id,
        "collaborators": collaborators or [],
    }
    _append(storage, event)
    return {
        "id": task_id,
        "title": title,
        "status": "open",
        "created_at": today,
        "due_date": due_date,
        "source": source,
        "completed_at": None,
        "metadata": metadata if metadata is not None else {},
        "project_id": project_id,
        "collaborators": collaborators or [],
    }


def complete_task(storage, match_text: str) -> Optional[dict]:
    tasks = _replay(storage)
    match_lower = match_text.lower()
    for task in tasks.values():
        if task["status"] == "open" and match_lower in task["title"].lower():
            today = date.today().isoformat()
            _append(storage, {"event": "complete", "task_id": task["id"], "completed_at": today})
            task["status"] = "completed"
            task["completed_at"] = today
            return task
    return None


def edit_task(storage, task_id: str, patch: dict) -> Optional[dict]:
    tasks = _replay(storage)
    if task_id not in tasks:
        return None
    _append(storage, {"event": "edit", "task_id": task_id, "patch": patch})
    tasks[task_id].update(patch)
    return tasks[task_id]


def get_open_tasks(storage) -> list:
    return [t for t in _replay(storage).values() if t["status"] == "open"]


def get_recent_completions(storage, days: int = 7) -> list:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [
        t for t in _replay(storage).values()
        if t["status"] == "completed" and (t.get("completed_at") or "") >= cutoff
    ]
```

- [ ] **Step 4: Run all task tests**

```bash
pytest tests/test_tasks.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Run the full suite to catch regressions**

```bash
pytest -v --tb=short 2>&1 | grep -E "FAILED|ERROR|passed|failed"
```
Fix any failures before committing. Callers of `add_task` elsewhere in the codebase use keyword arguments — the new signature is backward-compatible.

- [ ] **Step 6: Commit**

```bash
git add lib/tasks.py tests/test_tasks.py
git commit -m "feat: convert tasks to JSONL event log; add project_id, collaborators, edit_task"
```

---

## Task 3: Project Candidates Store — `lib/project_candidates.py`

**Files:**
- Create: `lib/project_candidates.py`
- Create: `tests/test_project_candidates.py`

`project_link_candidates.json` is written locally only (the entity UI and the local resolution flow). Actions never writes it — it only reads it to hydrate the pending_project_link field in Avoma thread state. Plain JSON is safe here.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_project_candidates.py
import pytest
from lib.storage import LocalStorage
from lib.project_candidates import (
    flag_candidate, list_pending_candidates, resolve_candidate, get_candidate,
)


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_flag_candidate(tmp_path):
    c = flag_candidate(
        _s(tmp_path),
        project_id="nicole-campaign",
        obs_date="2026-06-02",
        obs_entity="demo-call-acme",
        source_thread_ts="1234.5678",
        call_title="Demo - Acme",
    )
    assert c["project_id"] == "nicole-campaign"
    assert c["status"] == "pending"
    assert c["id"].startswith("plc-")


def test_list_pending_empty(tmp_path):
    assert list_pending_candidates(_s(tmp_path)) == []


def test_list_pending_returns_only_pending(tmp_path):
    s = _s(tmp_path)
    c = flag_candidate(s, project_id="proj-a", obs_date="2026-06-02",
                       obs_entity="ent", source_thread_ts="ts1", call_title="Call A")
    resolve_candidate(s, c["id"], "confirmed")
    flag_candidate(s, project_id="proj-b", obs_date="2026-06-02",
                   obs_entity="ent2", source_thread_ts="ts2", call_title="Call B")
    assert len(list_pending_candidates(s)) == 1
    assert list_pending_candidates(s)[0]["project_id"] == "proj-b"


def test_get_candidate(tmp_path):
    s = _s(tmp_path)
    c = flag_candidate(s, project_id="proj-a", obs_date="2026-06-02",
                       obs_entity="ent", source_thread_ts="ts1", call_title="Call A")
    assert get_candidate(s, c["id"])["id"] == c["id"]


def test_get_candidate_missing(tmp_path):
    assert get_candidate(_s(tmp_path), "nope") is None


def test_resolve_confirmed(tmp_path):
    s = _s(tmp_path)
    c = flag_candidate(s, project_id="proj-a", obs_date="2026-06-02",
                       obs_entity="ent", source_thread_ts="ts1", call_title="Call")
    resolved = resolve_candidate(s, c["id"], "confirmed")
    assert resolved["status"] == "confirmed"
    assert list_pending_candidates(s) == []


def test_resolve_dismissed(tmp_path):
    s = _s(tmp_path)
    c = flag_candidate(s, project_id="proj-a", obs_date="2026-06-02",
                       obs_entity="ent", source_thread_ts="ts1", call_title="Call")
    resolve_candidate(s, c["id"], "dismissed")
    assert list_pending_candidates(s) == []


def test_resolve_missing(tmp_path):
    assert resolve_candidate(_s(tmp_path), "nope", "confirmed") is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_project_candidates.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement `lib/project_candidates.py`**

```python
# lib/project_candidates.py
import uuid
from datetime import date
from typing import Optional

_KEY = "project_link_candidates.json"


def _load(storage) -> dict:
    return storage.read_json(_KEY, default={"candidates": []})


def _save(storage, data: dict) -> None:
    storage.write_json(_KEY, data)


def flag_candidate(
    storage,
    project_id: str,
    obs_date: str,
    obs_entity: str,
    source_thread_ts: str,
    call_title: str,
) -> dict:
    data = _load(storage)
    candidate = {
        "id": f"plc-{uuid.uuid4().hex[:6]}",
        "project_id": project_id,
        "obs_date": obs_date,
        "obs_entity": obs_entity,
        "source_thread_ts": source_thread_ts,
        "call_title": call_title,
        "status": "pending",
        "created": date.today().isoformat(),
    }
    data["candidates"].append(candidate)
    _save(storage, data)
    return candidate


def get_candidate(storage, candidate_id: str) -> Optional[dict]:
    for c in _load(storage)["candidates"]:
        if c["id"] == candidate_id:
            return c
    return None


def list_pending_candidates(storage) -> list:
    return [c for c in _load(storage)["candidates"] if c["status"] == "pending"]


def resolve_candidate(storage, candidate_id: str, resolution: str) -> Optional[dict]:
    data = _load(storage)
    for c in data["candidates"]:
        if c["id"] == candidate_id:
            c["status"] = resolution
            _save(storage, data)
            return c
    return None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_project_candidates.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/project_candidates.py tests/test_project_candidates.py
git commit -m "feat: project link candidate store (lib/project_candidates.py)"
```

---

## Task 4: Project Link Index — `lib/project_links.py`

**Files:**
- Create: `lib/project_links.py`
- Create: `tests/test_project_links.py`

`data/project_observation_links.jsonl` is a JSONL event log. Two event types: `link` (adds a relationship) and `unlink` (removes it). Slack confirmation flows through Actions, making this a two-writer file — the same reason tasks use JSONL.

The index answers two queries:
- "What observations are linked to project X?" → `get_links_for_project`
- "What projects are linked to observation (date, entity)?" → `get_projects_for_observation`

Replay builds a set of active links; `unlink` events remove from the set.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_project_links.py
import pytest
from lib.storage import LocalStorage
from lib.project_links import add_link, remove_link, get_links_for_project, get_projects_for_observation


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_add_link(tmp_path):
    add_link(_s(tmp_path), project_id="proj-a", obs_date="2026-06-02",
             obs_entity="demo-call", source_thread_ts="ts1", call_title="Demo")
    links = get_links_for_project(_s(tmp_path), "proj-a")
    assert len(links) == 1
    assert links[0]["obs_date"] == "2026-06-02"
    assert links[0]["obs_entity"] == "demo-call"


def test_add_link_idempotent(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="demo-call", source_thread_ts="ts1", call_title="Demo")
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="demo-call", source_thread_ts="ts1", call_title="Demo")
    # Duplicate link events must deduplicate on read
    assert len(get_links_for_project(s, "proj-a")) == 1


def test_remove_link(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="demo-call", source_thread_ts="ts1", call_title="Demo")
    remove_link(s, project_id="proj-a", obs_date="2026-06-02", obs_entity="demo-call")
    assert get_links_for_project(s, "proj-a") == []


def test_get_links_for_project_empty(tmp_path):
    assert get_links_for_project(_s(tmp_path), "proj-x") == []


def test_get_links_multiple_projects(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-01",
             obs_entity="call-1", source_thread_ts="ts1", call_title="Call 1")
    add_link(s, project_id="proj-b", obs_date="2026-06-02",
             obs_entity="call-2", source_thread_ts="ts2", call_title="Call 2")
    assert len(get_links_for_project(s, "proj-a")) == 1
    assert len(get_links_for_project(s, "proj-b")) == 1


def test_get_projects_for_observation(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="shared-call", source_thread_ts="ts1", call_title="Shared")
    add_link(s, project_id="proj-b", obs_date="2026-06-02",
             obs_entity="shared-call", source_thread_ts="ts1", call_title="Shared")
    projects = get_projects_for_observation(s, obs_date="2026-06-02", obs_entity="shared-call")
    assert set(projects) == {"proj-a", "proj-b"}


def test_get_projects_for_observation_after_unlink(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="call", source_thread_ts="ts1", call_title="Call")
    remove_link(s, project_id="proj-a", obs_date="2026-06-02", obs_entity="call")
    assert get_projects_for_observation(s, "2026-06-02", "call") == []


def test_events_are_jsonl(tmp_path):
    import json
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="call", source_thread_ts="ts1", call_title="Call")
    lines = (tmp_path / "project_observation_links.jsonl").read_text().strip().splitlines()
    event = json.loads(lines[0])
    assert event["event"] == "link"
    assert event["project_id"] == "proj-a"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_project_links.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement `lib/project_links.py`**

```python
# lib/project_links.py
import json
from datetime import date
from typing import Optional

_KEY = "project_observation_links.jsonl"


def _replay(storage) -> dict:
    """Return active links as {(project_id, obs_date, obs_entity): link_dict}."""
    content = storage.read(_KEY) or ""
    active: dict[tuple, dict] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (event["project_id"], event["obs_date"], event["obs_entity"])
        if event["event"] == "link":
            active[key] = {
                "project_id": event["project_id"],
                "obs_date": event["obs_date"],
                "obs_entity": event["obs_entity"],
                "call_title": event.get("call_title", ""),
                "source_thread_ts": event.get("source_thread_ts", ""),
                "linked_at": event.get("linked_at", ""),
            }
        elif event["event"] == "unlink":
            active.pop(key, None)
    return active


def add_link(
    storage,
    project_id: str,
    obs_date: str,
    obs_entity: str,
    source_thread_ts: str,
    call_title: str,
) -> None:
    event = {
        "event": "link",
        "project_id": project_id,
        "obs_date": obs_date,
        "obs_entity": obs_entity,
        "source_thread_ts": source_thread_ts,
        "call_title": call_title,
        "linked_at": date.today().isoformat(),
    }
    storage.append_line(_KEY, json.dumps(event))


def remove_link(storage, project_id: str, obs_date: str, obs_entity: str) -> None:
    event = {
        "event": "unlink",
        "project_id": project_id,
        "obs_date": obs_date,
        "obs_entity": obs_entity,
        "unlinked_at": date.today().isoformat(),
    }
    storage.append_line(_KEY, json.dumps(event))


def get_links_for_project(storage, project_id: str) -> list:
    active = _replay(storage)
    return [v for k, v in active.items() if k[0] == project_id]


def get_projects_for_observation(storage, obs_date: str, obs_entity: str) -> list:
    active = _replay(storage)
    return [k[0] for k in active if k[1] == obs_date and k[2] == obs_entity]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_project_links.py -v
```
Expected: all PASS.

- [ ] **Step 5: Now re-run the project tests that were deferred**

```bash
pytest tests/test_projects.py -v
```
Expected: all tests PASS including `test_project_context_for_brief_with_open_task` (which imports `lib.project_links`).

- [ ] **Step 6: Commit**

```bash
git add lib/project_links.py tests/test_project_links.py
git commit -m "feat: project observation link index (JSONL event log, lib/project_links.py)"
```

---

## Task 5: Avoma Phase 2 — Propose and Confirm Project Links

**Files:**
- Modify: `processors/avoma_phase2.py`
- Modify: `processors/avoma_thread_state.py`
- Modify: `tests/test_avoma_phase2.py`

When Phase 2 processes a Slack thread reply, Claude can now call `propose_project_link`. This posts a suggestion to the thread and stores a `pending_project_link` in thread state. A subsequent "yes"/"confirm" reply applies the link.

### 5a — Extend thread state schema

- [ ] **Step 1: Add `pending_project_link` to `processors/avoma_thread_state.py`**

Add two functions after `clear_pending_correction`:

```python
def set_pending_project_link(storage, thread_ts: str, link_proposal: dict) -> None:
    """Store a proposed project link awaiting confirmation."""
    state = _load(storage)
    if thread_ts not in state:
        return
    state[thread_ts]["pending_project_link"] = link_proposal
    _save(storage, state)


def clear_pending_project_link(storage, thread_ts: str) -> None:
    state = _load(storage)
    if thread_ts not in state:
        return
    state[thread_ts]["pending_project_link"] = None
    _save(storage, state)
```

The thread state schema comment at the top of the file should document the new optional field:

```python
#   "pending_project_link": null | {
#     "candidate_id": str,
#     "project_id": str,
#     "obs_date": str,
#     "obs_entity": str,
#     "call_title": str,
#     "confirmation_prompt": str,
#   }
```

- [ ] **Step 2: Run existing thread state tests**

```bash
pytest tests/test_avoma_thread_state.py -v
```
Expected: all existing tests PASS (new functions are additive).

### 5b — Add `propose_project_link` tool to Phase 2

- [ ] **Step 3: Add tool schema and project context helper to `processors/avoma_phase2.py`**

Add after `_PROPOSE_TOOL`:

```python
_PROPOSE_PROJECT_LINK_TOOL = {
    "name": "propose_project_link",
    "description": (
        "Suggest linking this call's observation to one or more existing projects. "
        "ONLY call this when a call participant is a known member of the project. "
        "Do NOT invent links. Bias hard toward missing a link over making a false one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "project_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "IDs of existing projects this call plausibly relates to.",
            },
            "rationale": {
                "type": "string",
                "description": "One sentence: which participant triggered the match and why.",
            },
        },
        "required": ["project_ids", "rationale"],
    },
}
```

Add the project context helper (reads `projects_registry.json` to inject active project summaries into the Claude prompt):

```python
def _project_context_block(storage) -> str:
    from lib.projects import list_projects
    try:
        projects = list_projects(storage, status="active")
        if not projects:
            return ""
        lines = ["## Active Projects (for link consideration)"]
        for p in projects:
            member_ids = [m["person_id"] for m in p.get("members", [])]
            lines.append(
                f"- id={p['id']}  name={p['canonical_name']}"
                f"  members={', '.join(member_ids) or 'none'}"
            )
        return "\n".join(lines)
    except Exception:
        return ""
```

- [ ] **Step 4: Wire the tool into `_handle_fresh_message`**

Replace the `tools=[_PROPOSE_TOOL]` call with `tools=[_PROPOSE_TOOL, _PROPOSE_PROJECT_LINK_TOOL]`.

Prepend project context to `user_content`:

```python
proj_ctx = _project_context_block(storage)
user_content = (
    (proj_ctx + "\n\n") if proj_ctx else ""
) + (
    f"## Phase 1 Output\n{phase1_output}\n\n"
    f"## Call Analysis\n{json.dumps(transcript_json, indent=2)}\n\n"
    f"## Trent's message\n{trigger_text}"
)
```

In the response-processing loop, handle `propose_project_link`:

```python
project_link_input = None
for block in response.content:
    if block.type == "tool_use" and block.name == "propose_correction":
        correction_input = block.input
    elif block.type == "tool_use" and block.name == "propose_project_link":
        project_link_input = block.input
    elif block.type == "text":
        text_response = block.text.strip()
```

After the correction-handling block, add:

```python
if project_link_input:
    _handle_project_link_proposal(
        project_link_input, state_record, thread_ts, storage,
        slack_bot_token, channel_id,
    )
    return
```

Add the handler function:

```python
def _handle_project_link_proposal(
    proposal: dict,
    state_record: dict,
    thread_ts: str,
    storage,
    slack_bot_token: str,
    channel_id: str,
) -> None:
    from lib.project_candidates import flag_candidate
    from processors.avoma_thread_state import set_pending_project_link

    transcript_json = state_record.get("transcript_json", {})
    obs_date = (transcript_json.get("start_at") or "")[:10] or date.today().isoformat()
    # Use the Avoma UUID as a stable obs_entity identifier
    obs_entity = state_record.get("avoma_uuid") or thread_ts
    call_title = transcript_json.get("title", "")

    candidate_ids = []
    for pid in proposal.get("project_ids", []):
        c = flag_candidate(
            storage,
            project_id=pid,
            obs_date=obs_date,
            obs_entity=obs_entity,
            source_thread_ts=thread_ts,
            call_title=call_title,
        )
        candidate_ids.append(c["id"])

    # Store the first project's pending link in thread state for in-thread confirmation
    if proposal.get("project_ids"):
        set_pending_project_link(storage, thread_ts, {
            "candidate_ids": candidate_ids,
            "project_ids": proposal["project_ids"],
            "obs_date": obs_date,
            "obs_entity": obs_entity,
            "call_title": call_title,
            "confirmation_prompt": "Reply 'yes' to link, 'no' to dismiss.",
        })

    projects_str = ", ".join(proposal["project_ids"])
    msg = (
        f"Project link suggested: {projects_str}\n"
        f"Reason: {proposal['rationale']}\n\n"
        "Reply 'yes' to confirm or 'no' to dismiss."
    )
    post_to_thread(slack_bot_token, channel_id, thread_ts, msg)
```

- [ ] **Step 5: Add project link confirmation to `run_phase2`**

In `run_phase2`, before the correction-confirmation block, add:

```python
pending_link = state_record.get("pending_project_link")

if pending_link and trigger_lower in _CONFIRMATIONS:
    _apply_project_link(pending_link, storage, slack_bot_token, channel_id, thread_ts)
    clear_pending_project_link(storage, thread_ts)
    return

if pending_link and trigger_lower in _REJECTIONS:
    from lib.project_candidates import resolve_candidate
    from processors.avoma_thread_state import clear_pending_project_link
    for cid in pending_link.get("candidate_ids", []):
        resolve_candidate(storage, cid, "dismissed")
    clear_pending_project_link(storage, thread_ts)
    post_to_thread(slack_bot_token, channel_id, thread_ts, "Project link dismissed.")
    return
```

Add the apply function:

```python
def _apply_project_link(
    pending_link: dict,
    storage,
    slack_bot_token: str,
    channel_id: str,
    thread_ts: str,
) -> None:
    from lib.project_candidates import resolve_candidate
    from lib.project_links import add_link

    obs_date = pending_link["obs_date"]
    obs_entity = pending_link["obs_entity"]
    call_title = pending_link["call_title"]
    applied = []

    for pid, cid in zip(
        pending_link.get("project_ids", []),
        pending_link.get("candidate_ids", []),
    ):
        add_link(
            storage,
            project_id=pid,
            obs_date=obs_date,
            obs_entity=obs_entity,
            source_thread_ts=thread_ts,
            call_title=call_title,
        )
        resolve_candidate(storage, cid, "confirmed")
        applied.append(pid)

    post_to_thread(
        slack_bot_token, channel_id, thread_ts,
        f"Linked to: {', '.join(applied)}.",
    )
```

Add the missing import at the top of the file:

```python
from processors.avoma_thread_state import (
    set_pending_correction, clear_pending_correction,
    set_pending_project_link, clear_pending_project_link,
)
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_avoma_phase2.py tests/test_avoma_thread_state.py -v
```
Expected: all existing tests PASS. The new code paths are only triggered when `propose_project_link` fires, which existing test fixtures don't exercise.

- [ ] **Step 7: Commit**

```bash
git add processors/avoma_phase2.py processors/avoma_thread_state.py
git commit -m "feat: Avoma Phase 2 propose and confirm project links via Slack reply"
```

---

## Task 6: Flask Server + Entity UI Extension

**Files:**
- Create: `tools/server.py`
- Modify: `tools/registry_ui.html`

### 6a — Flask server

The server wraps `lib/tasks.py` (JSONL-backed) — no SQLite, no separate backend. It is the single local writer for task operations from the UI.

- [ ] **Step 1: Install Flask if not present**

```bash
pip show flask || pip install flask
```

- [ ] **Step 2: Create `tools/server.py`**

```python
#!/usr/bin/env python3
"""Local entity UI server.

Serves tools/registry_ui.html and provides task + project CRUD endpoints
backed by lib/tasks.py (JSONL) and lib/projects.py.

Usage:
    python tools/server.py          # start server at http://localhost:8787
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_file
import lib.tasks as tasks_lib
import lib.projects as projects_lib
from lib.storage import LocalStorage

UI_PATH = Path(__file__).parent / "registry_ui.html"
DATA_DIR = ROOT / "data"

app = Flask(__name__)


def _storage():
    return LocalStorage(base_dir=str(DATA_DIR))


@app.route("/")
def index():
    return send_file(str(UI_PATH))


# --- Tasks ---

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    project_id = request.args.get("project_id")
    open_tasks = tasks_lib.get_open_tasks(_storage())
    if project_id:
        open_tasks = [t for t in open_tasks if t.get("project_id") == project_id]
    return jsonify(open_tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    body = request.get_json(force=True)
    task = tasks_lib.add_task(
        _storage(),
        title=body["title"],
        source=body.get("source", "ui"),
        due_date=body.get("due_date"),
        metadata=body.get("metadata"),
        project_id=body.get("project_id"),
        collaborators=body.get("collaborators"),
    )
    return jsonify(task), 201


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id: str):
    patch = request.get_json(force=True)
    result = tasks_lib.edit_task(_storage(), task_id, patch)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id: str):
    body = request.get_json(force=True) or {}
    result = tasks_lib.complete_task(_storage(), body.get("match_text", task_id))
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


# --- Projects ---

@app.route("/api/projects", methods=["GET"])
def list_projects():
    status = request.args.get("status", "active")
    return jsonify(projects_lib.list_projects(_storage(), status=status or None))


@app.route("/api/projects", methods=["POST"])
def create_project():
    body = request.get_json(force=True)
    project = projects_lib.add_project(
        _storage(),
        canonical_name=body["canonical_name"],
        aliases=body.get("aliases"),
        members=body.get("members"),
    )
    return jsonify(project), 201


@app.route("/api/projects/<project_id>", methods=["PATCH"])
def update_project(project_id: str):
    updates = request.get_json(force=True)
    result = projects_lib.update_project(_storage(), project_id, updates)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


if __name__ == "__main__":
    print("Entity UI → http://localhost:8787")
    app.run(port=8787, debug=False)
```

- [ ] **Step 3: Smoke-test**

```bash
python tools/server.py &
sleep 1
curl -s http://localhost:8787/api/tasks
curl -s http://localhost:8787/api/projects
kill %1
```
Expected: both return `[]` (or current task/project lists).

- [ ] **Step 4: Commit server**

```bash
git add tools/server.py
git commit -m "feat: local Flask entity UI server wrapping lib/tasks.py + lib/projects.py"
```

### 6b — Projects tab in `tools/registry_ui.html`

Read the existing file to understand the tab switcher and panel pattern before editing. Then add:

1. A **Projects tab button** matching the People tab button's CSS classes exactly.
2. A **Projects tab panel** that fetches from `GET /api/projects` on tab activation (no File System Access API for projects — the server owns that).
3. **Project list view**: name, status badge, member count. Click opens detail.
4. **Project detail view**: canonical name, aliases, members (names resolved from the people registry already in memory), and an open-tasks panel.
5. **Tasks panel per project**: fetches `GET /api/tasks?project_id=<id>`. Shows open tasks with a "Complete" button per task (`POST /api/tasks/<id>/complete`). Shows an "Add task" inline form that `POST`s to `/api/tasks` with `project_id` pre-filled.
6. **Server-offline banner**: if `fetch` to the API fails (server not running), display: *"Start tools/server.py to manage tasks."*

- [ ] **Step 5: Read the existing tab structure**

```bash
grep -n "tab\|panel\|data-tab\|tabContent" tools/registry_ui.html | head -30
```

Use the output to match the exact CSS class and JS pattern before editing.

- [ ] **Step 6: Add Projects tab and panel to `tools/registry_ui.html`**

This is a direct edit — adapt the exact markup and JS patterns from the People tab. Reuse CSS classes; do not introduce new ones unless required for the project-specific layout.

- [ ] **Step 7: Test the UI manually**

```bash
python tools/server.py &
open http://localhost:8787
```

1. Open the People tab — verify it still works without regression.
2. Open the Projects tab — verify it loads (empty if no projects yet).
3. Use the "Add Project" form (or `curl -XPOST /api/projects`) to create a test project.
4. Reload the Projects tab — verify the project appears.
5. Click the project — verify the task panel loads.
6. Add a task via the inline form — verify it appears immediately without page reload.
7. Complete the task — verify it disappears from the open list.
8. Stop the server (`kill %1`) and reload — verify the offline banner appears instead of an error.

- [ ] **Step 8: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: Projects tab with entity-attached task panels in entity UI"
```

---

## Task 7: Brief Integration

**Files:**
- Modify: whichever file assembles the brief sections (confirm by running `grep -n "def.*brief\|BriefContent" processors/brief.py main.py` first)
- Modify: `tests/test_brief.py` or `tests/test_brief_extended.py`

- [ ] **Step 1: Locate the brief assembly function**

```bash
grep -rn "def.*brief\|BriefContent\|sections\|brief_text" processors/brief.py main.py | head -20
```

Find where sections are built and concatenated into the final brief string.

- [ ] **Step 2: Add projects section call**

In the brief assembly function, import and call `project_context_for_brief`:

```python
from lib.projects import project_context_for_brief

project_ctx = project_context_for_brief(storage)
if project_ctx:
    lines = ["## Active Projects\n"]
    for entry in project_ctx:
        p = entry["project"]
        lines.append(f"### {p['canonical_name']}")
        if entry["open_tasks"]:
            lines.append("Open tasks:")
            for t in entry["open_tasks"]:
                lines.append(f"  - {t['title']}")
        if entry["linked_obs"]:
            lines.append(f"Recent calls ({len(entry['linked_obs'])} in last 14 days):")
            for lk in entry["linked_obs"][-3:]:
                lines.append(f"  - {lk['call_title']} ({lk['obs_date']})")
        lines.append("")
    # Insert before the existing tasks section, or append — match local convention
    brief_sections.append("\n".join(lines))
```

- [ ] **Step 3: Run existing brief tests**

```bash
pytest tests/test_brief.py tests/test_brief_extended.py -v
```
Expected: all existing tests PASS. The new section only appears when `project_ctx` is non-empty; fixtures with no projects are unaffected.

- [ ] **Step 4: Add a brief test covering the project section**

In `tests/test_brief.py` (or `test_brief_extended.py`), add:

```python
def test_brief_includes_project_section(tmp_path):
    """Projects with open tasks appear in the brief."""
    from lib.storage import LocalStorage
    from lib.projects import add_project
    from lib.tasks import add_task

    s = LocalStorage(base_dir=str(tmp_path))
    add_project(s, canonical_name="Nicole Campaign")
    add_task(s, "Send outreach deck", project_id="nicole-campaign")

    # Call whatever function produces the brief text and takes a storage arg.
    # Replace `assemble_brief_sections` with the actual function name from Step 1.
    sections = assemble_brief_sections(storage=s, config={})
    combined = "\n".join(sections)
    assert "Nicole Campaign" in combined
    assert "Send outreach deck" in combined
```

Run: `pytest tests/test_brief.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/brief.py tests/test_brief.py
git commit -m "feat: add active-projects section to daily brief"
```

---

## Verification Checklist

After all tasks complete:

```bash
pytest -v --tb=short 2>&1 | tail -20
```
Expected: zero new failures.

Then end-to-end:

1. `python tools/server.py` → open `http://localhost:8787`.
2. People tab: confirm existing behavior unchanged.
3. Projects tab: create a project, add a task, complete it.
4. `python main.py --no-email`: confirm brief runs clean and shows project section if any active projects exist.
5. Confirm `data/tasks.jsonl` exists and `data/tasks.json` is either absent or untouched (migration should not delete the old file).
6. Run `git status` — confirm `data/tasks.jsonl` is the tracked file and `data/tasks.json` can be removed if migration succeeded.
