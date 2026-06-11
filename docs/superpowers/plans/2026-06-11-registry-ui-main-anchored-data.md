# Registry UI — Main-Anchored Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the registry UI treat `origin/main` as the single source of truth for all data (tasks, projects, people, notes, tags) — reading it into memory and writing it back via a worktree — so the working-tree clobber, the read/write race, and the tasks-vs-projects branch split are eliminated.

**Architecture:** A read-only `MainStorage` adapter serves the existing `lib.tasks`/`lib.projects` logic from `git show origin/main:<file>` and buffers writes in memory. A `git_sync` module does the git plumbing (fetch, show, commit-to-main via a throwaway worktree, with union-merge for append-only `.jsonl` files). `tools/server.py` holds one in-memory snapshot rebuilt on page load / Refresh / after each write, serves all GETs from it, and routes all writes through one `_write_main` helper that blocks when `main` is unreachable. The UI gates write actions on connectivity and shows an offline banner.

**Tech Stack:** Python 3.14, Flask 3.1, pytest 8.3, git, vanilla JS (no build step).

> ⚠️ **The manual-verification steps in Tasks 7 and 8 are NOT dry runs.** They start the real server and create/complete/delete real tasks, projects, and notes, which push actual commits to `origin/main` (that is the system's normal behavior — CI consumers read `main`). If you want to verify without writing to `main`, use throwaway records you then delete, or rely on the mocked integration tests (Task 6) which never touch git. The offline-simulation step (Task 7, Step 5) renames the `origin` remote — make sure to restore it.

---

## Spec

Design doc: `docs/superpowers/specs/2026-06-11-registry-ui-main-anchored-data-design.md`

## File Structure

**Create:**
- `lib/git_sync.py` — git plumbing: `fetch_main`, `show_main`, `prune_worktrees`, `commit_files_to_main`, `_union_merge_lines`.
- `lib/main_storage.py` — `MainStorage` adapter (reads from a blob reader, buffers writes).
- `tests/test_git_sync.py` — unit tests for the union-merge helper and subprocess-mocked git calls.
- `tests/test_main_storage.py` — unit tests for the adapter.
- `tests/test_server_data_layer.py` — Flask-test-client integration tests with `git_sync` monkeypatched.

**Modify:**
- `lib/notes.py` — extract `replay_notes_content(content)` from `replay_notes(path)`.
- `tools/server.py` — snapshot + bootstrap/refresh + endpoint rewiring; remove `_sync_tasks_from_main`, `_git_commit_push`, `_git_push_projects`, `_git_push_notes`, `_git_push_tasks`.
- `tools/registry_ui.html` — bootstrap call, offline banner + Refresh button (injected via JS), write-gating in `fetchJSON`.

**Unchanged:** `lib/tasks.py`, `lib/projects.py` (their mutation logic is reused as-is), `lib/storage.py`, all CI consumers, every data-file format.

---

## Task 1: `lib/git_sync.py` — git plumbing

**Files:**
- Create: `lib/git_sync.py`
- Test: `tests/test_git_sync.py`

- [ ] **Step 1: Write the failing test for the union-merge helper**

```python
# tests/test_git_sync.py
from lib.git_sync import _union_merge_lines


def test_union_merge_appends_only_new_lines():
    existing = '{"id":"a"}\n{"id":"b"}\n'
    incoming = '{"id":"a"}\n{"id":"b"}\n{"id":"c"}\n'
    merged = _union_merge_lines(existing, incoming)
    assert merged == '{"id":"a"}\n{"id":"b"}\n{"id":"c"}\n'


def test_union_merge_preserves_concurrent_remote_lines():
    # `existing` simulates origin/main having a line our buffer never saw
    existing = '{"id":"a"}\n{"id":"remote"}\n'
    incoming = '{"id":"a"}\n{"id":"mine"}\n'
    merged = _union_merge_lines(existing, incoming)
    assert merged == '{"id":"a"}\n{"id":"remote"}\n{"id":"mine"}\n'


def test_union_merge_empty_existing():
    assert _union_merge_lines("", '{"id":"a"}\n') == '{"id":"a"}\n'


def test_union_merge_empty_incoming():
    assert _union_merge_lines('{"id":"a"}\n', "") == '{"id":"a"}\n'
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_git_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.git_sync'`

- [ ] **Step 3: Create `lib/git_sync.py` with the helper and the subprocess functions**

```python
# lib/git_sync.py
"""Git plumbing for the registry UI: read/write data files on origin/main.

The UI treats origin/main as the single source of truth. Reads come from the
committed blob (git show); writes land on main via a throwaway worktree, never
touching the user's checked-out branch.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
_TIMEOUT = 8


def _union_merge_lines(existing: str, incoming: str) -> str:
    """Return existing lines plus any incoming lines not already present, order-preserving.

    Used for append-only *.jsonl files so a concurrent writer's lines are never lost.
    """
    existing_lines = [l for l in existing.splitlines() if l.strip()]
    seen = set(existing_lines)
    merged = existing_lines + [l for l in incoming.splitlines() if l.strip() and l not in seen]
    return "\n".join(merged) + ("\n" if merged else "")


def fetch_main(timeout: int = _TIMEOUT) -> bool:
    """Update the local origin/main ref. Return True if reachable, False if offline."""
    try:
        r = subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(REPO_ROOT), capture_output=True, timeout=timeout,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def show_main(repo_rel_path: str) -> Optional[str]:
    """Return the content of repo_rel_path on origin/main, or None if absent/unreadable."""
    try:
        r = subprocess.run(
            ["git", "show", f"origin/main:{repo_rel_path}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def prune_worktrees() -> None:
    """Remove orphaned worktrees left by a hard crash. Best-effort."""
    try:
        subprocess.run(["git", "worktree", "prune"], cwd=str(REPO_ROOT), capture_output=True)
    except OSError:
        pass


def commit_files_to_main(files: dict, msg: str) -> dict:
    """Commit {repo_rel_path: content} to origin/main via a temp worktree, then push.

    *.jsonl files are union-merged with main's current lines (concurrency-safe);
    other files are overwritten. Never touches the checked-out branch.
    """
    if not files:
        return {"status": "ok", "detail": "no changes"}
    repo = str(REPO_ROOT)
    try:
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=repo, check=True, capture_output=True, timeout=_TIMEOUT,
        )
        with tempfile.TemporaryDirectory() as tmp:
            wt = tmp + "/wt"
            subprocess.run(
                ["git", "worktree", "add", "--detach", wt, "origin/main"],
                cwd=repo, check=True, capture_output=True,
            )
            try:
                for rel, content in files.items():
                    target = Path(wt) / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if rel.endswith(".jsonl"):
                        existing = target.read_text() if target.exists() else ""
                        target.write_text(_union_merge_lines(existing, content))
                    else:
                        target.write_text(content)
                subprocess.run(["git", "add"] + list(files.keys()), cwd=wt, check=True, capture_output=True)
                commit = subprocess.run(["git", "commit", "-m", msg], cwd=wt, capture_output=True, text=True)
                if commit.returncode != 0:
                    out = (commit.stdout + commit.stderr).strip()
                    if "nothing to commit" in out:
                        return {"status": "ok", "detail": "already up to date"}
                    return {"status": "commit_failed", "detail": out}
                push = subprocess.run(
                    ["git", "push", "origin", "HEAD:refs/heads/main"],
                    cwd=wt, capture_output=True, text=True,
                )
                if push.returncode != 0:
                    return {"status": "push_failed", "detail": push.stderr.strip()}
            finally:
                subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo, capture_output=True)
        return {"status": "ok", "detail": "committed and pushed to main"}
    except subprocess.TimeoutExpired:
        return {"status": "offline", "detail": "git fetch timed out"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
```

- [ ] **Step 4: Run the union-merge tests to verify they pass**

Run: `python -m pytest tests/test_git_sync.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Add subprocess-mocked tests for fetch_main / show_main**

```python
# append to tests/test_git_sync.py
import subprocess
from unittest.mock import patch
import lib.git_sync as gs


def test_fetch_main_true_on_success():
    with patch("lib.git_sync.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        assert gs.fetch_main() is True


def test_fetch_main_false_on_timeout():
    with patch("lib.git_sync.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 8)):
        assert gs.fetch_main() is False


def test_fetch_main_false_on_nonzero():
    with patch("lib.git_sync.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 128, b"", b"fatal")
        assert gs.fetch_main() is False


def test_show_main_returns_stdout():
    with patch("lib.git_sync.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, '{"id":"a"}\n', "")
        assert gs.show_main("data/tasks.jsonl") == '{"id":"a"}\n'


def test_show_main_none_when_absent():
    with patch("lib.git_sync.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 128, "", "does not exist")
        assert gs.show_main("data/missing.jsonl") is None
```

- [ ] **Step 6: Run all git_sync tests**

Run: `python -m pytest tests/test_git_sync.py -v`
Expected: PASS (9 passed)

- [ ] **Step 7: Commit**

```bash
git add lib/git_sync.py tests/test_git_sync.py
git commit -m "feat(registry-ui): add git_sync plumbing for main-anchored data"
```

---

## Task 2: `lib/main_storage.py` — read-from-main / buffer-writes adapter

**Files:**
- Create: `lib/main_storage.py`
- Test: `tests/test_main_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_main_storage.py
import json
from lib.main_storage import MainStorage


def _store(blobs):
    """blobs: {repo_rel_path: content}. Returns a MainStorage reading from that dict."""
    return MainStorage(read_blob=lambda rel: blobs.get(rel))


def test_read_falls_back_to_blob():
    s = _store({"data/tasks.jsonl": '{"id":"a"}\n'})
    assert s.read("tasks.jsonl") == '{"id":"a"}\n'


def test_read_missing_blob_returns_none():
    assert _store({}).read("tasks.jsonl") is None


def test_write_then_read_uses_buffer():
    s = _store({"data/tasks.jsonl": "old\n"})
    s.write("tasks.jsonl", "new\n")
    assert s.read("tasks.jsonl") == "new\n"


def test_append_line_starts_from_blob():
    s = _store({"data/tasks.jsonl": '{"id":"a"}\n'})
    s.append_line("tasks.jsonl", '{"id":"b"}')
    assert s.read("tasks.jsonl") == '{"id":"a"}\n{"id":"b"}\n'


def test_append_line_on_missing_blob():
    s = _store({})
    s.append_line("notes.jsonl", '{"id":"n"}')
    assert s.read("notes.jsonl") == '{"id":"n"}\n'


def test_exists_reflects_blob_and_buffer():
    s = _store({"data/a.json": "{}"})
    assert s.exists("a.json") is True
    assert s.exists("b.json") is False
    s.write("b.json", "{}")
    assert s.exists("b.json") is True


def test_read_json_and_write_json():
    s = _store({"data/projects_registry.json": json.dumps({"version": 1, "projects": []})})
    data = s.read_json("projects_registry.json")
    assert data == {"version": 1, "projects": []}
    data["projects"].append({"id": "x"})
    s.write_json("projects_registry.json", data)
    assert s.read_json("projects_registry.json")["projects"] == [{"id": "x"}]


def test_read_json_default_on_missing():
    assert _store({}).read_json("x.json", default={"k": 1}) == {"k": 1}


def test_dirty_maps_to_repo_rel_paths():
    s = _store({})
    s.write("tasks.jsonl", "line\n")
    s.write_json("notes_tags.json", [])
    assert s.dirty() == {"data/tasks.jsonl": "line\n", "data/notes_tags.json": "[]"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_main_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.main_storage'`

- [ ] **Step 3: Create `lib/main_storage.py`**

```python
# lib/main_storage.py
"""A storage adapter whose reads come from origin/main and whose writes accumulate
in memory. Lets the existing lib.tasks / lib.projects logic operate against main
without touching the working tree.

- read*/exists: served from the in-memory write buffer if the key was written this
  session, else from read_blob(repo_rel_path) (origin/main).
- write*/append_line: accumulate into the buffer. Call dirty() to get the changed
  files as {repo_rel_path: content} for committing.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


class MainStorage:
    def __init__(self, read_blob: Callable[[str], Optional[str]], data_prefix: str = "data"):
        self._read_blob = read_blob
        self._prefix = data_prefix
        self._buffer: dict = {}   # key (relative to data/) -> content

    def _rel(self, key: str) -> str:
        return f"{self._prefix}/{key}"

    def read(self, key: str) -> Optional[str]:
        if key in self._buffer:
            return self._buffer[key]
        return self._read_blob(self._rel(key))

    def write(self, key: str, content: str) -> None:
        self._buffer[key] = content

    def exists(self, key: str) -> bool:
        return self.read(key) is not None

    def read_json(self, key: str, default: Any = None) -> Any:
        content = self.read(key)
        if content is None:
            return default
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return default

    def write_json(self, key: str, data: Any, indent: int = 2) -> None:
        self.write(key, json.dumps(data, indent=indent))

    def append_line(self, key: str, line: str) -> None:
        existing = self.read(key) or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        self.write(key, existing + line + "\n")

    def dirty(self) -> dict:
        """Return {repo_rel_path: content} for every file written this session."""
        return {self._rel(k): v for k, v in self._buffer.items()}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_main_storage.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Verify the existing task logic works against MainStorage (integration sanity)**

```python
# append to tests/test_main_storage.py
import lib.tasks as tasks_lib
import lib.projects as projects_lib


def test_add_task_against_main_storage():
    s = _store({"data/tasks.jsonl": '{"event":"create","task_id":"t-aaa","title":"old","source":"slack","created_at":"2026-01-01","due_date":null,"metadata":{},"project_id":null,"collaborators":[],"owner":null}\n'})
    task = tasks_lib.add_task(s, "new task", source="ui")
    # buffer should now contain the original line plus the new create event
    content = s.read("tasks.jsonl")
    assert '"title": "new task"' in content
    assert "t-aaa" in content  # original preserved
    assert "data/tasks.jsonl" in s.dirty()
    # open tasks replays both
    open_titles = {t["title"] for t in tasks_lib.get_open_tasks(s)}
    assert {"old", "new task"} <= open_titles


def test_add_project_against_main_storage():
    s = _store({"data/projects_registry.json": json.dumps({"version": 1, "projects": []})})
    proj = projects_lib.add_project(s, "Test Project")
    assert proj["id"] == "test-project"
    assert s.dirty() == {"data/projects_registry.json": json.dumps({"version": 1, "projects": [proj]}, indent=2)}
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/test_main_storage.py -v`
Expected: PASS (11 passed)

- [ ] **Step 7: Commit**

```bash
git add lib/main_storage.py tests/test_main_storage.py
git commit -m "feat(registry-ui): add MainStorage adapter (read from main, buffer writes)"
```

---

## Task 3: `lib/notes.py` — content-based replay

**Files:**
- Modify: `lib/notes.py:10-60`
- Test: `tests/test_notes_replay.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notes_replay.py
from pathlib import Path
from lib.notes import replay_notes, replay_notes_content


def test_replay_notes_content_create_and_update():
    content = (
        '{"event":"create","id":"n-1","ts":"2026-06-10T10:00:00","body":"first","tags":["X"]}\n'
        '{"event":"update","id":"n-1","ts":"2026-06-10T11:00:00","body":"edited"}\n'
    )
    notes = replay_notes_content(content)
    assert len(notes) == 1
    assert notes[0]["body"] == "edited"
    assert notes[0]["tags"] == ["X"]


def test_replay_notes_content_delete():
    content = (
        '{"event":"create","id":"n-1","ts":"2026-06-10T10:00:00","body":"x"}\n'
        '{"event":"delete","id":"n-1","ts":"2026-06-10T11:00:00"}\n'
    )
    assert replay_notes_content(content) == []


def test_replay_notes_content_empty():
    assert replay_notes_content("") == []


def test_replay_notes_path_delegates(tmp_path):
    p = Path(tmp_path) / "notes.jsonl"
    p.write_text('{"event":"create","id":"n-1","ts":"2026-06-10T10:00:00","body":"hi"}\n')
    assert replay_notes(p) == replay_notes_content(p.read_text())
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_notes_replay.py -v`
Expected: FAIL — `ImportError: cannot import name 'replay_notes_content'`

- [ ] **Step 3: Refactor `lib/notes.py` — extract content-based replay**

Replace the existing `replay_notes` function (lines 10-60) with:

```python
def replay_notes(path: Path) -> list[dict]:
    """Replay notes.jsonl events from a file and return current state (see replay_notes_content)."""
    if not path.exists():
        return []
    return replay_notes_content(path.read_text())


def replay_notes_content(content: str) -> list[dict]:
    """Replay notes events from raw JSONL content and return current state for every
    non-deleted note.

    Each returned note includes a derived `brief_flagged_date` field (ISO date string
    or None): the calendar date of the most recent event that set brief=True.
    """
    notes: dict[str, dict] = {}
    brief_flagged_dates: dict[str, str] = {}
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nid = ev["id"]
        etype = ev["event"]
        if etype == "create":
            notes[nid] = {
                "id": nid,
                "ts": ev["ts"],
                "body": ev["body"],
                "tags": ev.get("tags", []),
                "person_id": ev.get("person_id"),
                "task_id": ev.get("task_id"),
                "brief": ev.get("brief", False),
                "pinned": ev.get("pinned", False),
            }
            if ev.get("brief"):
                brief_flagged_dates[nid] = ev["ts"][:10]
        elif etype == "update" and nid in notes:
            patch = {k: v for k, v in ev.items() if k not in ("event", "id", "ts")}
            notes[nid].update(patch)
            if ev.get("brief") is True:
                brief_flagged_dates[nid] = ev["ts"][:10]
            elif ev.get("brief") is False:
                brief_flagged_dates.pop(nid, None)
        elif etype == "pin" and nid in notes:
            notes[nid]["pinned"] = ev.get("pinned", True)
        elif etype == "delete":
            notes.pop(nid, None)
            brief_flagged_dates.pop(nid, None)
    result = []
    for nid, note in notes.items():
        n = dict(note)
        n["brief_flagged_date"] = brief_flagged_dates.get(nid)
        result.append(n)
    return result
```

- [ ] **Step 4: Run new + existing notes tests to verify pass**

Run: `python -m pytest tests/test_notes_replay.py tests/test_notes_lib.py -v`
Expected: PASS (existing `test_notes_lib.py` still green — `replay_notes` behavior unchanged)

- [ ] **Step 5: Commit**

```bash
git add lib/notes.py tests/test_notes_replay.py
git commit -m "refactor(notes): extract replay_notes_content for content-based replay"
```

---

## Task 4: `tools/server.py` — snapshot, bootstrap/refresh, remove old sync

**Files:**
- Modify: `tools/server.py:10-73` (imports, helpers, index, add snapshot)

- [ ] **Step 1: Replace the imports + module-level helpers block**

Replace lines 10-73 (from `import json` through the end of the `index()` function) with:

```python
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_file
import lib.tasks as tasks_lib
import lib.projects as projects_lib
import lib.git_sync as git_sync
from lib.main_storage import MainStorage
from lib.notes import replay_notes_content

UI_PATH = Path(__file__).parent / "registry_ui.html"

app = Flask(__name__)


# --- Snapshot of origin/main (the single source of truth) ---

class _Snapshot:
    def __init__(self):
        self.online = False
        self.fetched_at = None
        self.tasks = []
        self.projects = []
        self.people = {"people": []}
        self.notes = []
        self.tags = []


SNAPSHOT = _Snapshot()


def _read_store() -> MainStorage:
    """A MainStorage that reads from origin/main (current local ref)."""
    return MainStorage(read_blob=git_sync.show_main)


def rebuild_snapshot(known_online=None) -> None:
    """Re-read every dataset from origin/main into SNAPSHOT.

    If known_online is None, fetch origin/main first (the fetch result is the
    connectivity signal). Pass True to skip the fetch (e.g. right after a write
    that already updated the ref).
    """
    online = git_sync.fetch_main() if known_online is None else known_online
    store = _read_store()
    SNAPSHOT.tasks = tasks_lib.get_open_tasks(store)
    SNAPSHOT.projects = projects_lib.list_projects(store, status=None)
    SNAPSHOT.people = store.read_json("people_registry.json", default={"people": []})
    SNAPSHOT.notes = replay_notes_content(store.read("notes.jsonl") or "")
    SNAPSHOT.tags = store.read_json("notes_tags.json", default=[])
    SNAPSHOT.online = online
    SNAPSHOT.fetched_at = datetime.now(timezone.utc).isoformat()


def _write_main(mutate, msg_fn):
    """Apply mutate(store) against origin/main and commit the result.

    Returns (result, push, http_status). When main is unreachable, returns
    (None, {"status":"offline"}, 503) WITHOUT attempting any commit.
    msg_fn is a commit message string, or a callable taking the mutate result.
    """
    if not git_sync.fetch_main():
        return None, {"status": "offline", "detail": "cannot reach main"}, 503
    store = _read_store()
    result = mutate(store)
    msg = msg_fn(result) if callable(msg_fn) else msg_fn
    push = git_sync.commit_files_to_main(store.dirty(), msg)
    if push.get("status") == "ok":
        rebuild_snapshot(known_online=True)
    return result, push, 200


def _people_list():
    return [
        {"id": p["id"], "name": p.get("canonical_name", p["id"])}
        for p in SNAPSHOT.people.get("people", [])
    ]


@app.route("/")
def index():
    return send_file(str(UI_PATH))


@app.route("/api/bootstrap", methods=["GET"])
@app.route("/api/refresh", methods=["POST"])
def bootstrap():
    rebuild_snapshot()
    return jsonify({
        "online": SNAPSHOT.online,
        "fetched_at": SNAPSHOT.fetched_at,
        "tasks": SNAPSHOT.tasks,
        "projects": SNAPSHOT.projects,
        "people": _people_list(),
        "notes": SNAPSHOT.notes,
        "tags": SNAPSHOT.tags,
    })
```

> Note: this removes `_storage`, `_git_push_notes`, `_sync_tasks_from_main`, the `threading`/`shutil`/`tempfile`/`subprocess` imports, and `NOTES_JSONL`/`NOTES_TAGS_JSON` module constants. They are no longer referenced after Tasks 5–6. The functions `_git_commit_push`, `_git_push_projects`, `_git_push_tasks` (lines 134-217) are removed in Task 5.

- [ ] **Step 2: Verify the server still imports (it will error on now-undefined names until Task 5; just check the new block parses)**

Run: `python -c "import ast; ast.parse(open('tools/server.py').read()); print('parses')"`
Expected: `parses`

- [ ] **Step 3: Commit (work-in-progress checkpoint)**

```bash
git add tools/server.py
git commit -m "feat(registry-ui): add main snapshot + bootstrap/refresh; remove working-tree sync"
```

---

## Task 5: `tools/server.py` — rewire all write + read endpoints

**Files:**
- Modify: `tools/server.py` (tasks/projects/notes/tags/people endpoints + delete the old git helpers)

- [ ] **Step 1: Delete the three obsolete git helpers**

Delete `_git_commit_push` (lines 134-153), `_git_push_projects` (156-157), and `_git_push_tasks` (160-217) entirely. They are replaced by `git_sync` + `_write_main`.

- [ ] **Step 2: Replace the Tasks endpoints**

Replace the tasks block with:

```python
# --- Tasks ---

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    project_id = request.args.get("project_id")
    tasks = SNAPSHOT.tasks
    if project_id:
        tasks = [t for t in tasks if t.get("project_id") == project_id]
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    body = request.get_json(force=True)
    if not body or not body.get("title"):
        return jsonify({"error": "title is required"}), 400

    def mutate(store):
        return tasks_lib.add_task(
            store,
            title=body["title"],
            source=body.get("source", "ui"),
            due_date=body.get("due_date"),
            metadata=body.get("metadata"),
            project_id=body.get("project_id"),
            collaborators=body.get("collaborators"),
            owner=body.get("owner"),
        )

    task, push, status = _write_main(mutate, lambda t: f"data: create task {t['id']}")
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    return jsonify({"task": task, "push": push}), 201


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id: str):
    patch = request.get_json(force=True)
    task, push, status = _write_main(
        lambda store: tasks_lib.edit_task(store, task_id, patch),
        f"data: update task {task_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": task, "push": push})


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id: str):
    task, push, status = _write_main(
        lambda store: tasks_lib.complete_task_by_id(store, task_id),
        f"data: complete task {task_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": task, "push": push})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id: str):
    task, push, status = _write_main(
        lambda store: tasks_lib.delete_task_by_id(store, task_id),
        f"data: delete task {task_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": task, "push": push})
```

- [ ] **Step 3: Replace the Projects endpoints**

```python
# --- Projects ---

@app.route("/api/projects", methods=["GET"])
def list_projects():
    status = request.args.get("status", "active")
    projects = SNAPSHOT.projects
    if status:
        projects = [p for p in projects if p.get("status") == status]
    return jsonify(projects)


@app.route("/api/projects", methods=["POST"])
def create_project():
    body = request.get_json(force=True)
    if not body or not body.get("canonical_name"):
        return jsonify({"error": "canonical_name is required"}), 400

    def mutate(store):
        return projects_lib.add_project(
            store,
            canonical_name=body["canonical_name"],
            aliases=body.get("aliases"),
            members=body.get("members"),
        )

    project, push, status = _write_main(mutate, lambda p: f"data: add project '{p['canonical_name']}'")
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    return jsonify({"project": project, "push": push}), 201


@app.route("/api/projects/<project_id>", methods=["PATCH"])
def update_project(project_id: str):
    updates = request.get_json(force=True)
    project, push, status = _write_main(
        lambda store: projects_lib.update_project(store, project_id, updates),
        f"data: update project {project_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if project is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(project)


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id: str):
    def mutate(store):
        open_tasks = tasks_lib.get_open_tasks(store)
        proj_tasks = [t for t in open_tasks if t.get("project_id") == project_id]
        for t in proj_tasks:
            tasks_lib.delete_task_by_id(store, t["id"])
        deleted = projects_lib.delete_project(store, project_id)
        if not deleted:
            return None
        return {"project_id": project_id, "tasks_deleted": len(proj_tasks)}

    result, push, status = _write_main(mutate, f"data: delete project {project_id}")
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": project_id, "tasks_deleted": result["tasks_deleted"], "push": push})
```

- [ ] **Step 4: Replace the People endpoints**

```python
# --- People ---

@app.route("/api/people", methods=["GET"])
def list_people():
    return jsonify(_people_list())


@app.route("/api/registry", methods=["GET"])
def get_registry():
    return jsonify(SNAPSHOT.people)
```

- [ ] **Step 5: Replace the Notes endpoints**

```python
# --- Notes ---

@app.route("/api/notes", methods=["GET"])
def list_notes():
    return jsonify(SNAPSHOT.notes)


@app.route("/api/notes", methods=["POST"])
def create_note():
    body = request.get_json(force=True)
    if not body or not body.get("body"):
        return jsonify({"error": "body is required"}), 400
    note_id = "n-" + secrets.token_hex(3)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ev = {
        "event": "create", "id": note_id, "ts": ts,
        "body": body["body"], "tags": body.get("tags", []),
        "person_id": body.get("person_id"), "task_id": body.get("task_id"),
        "brief": body.get("brief", False), "pinned": body.get("pinned", False),
    }
    _, push, status = _write_main(
        lambda store: store.append_line("notes.jsonl", json.dumps(ev)),
        f"data: create note {note_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    note_out = {**ev, "brief_flagged_date": ts[:10] if ev["brief"] else None}
    return jsonify({"note": note_out, "push": push}), 201


@app.route("/api/notes/<note_id>", methods=["PATCH"])
def patch_note(note_id: str):
    body = request.get_json(force=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    event_type = body.pop("event_type", "update")
    if event_type == "pin":
        ev = {"event": "pin", "id": note_id, "ts": ts, "pinned": body.get("pinned", True)}
    else:
        ev = {"event": "update", "id": note_id, "ts": ts,
              **{k: v for k, v in body.items() if k not in ("event", "id", "ts")}}

    def mutate(store):
        notes = replay_notes_content(store.read("notes.jsonl") or "")
        if not any(n["id"] == note_id for n in notes):
            return None
        store.append_line("notes.jsonl", json.dumps(ev))
        updated = replay_notes_content(store.read("notes.jsonl"))
        return next(n for n in updated if n["id"] == note_id)

    note, push, status = _write_main(mutate, f"data: update note {note_id}")
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if note is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"note": note, "push": push})


@app.route("/api/notes/<note_id>", methods=["DELETE"])
def delete_note(note_id: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def mutate(store):
        notes = replay_notes_content(store.read("notes.jsonl") or "")
        if not any(n["id"] == note_id for n in notes):
            return None
        store.append_line("notes.jsonl", json.dumps({"event": "delete", "id": note_id, "ts": ts}))
        return note_id

    result, push, status = _write_main(mutate, f"data: delete note {note_id}")
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": note_id, "push": push})
```

- [ ] **Step 6: Replace the Notes Tags endpoints**

```python
# --- Notes Tags ---

@app.route("/api/notes/tags", methods=["GET"])
def list_note_tags():
    return jsonify(SNAPSHOT.tags)


@app.route("/api/notes/tags", methods=["POST"])
def create_note_tag():
    body = request.get_json(force=True)
    if not body or not body.get("id"):
        return jsonify({"error": "id is required"}), 400
    tag_id = body["id"].upper().replace(" ", "_")
    tag = {"id": tag_id, "color": body.get("color", "#555555")}

    def mutate(store):
        tags = store.read_json("notes_tags.json", default=[])
        if any(t["id"] == tag_id for t in tags):
            return "exists"
        tags.append(tag)
        store.write_json("notes_tags.json", tags)
        return tag

    result, push, status = _write_main(mutate, f"data: create tag {tag_id}")
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if result == "exists":
        return jsonify({"error": "tag already exists"}), 409
    return jsonify({"tag": result}), 201


@app.route("/api/notes/tags/<tag_id>", methods=["PATCH"])
def update_note_tag(tag_id: str):
    body = request.get_json(force=True)
    new_id = body.get("id", tag_id).upper().replace(" ", "_")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def mutate(store):
        tags = store.read_json("notes_tags.json", default=[])
        tag = next((t for t in tags if t["id"] == tag_id), None)
        if tag is None:
            return None
        new_color = body.get("color", tag.get("color", "#555555"))
        for t in tags:
            if t["id"] == tag_id:
                t["id"] = new_id
                t["color"] = new_color
        store.write_json("notes_tags.json", tags)
        if new_id != tag_id:
            affected = [n for n in replay_notes_content(store.read("notes.jsonl") or "")
                        if tag_id in n.get("tags", [])]
            for note in affected:
                new_tags = [new_id if x == tag_id else x for x in note["tags"]]
                store.append_line("notes.jsonl", json.dumps(
                    {"event": "update", "id": note["id"], "ts": ts, "tags": new_tags}))
        return {"id": new_id, "color": new_color}

    result, push, status = _write_main(mutate, f"data: rename tag {tag_id} -> {new_id}")
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"tag": result})


@app.route("/api/notes/tags/<tag_id>", methods=["DELETE"])
def delete_note_tag(tag_id: str):
    def mutate(store):
        tags = store.read_json("notes_tags.json", default=[])
        new_tags = [t for t in tags if t["id"] != tag_id]
        if len(new_tags) == len(tags):
            return None
        store.write_json("notes_tags.json", new_tags)
        return tag_id

    result, push, status = _write_main(mutate, f"data: delete tag {tag_id}")
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": tag_id, "push": push})
```

- [ ] **Step 7: Update the `__main__` block to prune worktrees + build the first snapshot**

Replace the `if __name__ == "__main__":` block with:

```python
if __name__ == "__main__":
    git_sync.prune_worktrees()
    rebuild_snapshot()
    print("Entity UI → http://localhost:8787")
    app.run(port=8787, debug=False, threaded=True)
```

- [ ] **Step 8: Verify the file parses and has no dangling references**

Run: `python -c "import ast; ast.parse(open('tools/server.py').read()); print('parses')"`
Expected: `parses`

Run: `grep -nE "_storage|_git_commit_push|_git_push_tasks|_git_push_projects|_git_push_notes|_sync_tasks_from_main|NOTES_JSONL|NOTES_TAGS_JSON|_replay_notes_lib" tools/server.py`
Expected: no output (all removed)

- [ ] **Step 9: Commit**

```bash
git add tools/server.py
git commit -m "feat(registry-ui): route all reads/writes through origin/main snapshot"
```

---

## Task 6: Server integration tests (mocked git_sync)

**Files:**
- Test: `tests/test_server_data_layer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server_data_layer.py
import json
import pytest
import tools.server as server


@pytest.fixture
def client(monkeypatch):
    # In-memory fake of origin/main: {repo_rel_path: content}
    main = {
        "data/tasks.jsonl": "",
        "data/projects_registry.json": json.dumps({"version": 1, "projects": []}),
        "data/people_registry.json": json.dumps({"people": [{"id": "trent-luecke", "canonical_name": "Trent Luecke"}]}),
        "data/notes.jsonl": "",
        "data/notes_tags.json": "[]",
    }
    committed = []

    monkeypatch.setattr(server.git_sync, "fetch_main", lambda *a, **k: True)
    monkeypatch.setattr(server.git_sync, "show_main", lambda rel: main.get(rel))

    def fake_commit(files, msg):
        # apply union-merge for jsonl, overwrite otherwise — mirrors real behavior
        for rel, content in files.items():
            if rel.endswith(".jsonl"):
                existing = main.get(rel, "")
                seen = set(l for l in existing.splitlines() if l.strip())
                merged = [l for l in existing.splitlines() if l.strip()]
                merged += [l for l in content.splitlines() if l.strip() and l not in seen]
                main[rel] = "\n".join(merged) + ("\n" if merged else "")
            else:
                main[rel] = content
        committed.append(msg)
        return {"status": "ok", "detail": "committed and pushed to main"}

    monkeypatch.setattr(server.git_sync, "commit_files_to_main", fake_commit)
    server.rebuild_snapshot()
    c = server.app.test_client()
    c._main = main
    c._committed = committed
    return c


def test_bootstrap_reports_online_and_people(client):
    r = client.get("/api/bootstrap")
    body = r.get_json()
    assert body["online"] is True
    assert body["people"] == [{"id": "trent-luecke", "name": "Trent Luecke"}]


def test_create_task_commits_to_main_and_appears(client):
    r = client.post("/api/tasks", json={"title": "Ship it", "owner": "trent-luecke"})
    assert r.status_code == 201
    assert "Ship it" in client._main["data/tasks.jsonl"]
    # snapshot rebuilt → GET reflects it
    tasks = client.get("/api/tasks").get_json()
    assert any(t["title"] == "Ship it" for t in tasks)


def test_create_task_offline_returns_503_no_commit(client, monkeypatch):
    monkeypatch.setattr(server.git_sync, "fetch_main", lambda *a, **k: False)
    before = client._main["data/tasks.jsonl"]
    r = client.post("/api/tasks", json={"title": "nope"})
    assert r.status_code == 503
    assert client._main["data/tasks.jsonl"] == before  # nothing committed


def test_delete_project_cascades_tasks_in_one_commit(client):
    client.post("/api/projects", json={"canonical_name": "Temp Proj"})
    pid = client.get("/api/projects").get_json()[0]["id"]
    client.post("/api/tasks", json={"title": "child", "project_id": pid})
    n_commits_before = len(client._committed)
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    assert r.get_json()["tasks_deleted"] == 1
    # exactly one new commit covered both the task deletion and the project removal
    assert len(client._committed) == n_commits_before + 1


def test_create_note_and_list(client):
    client.post("/api/notes", json={"body": "remember this", "tags": []})
    notes = client.get("/api/notes").get_json()
    assert any(n["body"] == "remember this" for n in notes)
```

- [ ] **Step 2: Run to verify they pass**

Run: `python -m pytest tests/test_server_data_layer.py -v`
Expected: PASS (5 passed)

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `python -m pytest tests/ -q`
Expected: all pass (existing task/project/notes tests still green)

- [ ] **Step 4: Commit**

```bash
git add tests/test_server_data_layer.py
git commit -m "test(registry-ui): integration tests for main-anchored data layer"
```

---

## Task 7: `tools/registry_ui.html` — bootstrap, offline banner, Refresh button, write-gate

**Files:**
- Modify: `tools/registry_ui.html` — `fetchJSON` (line 1710), `init` (line 2361)

- [ ] **Step 1: Add connectivity chrome + state helpers**

Immediately **before** the `async function fetchJSON(url, opts = {})` definition (line 1710), insert:

```javascript
// --- Connectivity state (main is the single source of truth) ---
if (typeof state !== 'undefined') { state.online = (typeof state.online === 'boolean') ? state.online : true; }

function ensureConnectivityChrome() {
  if (document.getElementById('conn-chrome')) return;
  const bar = document.createElement('div');
  bar.id = 'conn-chrome';
  bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;display:flex;'
    + 'align-items:center;gap:12px;padding:6px 12px;font:13px system-ui;'
    + 'background:#b00020;color:#fff;transform:translateY(-100%);transition:transform .2s;';
  const msg = document.createElement('span');
  msg.id = 'conn-msg';
  msg.textContent = '⚠ Offline — can’t reach main. Showing last-known data; editing disabled.';
  const btn = document.createElement('button');
  btn.id = 'conn-refresh';
  btn.textContent = '↻ Refresh';
  btn.style.cssText = 'margin-left:auto;cursor:pointer;padding:2px 10px;border-radius:4px;'
    + 'border:1px solid #fff;background:transparent;color:#fff;';
  btn.onclick = () => refreshFromMain();
  bar.appendChild(msg);
  bar.appendChild(btn);
  document.body.appendChild(bar);
}

function applyOnlineState() {
  ensureConnectivityChrome();
  const bar = document.getElementById('conn-chrome');
  const offline = state.online === false;
  document.body.classList.toggle('offline', offline);
  bar.style.transform = offline ? 'translateY(0)' : 'translateY(-100%)';
}

async function refreshFromMain() {
  try {
    const boot = await fetch(`${API}/api/refresh`, { method: 'POST' }).then(r => r.json());
    state.online = boot.online;
  } catch (e) {
    state.online = false;
  }
  applyOnlineState();
  if (typeof rerenderCurrentView === 'function') {
    rerenderCurrentView();
  } else {
    location.reload();
  }
}
```

> The `rerenderCurrentView` reference falls back to `location.reload()` if no such function exists, so this works regardless of the existing view-routing internals.

- [ ] **Step 2: Add the write-gate to `fetchJSON`**

Replace the body of `fetchJSON` (lines 1710-1712, the function up to its first `const res = await fetch(...)`) so it begins:

```javascript
async function fetchJSON(url, opts = {}) {
  const method = (opts.method || 'GET').toUpperCase();
  if (method !== 'GET' && typeof state !== 'undefined' && state.online === false) {
    applyOnlineState();
    throw new Error('offline: editing disabled until main is reachable');
  }
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (res.status === 503) {
    if (typeof state !== 'undefined') { state.online = false; }
    applyOnlineState();
    throw new Error('offline: write rejected by server');
  }
```

(Keep the rest of the original `fetchJSON` body — the existing `if (!res.ok)` handling and `return res.json()` — unchanged below this point.)

- [ ] **Step 3: Bootstrap on startup inside `init()`**

At the very start of `async function init()` (line 2361), immediately after the opening brace, insert:

```javascript
  try {
    const boot = await fetch(`${API}/api/bootstrap`).then(r => r.json());
    state.online = boot.online;
  } catch (e) {
    state.online = false;
  }
  applyOnlineState();
```

- [ ] **Step 4: Manual verification — online path**

> ⚠️ This step pushes real commits to `origin/main`. Use a throwaway task you delete afterward if you don't want it to persist.

Run:
```bash
pkill -f "tools/server.py" 2>/dev/null; sleep 1
python3 tools/server.py &
sleep 2 && open http://localhost:8787
```
Expected: page loads with no red banner; create a task → it appears; confirm it landed on main:
```bash
git fetch origin main -q && git show origin/main:data/tasks.jsonl | tail -1
```
Expected: the new task's create event is the last line.

- [ ] **Step 5: Manual verification — offline path**

With the server running, simulate offline by temporarily breaking the remote:
```bash
git remote rename origin origin_bak
```
Click **↻ Refresh** in the UI. Expected: red banner appears; attempting to create/complete/delete a task shows it's blocked (no change, console shows the `offline:` error). Restore:
```bash
git remote rename origin_bak origin
```
Click **↻ Refresh** again. Expected: banner disappears; editing works.

- [ ] **Step 6: Confirm the working tree is never mutated by viewing the UI**

Run (with server running, after several page loads/refreshes):
```bash
git status --porcelain data/
```
Expected: no output for `data/tasks.jsonl` / `data/notes.jsonl` / `data/projects_registry.json` caused by the UI (the UI no longer checks out `origin/main` over the working tree).

- [ ] **Step 7: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(registry-ui): bootstrap from main, offline banner + Refresh, write-gating"
```

---

## Task 8: Final verification

- [ ] **Step 1: Full test suite**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 2: End-to-end smoke across all three entity types**

With the server running and online:
1. Create + complete + delete a task.
2. Create a project, attach a task, delete the project (confirm cascade).
3. Create + edit + delete a note; create + rename + delete a tag.

After each, verify on main:
```bash
git fetch origin main -q
git show origin/main:data/tasks.jsonl | tail -3
git show origin/main:data/projects_registry.json
git show origin/main:data/notes.jsonl | tail -3
git show origin/main:data/notes_tags.json
```
Expected: each change is present on `origin/main`; the local working tree shows no UI-caused modifications (`git status --porcelain data/`).

- [ ] **Step 3: Confirm no orphaned worktrees**

Run: `git worktree list`
Expected: only the main checkout (no leftover temp worktrees).

---

## Self-Review Notes

- **Spec coverage:** read path → Task 4 (`rebuild_snapshot`, `/api/bootstrap`); write path → Task 5 (`_write_main` + `git_sync.commit_files_to_main`); union-merge for jsonl → Task 1; read-modify-write for JSON → MainStorage + Task 5 mutate closures; connectivity gating/block-when-offline → Task 5 (503) + Task 7 (banner, fetchJSON gate); remove working-tree checkout → Task 4 (`index()` no longer spawns the sync thread); worktree prune on startup → Task 5 Step 7; testing → Tasks 1,2,3,6,7,8.
- **Placeholder scan:** none — all code blocks are complete.
- **Type consistency:** `MainStorage.dirty()` returns `{repo_rel_path: content}`, consumed by `git_sync.commit_files_to_main(files, msg)`; `_write_main` returns `(result, push, status)` consistently across all endpoints; `rebuild_snapshot(known_online=None)` signature matches both call sites (`bootstrap` with default, post-write with `True`).
