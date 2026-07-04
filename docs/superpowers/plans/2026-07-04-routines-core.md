# Routines Core Implementation Plan (Phase 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Named batches of task templates ("routines") stored in `data/routines.json`, manageable and runnable from the Registry UI; running one appends ordinary tagged task events, and the UI groups a run's tasks visually.

**Architecture:** `lib/routines.py` mirrors `lib/projects.py` (a JSON registry file with slug IDs, loaded/saved through the storage abstraction). `tools/server.py` exposes CRUD + a run endpoint that appends `create` events to `tasks.jsonl` via the existing `_write_main` origin/main commit path. The UI adds a Routines section to the Work tab and groups standalone tasks sharing a `metadata.routine_run`.

**Tech Stack:** Python 3.11 (Flask, pytest), vanilla JS in `tools/registry_ui.html`.

**Spec:** `docs/superpowers/specs/2026-07-04-task-horizon-routines-design.md` (Feature 2, excluding "Triggered routines" and "`/routine` Slack command" — those are Phase 3).

## Global Constraints

- Routine shape (exact): `{"id", "name", "steps": [{"title": str}, ...], "trigger": null | {"type": "calendar_ooo", "lead_days": int}, "created": "YYYY-MM-DD", "runs": [{"date": "YYYY-MM-DD", "trigger_key": str|null, "source": str}, ...]}`. File shape: `{"version": 1, "routines": [...]}` at `data/routines.json`.
- Running a routine appends one ordinary `create` event per step to `tasks.jsonl` with `source="routine"`, `metadata={"routine": "<id>", "routine_run": "<YYYY-MM-DD>"}` — created tasks are regular tasks afterward (completable, editable, horizon-able). No new event types.
- Duplicate-run guard: running a routine that already ran within the last 7 days requires explicit confirmation (HTTP 409 from the server unless `force: true`; UI `confirm()` then retries with force). Still allowed — never hard-blocked.
- Phase 3 fields are stored but inert: `trigger` and `runs[].trigger_key` are persisted now; nothing reads them yet.
- No changes to Telegram (`processors/query_tools.py`, `processors/query.py`), the brief, or Slack in this phase.
- Work on branch `feat/routines-core` off fresh `origin/main`. Never hand-edit `data/*` files.
- Run tests with `python3 -m pytest tests/<file> -v` from the repo root.

---

### Task 1: `lib/routines.py` — registry CRUD

**Files:**
- Create: `lib/routines.py`
- Modify: `.gitignore` (allow-list `data/routines.json`, after the `!data/notes.jsonl` line)
- Test: `tests/test_routines.py` (new)

**Interfaces:**
- Produces: `list_routines(storage) -> list`; `get_routine(storage, routine_id) -> Optional[dict]`; `add_routine(storage, name: str, steps: list, trigger: Optional[dict] = None) -> dict` (steps items may be strings or `{"title": ...}` dicts — normalized to `[{"title": str}]`, empty/whitespace titles dropped); `update_routine(storage, routine_id, updates: dict) -> Optional[dict]` (only `name`/`steps`/`trigger` applied, steps normalized; `id`/`created`/`runs` never overwritten); `delete_routine(storage, routine_id) -> bool`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_routines.py`:

```python
# tests/test_routines.py
import pytest
from lib.storage import LocalStorage
from lib.routines import (
    add_routine, get_routine, list_routines,
    update_routine, delete_routine,
)


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


# --- CRUD ---

def test_add_routine_minimal(tmp_path):
    r = add_routine(_s(tmp_path), name="Out of Office Prep",
                    steps=["Cancel meetings", "Set OOO responder"])
    assert r["id"] == "out-of-office-prep"
    assert r["name"] == "Out of Office Prep"
    assert r["steps"] == [{"title": "Cancel meetings"}, {"title": "Set OOO responder"}]
    assert r["trigger"] is None
    assert r["runs"] == []
    assert r["created"]


def test_add_routine_normalizes_dict_steps_and_drops_blanks(tmp_path):
    r = add_routine(_s(tmp_path), name="R",
                    steps=[{"title": "Keep"}, "", "  ", "Also keep"])
    assert r["steps"] == [{"title": "Keep"}, {"title": "Also keep"}]


def test_add_routine_with_trigger(tmp_path):
    r = add_routine(_s(tmp_path), name="OOO",
                    steps=["x"], trigger={"type": "calendar_ooo", "lead_days": 7})
    assert r["trigger"] == {"type": "calendar_ooo", "lead_days": 7}


def test_add_routine_unique_slug(tmp_path):
    s = _s(tmp_path)
    add_routine(s, name="Weekly Review", steps=["a"])
    r2 = add_routine(s, name="Weekly Review", steps=["b"])
    assert r2["id"] == "weekly-review-2"


def test_list_and_get(tmp_path):
    s = _s(tmp_path)
    assert list_routines(s) == []
    r = add_routine(s, name="R", steps=["a"])
    assert [x["id"] for x in list_routines(s)] == [r["id"]]
    assert get_routine(s, r["id"])["name"] == "R"
    assert get_routine(s, "nope") is None


def test_update_routine(tmp_path):
    s = _s(tmp_path)
    r = add_routine(s, name="R", steps=["a"])
    out = update_routine(s, r["id"], {"name": "R2", "steps": ["x", "y"],
                                      "trigger": {"type": "calendar_ooo", "lead_days": 3}})
    assert out["name"] == "R2"
    assert out["steps"] == [{"title": "x"}, {"title": "y"}]
    assert out["trigger"]["lead_days"] == 3
    # persisted
    assert get_routine(s, r["id"])["name"] == "R2"


def test_update_routine_protects_id_created_runs(tmp_path):
    s = _s(tmp_path)
    r = add_routine(s, name="R", steps=["a"])
    out = update_routine(s, r["id"], {"id": "hax", "created": "1999-01-01", "runs": ["bogus"]})
    assert out["id"] == r["id"]
    assert out["created"] == r["created"]
    assert out["runs"] == []


def test_update_routine_missing_returns_none(tmp_path):
    assert update_routine(_s(tmp_path), "nope", {"name": "x"}) is None


def test_delete_routine(tmp_path):
    s = _s(tmp_path)
    r = add_routine(s, name="R", steps=["a"])
    assert delete_routine(s, r["id"]) is True
    assert list_routines(s) == []
    assert delete_routine(s, r["id"]) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_routines.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.routines'`

- [ ] **Step 3: Implement `lib/routines.py`**

```python
# lib/routines.py
import re
from datetime import date, timedelta
from typing import Optional

_ROUTINES_KEY = "routines.json"


def _load(storage) -> dict:
    return storage.read_json(_ROUTINES_KEY, default={"version": 1, "routines": []})


def _save(storage, data: dict) -> None:
    storage.write_json(_ROUTINES_KEY, data)


# Private slug helpers duplicated from lib/projects.py — both registries keep
# their own copies rather than importing each other's privates.
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _unique_id(base: str, existing_ids: set) -> str:
    if base not in existing_ids:
        return base
    for i in range(2, 100):
        candidate = f"{base}-{i}"
        if candidate not in existing_ids:
            return candidate
    raise ValueError(f"Cannot generate unique ID for slug {base!r}: all candidates taken")


def _normalize_steps(steps) -> list:
    """Accept strings or {'title': ...} dicts; drop blank titles."""
    out = []
    for s in steps or []:
        title = (s.get("title") if isinstance(s, dict) else s or "").strip()
        if title:
            out.append({"title": title})
    return out


def list_routines(storage) -> list:
    return _load(storage)["routines"]


def get_routine(storage, routine_id: str) -> Optional[dict]:
    for r in list_routines(storage):
        if r["id"] == routine_id:
            return r
    return None


def add_routine(storage, name: str, steps: list, trigger: Optional[dict] = None) -> dict:
    data = _load(storage)
    existing_ids = {r["id"] for r in data["routines"]}
    routine = {
        "id": _unique_id(_slug(name), existing_ids),
        "name": name,
        "steps": _normalize_steps(steps),
        "trigger": trigger or None,
        "created": date.today().isoformat(),
        "runs": [],
    }
    data["routines"].append(routine)
    _save(storage, data)
    return routine


def update_routine(storage, routine_id: str, updates: dict) -> Optional[dict]:
    data = _load(storage)
    for r in data["routines"]:
        if r["id"] == routine_id:
            if "name" in updates:
                r["name"] = updates["name"]
            if "steps" in updates:
                r["steps"] = _normalize_steps(updates["steps"])
            if "trigger" in updates:
                r["trigger"] = updates["trigger"] or None
            _save(storage, data)
            return r
    return None


def delete_routine(storage, routine_id: str) -> bool:
    data = _load(storage)
    before = len(data["routines"])
    data["routines"] = [r for r in data["routines"] if r["id"] != routine_id]
    if len(data["routines"]) == before:
        return False
    _save(storage, data)
    return True
```

- [ ] **Step 4: Add the gitignore allow-list line** — in `.gitignore`, directly after the `!data/notes.jsonl` line, add:

```
!data/routines.json
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_routines.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add lib/routines.py tests/test_routines.py .gitignore
git commit -m "feat(routines): routines registry with CRUD in lib/routines.py"
```

---

### Task 2: `run_routine` + duplicate-run helpers

**Files:**
- Modify: `lib/routines.py`
- Test: `tests/test_routines.py`

**Interfaces:**
- Consumes: `lib.tasks.add_task(storage, title, source=..., metadata=...)` (existing).
- Produces: `run_routine(storage, routine_id, source: str = "ui", trigger_key: Optional[str] = None) -> Optional[dict]` — returns `{"routine": <updated routine>, "tasks": [<created task dicts>]}` or `None` if routine not found; `ran_within(routine: dict, days: int, today: Optional[str] = None) -> bool`; `last_run_date(routine: dict) -> Optional[str]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_routines.py`:

```python
# --- Run ---

def test_run_routine_creates_tagged_tasks_and_records_run(tmp_path):
    from datetime import date
    from lib.tasks import get_open_tasks
    from lib.routines import run_routine
    s = _s(tmp_path)
    r = add_routine(s, name="OOO Prep", steps=["Cancel meetings", "Set responder"])
    result = run_routine(s, r["id"])
    today = date.today().isoformat()

    assert [t["title"] for t in result["tasks"]] == ["Cancel meetings", "Set responder"]
    for t in result["tasks"]:
        assert t["source"] == "routine"
        assert t["metadata"] == {"routine": r["id"], "routine_run": today}
    assert result["routine"]["runs"] == [{"date": today, "trigger_key": None, "source": "ui"}]

    # tasks landed in the real task ledger, run persisted in the registry
    open_titles = {t["title"] for t in get_open_tasks(s)}
    assert {"Cancel meetings", "Set responder"} <= open_titles
    assert get_routine(s, r["id"])["runs"] == result["routine"]["runs"]


def test_run_routine_with_source_and_trigger_key(tmp_path):
    from lib.routines import run_routine
    s = _s(tmp_path)
    r = add_routine(s, name="R", steps=["a"])
    result = run_routine(s, r["id"], source="slack", trigger_key="gcal:evt123")
    assert result["routine"]["runs"][0]["source"] == "slack"
    assert result["routine"]["runs"][0]["trigger_key"] == "gcal:evt123"


def test_run_routine_missing_returns_none(tmp_path):
    from lib.routines import run_routine
    assert run_routine(_s(tmp_path), "nope") is None


def test_ran_within(tmp_path):
    from datetime import date, timedelta
    from lib.routines import ran_within, last_run_date
    today = date.today()
    recent = {"runs": [{"date": (today - timedelta(days=3)).isoformat(), "trigger_key": None, "source": "ui"}]}
    old = {"runs": [{"date": (today - timedelta(days=10)).isoformat(), "trigger_key": None, "source": "ui"}]}
    never = {"runs": []}
    assert ran_within(recent, days=7) is True
    assert ran_within(old, days=7) is False
    assert ran_within(never, days=7) is False
    assert last_run_date(recent) == (today - timedelta(days=3)).isoformat()
    assert last_run_date(never) is None


def test_ran_within_explicit_today():
    from lib.routines import ran_within
    r = {"runs": [{"date": "2026-07-01", "trigger_key": None, "source": "ui"}]}
    assert ran_within(r, days=7, today="2026-07-05") is True
    assert ran_within(r, days=7, today="2026-07-20") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_routines.py -v -k "run or ran"`
Expected: FAIL — `ImportError: cannot import name 'run_routine'`

- [ ] **Step 3: Implement** — append to `lib/routines.py`:

```python
def run_routine(storage, routine_id: str, source: str = "ui",
                trigger_key: Optional[str] = None) -> Optional[dict]:
    """Instantiate a routine: one ordinary task per step, tagged so the UI can
    group the batch, plus a run record on the routine itself."""
    from lib.tasks import add_task

    data = _load(storage)
    routine = next((r for r in data["routines"] if r["id"] == routine_id), None)
    if routine is None:
        return None

    today = date.today().isoformat()
    tasks = [
        add_task(
            storage,
            title=step["title"],
            source="routine",
            metadata={"routine": routine_id, "routine_run": today},
        )
        for step in routine["steps"]
    ]
    routine["runs"].append({"date": today, "trigger_key": trigger_key, "source": source})
    _save(storage, data)
    return {"routine": routine, "tasks": tasks}


def last_run_date(routine: dict) -> Optional[str]:
    runs = routine.get("runs") or []
    return max((r["date"] for r in runs), default=None)


def ran_within(routine: dict, days: int, today: Optional[str] = None) -> bool:
    last = last_run_date(routine)
    if not last:
        return False
    today_d = date.fromisoformat(today) if today else date.today()
    return last >= (today_d - timedelta(days=days)).isoformat()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_routines.py tests/test_tasks.py -v`
Expected: ALL PASS (task lib untouched — regression check only)

- [ ] **Step 5: Commit**

```bash
git add lib/routines.py tests/test_routines.py
git commit -m "feat(routines): run_routine creates tagged tasks and records runs"
```

---

### Task 3: Server endpoints + snapshot

**Files:**
- Modify: `tools/server.py` — `_Snapshot.__init__` (~line 36), `rebuild_snapshot()` (~line 56), `bootstrap()` (~line 137), new `# --- Routines ---` section after the Projects endpoints (after `delete_project`, ~line 296)
- Test: `tests/test_server_data_layer.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2 (`routines_lib.list_routines/get_routine/add_routine/update_routine/delete_routine/run_routine/ran_within/last_run_date`).
- Produces: `GET /api/routines` → list; `POST /api/routines` (`{name, steps, trigger?}`, 400 without name or without ≥1 non-blank step) → 201 `{routine, push}`; `PATCH /api/routines/<id>` → `{routine, push}` | 404; `DELETE /api/routines/<id>` → `{deleted, push}` | 404; `POST /api/routines/<id>/run` (`{force?: bool}`) → 201 `{routine, tasks, push}` | 404 | 400 `no_steps` | 409 `{"error": "recent_run", "last_run": "..."}` when ran within 7 days and not force. `SNAPSHOT.routines` + `"routines"` key in `/api/bootstrap`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_server_data_layer.py`: add `"data/routines.json": json.dumps({"version": 1, "routines": []}),` to the `main` dict in the `client` fixture, then append:

```python
# --- Routines ---

def _mk_routine(client, name="OOO Prep", steps=("Cancel meetings", "Set responder")):
    r = client.post("/api/routines", json={"name": name, "steps": list(steps)})
    assert r.status_code == 201
    return json.loads(r.data)["routine"]


def test_routines_crud_roundtrip(client):
    r = _mk_routine(client)
    assert r["id"] == "ooo-prep"
    listed = json.loads(client.get("/api/routines").data)
    assert [x["id"] for x in listed] == ["ooo-prep"]

    resp = client.patch("/api/routines/ooo-prep", json={"name": "OOO", "steps": ["Only step"]})
    assert resp.status_code == 200
    assert json.loads(resp.data)["routine"]["steps"] == [{"title": "Only step"}]

    resp = client.delete("/api/routines/ooo-prep")
    assert resp.status_code == 200
    assert json.loads(client.get("/api/routines").data) == []


def test_create_routine_requires_name_and_steps(client):
    assert client.post("/api/routines", json={"steps": ["x"]}).status_code == 400
    assert client.post("/api/routines", json={"name": "R", "steps": ["", "  "]}).status_code == 400


def test_patch_delete_missing_routine_404(client):
    assert client.patch("/api/routines/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/routines/nope").status_code == 404


def test_run_routine_creates_tasks(client):
    _mk_routine(client)
    resp = client.post("/api/routines/ooo-prep/run", json={})
    assert resp.status_code == 201
    body = json.loads(resp.data)
    assert [t["title"] for t in body["tasks"]] == ["Cancel meetings", "Set responder"]
    tasks = json.loads(client.get("/api/tasks").data)
    routine_tasks = [t for t in tasks if t["metadata"].get("routine") == "ooo-prep"]
    assert len(routine_tasks) == 2


def test_run_routine_recent_guard_and_force(client):
    _mk_routine(client)
    assert client.post("/api/routines/ooo-prep/run", json={}).status_code == 201
    resp = client.post("/api/routines/ooo-prep/run", json={})
    assert resp.status_code == 409
    assert json.loads(resp.data)["error"] == "recent_run"
    assert client.post("/api/routines/ooo-prep/run", json={"force": True}).status_code == 201


def test_run_routine_missing_and_empty(client):
    assert client.post("/api/routines/nope/run", json={}).status_code == 404
    assert client.post("/api/routines", json={"name": "E2", "steps": []}).status_code == 400


def test_bootstrap_includes_routines(client):
    _mk_routine(client)
    boot = json.loads(client.get("/api/bootstrap").data)
    assert [r["id"] for r in boot["routines"]] == ["ooo-prep"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server_data_layer.py -v -k routine`
Expected: FAIL — 404s from missing `/api/routines` routes

- [ ] **Step 3: Implement in `tools/server.py`**

(a) Import beside the other libs (top of file, matching existing style): `from lib import routines as routines_lib` — match the exact import idiom used for `tasks_lib`/`projects_lib` (check the header; it may be `import lib.tasks as tasks_lib` style).

(b) `_Snapshot.__init__`: add `self.routines = []` after `self.projects = []`.

(c) `rebuild_snapshot()`: add `SNAPSHOT.routines = routines_lib.list_routines(store)` after the `SNAPSHOT.projects = ...` line.

(d) `bootstrap()`: add `"routines": SNAPSHOT.routines,` after `"projects": SNAPSHOT.projects,`.

(e) New section after `delete_project`:

```python
# --- Routines ---

@app.route("/api/routines", methods=["GET"])
def list_routines():
    return jsonify(SNAPSHOT.routines)


@app.route("/api/routines", methods=["POST"])
def create_routine():
    body = request.get_json(force=True)
    if not body or not body.get("name"):
        return jsonify({"error": "name is required"}), 400
    if not routines_lib._normalize_steps(body.get("steps")):
        return jsonify({"error": "at least one step is required"}), 400

    def mutate(store):
        return routines_lib.add_routine(
            store,
            name=body["name"],
            steps=body.get("steps") or [],
            trigger=body.get("trigger"),
        )

    routine, push, status = _write_main(mutate, lambda r: f"data: add routine '{r['name']}'")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    return jsonify({"routine": routine, "push": push}), 201


@app.route("/api/routines/<routine_id>", methods=["PATCH"])
def update_routine(routine_id: str):
    updates = request.get_json(force=True)
    routine, push, status = _write_main(
        lambda store: routines_lib.update_routine(store, routine_id, updates),
        f"data: update routine {routine_id}",
    )
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if routine is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"routine": routine, "push": push})


@app.route("/api/routines/<routine_id>", methods=["DELETE"])
def delete_routine(routine_id: str):
    def mutate(store):
        return routine_id if routines_lib.delete_routine(store, routine_id) else None

    result, push, status = _write_main(mutate, f"data: delete routine {routine_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": routine_id, "push": push})


@app.route("/api/routines/<routine_id>/run", methods=["POST"])
def run_routine(routine_id: str):
    body = request.get_json(force=True, silent=True) or {}
    routine = routines_lib.get_routine(_read_store(), routine_id)
    if routine is None:
        return jsonify({"error": "not found"}), 404
    if not routine.get("steps"):
        return jsonify({"error": "no_steps"}), 400
    if not body.get("force") and routines_lib.ran_within(routine, days=7):
        return jsonify({"error": "recent_run",
                        "last_run": routines_lib.last_run_date(routine)}), 409

    def mutate(store):
        return routines_lib.run_routine(store, routine_id, source="ui")

    result, push, status = _write_main(
        mutate, lambda r: f"data: run routine {routine_id} ({len(r['tasks'])} tasks)")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"routine": result["routine"], "tasks": result["tasks"], "push": push}), 201
```

Note: Flask requires unique endpoint function names — `list_routines`/`update_routine`/`delete_routine`/`run_routine` collide with nothing in server.py today (`list_tasks`, `list_projects`, etc.), but they DO shadow the `routines_lib` function names only if imported bare — which is why the import in (a) must be the namespaced `routines_lib` form, never `from lib.routines import *`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server_data_layer.py tests/test_server.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tools/server.py tests/test_server_data_layer.py
git commit -m "feat(routines): routines CRUD + run endpoints with recent-run guard"
```

---

### Task 4: Registry UI — Routines section

**Files:**
- Modify: `tools/registry_ui.html` — new render/wire helper functions (place directly before `renderWorkView`), `renderWorkView()` (fetch + section + wiring), CSS block containing `.due-chip`.

**Interfaces:**
- Consumes: the Task 3 endpoints exactly as specified; existing helpers `fetchJSON(url, {method, body, label})` (throws `Error('HTTP 409')` on 409 — no status field), `esc()`, `el()`, `setBusy()`, `formatDate(iso)`, `workState`.
- Produces: `workState.routineEditing` (Set of routine ids, plus the sentinel `"__new__"`); Routines section DOM ids used by Task 5's verification: `#routines-list`, `#routine-row-<id>`, `#new-routine-toggle`.

There is no JS test harness — verification is code-reading + `node --check` on extracted JS + the controller's browser walkthrough in Task 6.

- [ ] **Step 1: State** — find `const workState` and add `routineEditing: new Set(),` to it.

- [ ] **Step 2: Render/wire helpers** — insert these functions directly before `renderWorkView`:

```js
function routineStepInputHtml(val) {
  return `<div class="routine-step-row">
    <input class="add-task-input routine-step-input" value="${esc(val || '')}" placeholder="Step…" style="flex:1" />
    <button class="routine-step-up" title="Move up">↑</button>
    <button class="routine-step-del" title="Remove">×</button>
  </div>`;
}

function routineFormHtml(idPrefix, r) {
  const steps = (r?.steps?.length ? r.steps : [{ title: '' }])
    .map(s => routineStepInputHtml(s.title)).join('');
  const trigType = r?.trigger?.type || '';
  const lead = r?.trigger?.lead_days ?? 7;
  return `
    <input class="add-task-input" id="${idPrefix}-name" placeholder="Routine name…" value="${esc(r?.name || '')}" style="width:100%;margin-bottom:6px" />
    <div class="routine-steps" id="${idPrefix}-steps">${steps}</div>
    <div class="routine-form-footer">
      <button class="routine-add-step" id="${idPrefix}-add-step">+ Step</button>
      <select id="${idPrefix}-trigger">
        <option value="">Manual only</option>
        <option value="calendar_ooo"${trigType === 'calendar_ooo' ? ' selected' : ''}>Auto-suggest on calendar OOO</option>
      </select>
      <input type="number" id="${idPrefix}-lead" value="${lead}" min="1" max="60" style="width:52px"${trigType ? '' : ' disabled'} />
      <span class="muted" style="font-size:11px">days ahead</span>
      <button class="btn-add-task" id="${idPrefix}-save">Save</button>
    </div>`;
}

function readRoutineForm(idPrefix) {
  const name = document.getElementById(`${idPrefix}-name`).value.trim();
  const steps = [...document.querySelectorAll(`#${idPrefix}-steps .routine-step-input`)]
    .map(i => i.value.trim()).filter(Boolean);
  const trigSel = document.getElementById(`${idPrefix}-trigger`).value;
  const lead = parseInt(document.getElementById(`${idPrefix}-lead`).value, 10) || 7;
  return { name, steps, trigger: trigSel ? { type: trigSel, lead_days: lead } : null };
}

function wireRoutineForm(idPrefix, onSave) {
  const panel = document.getElementById(`${idPrefix}-steps`);
  document.getElementById(`${idPrefix}-add-step`).addEventListener('click', () => {
    panel.insertAdjacentHTML('beforeend', routineStepInputHtml(''));
  });
  document.getElementById(`${idPrefix}-trigger`).addEventListener('change', e => {
    document.getElementById(`${idPrefix}-lead`).disabled = !e.target.value;
  });
  panel.addEventListener('click', e => {
    const row = e.target.closest('.routine-step-row');
    if (!row) return;
    if (e.target.matches('.routine-step-del')) row.remove();
    else if (e.target.matches('.routine-step-up') && row.previousElementSibling) {
      row.parentElement.insertBefore(row, row.previousElementSibling);
    }
  });
  document.getElementById(`${idPrefix}-save`).addEventListener('click', async e => {
    const form = readRoutineForm(idPrefix);
    if (!form.name) { document.getElementById(`${idPrefix}-name`).focus(); return; }
    if (!form.steps.length) { alert('Add at least one step.'); return; }
    setBusy(e.target);
    try { await onSave(form); } catch (err) { setBusy(e.target, false); }
  });
}

function renderRoutineRow(r, editing) {
  const n = (r.steps || []).length;
  const trig = r.trigger
    ? `<span class="routine-trigger-chip">auto · OOO −${esc(String(r.trigger.lead_days))}d</span>` : '';
  return `
    <div class="routine-row" id="routine-row-${esc(r.id)}">
      <div class="routine-row-main">
        <button class="btn-run-routine" data-routine-id="${esc(r.id)}">Run</button>
        <span class="routine-name">${esc(r.name)}</span>
        <span class="muted" style="font-size:12px">${n} step${n !== 1 ? 's' : ''}</span>
        ${trig}
        <button class="routine-edit-btn" data-routine-id="${esc(r.id)}" title="Edit routine">✎</button>
        <button class="btn-delete-routine" data-routine-id="${esc(r.id)}" title="Delete routine">✕</button>
      </div>
      <div class="routine-edit-panel${editing ? '' : ' hidden'}" id="routine-edit-${esc(r.id)}">
        ${editing ? routineFormHtml(`rf-${r.id}`, r) : ''}
      </div>
    </div>`;
}

async function runRoutineFromUi(id, btn, onChanged) {
  setBusy(btn);
  const post = body => fetchJSON(`${API}/api/routines/${encodeURIComponent(id)}/run`, {
    method: 'POST', body: JSON.stringify(body), label: 'Routine run',
  });
  try {
    await post({});
    onChanged();
  } catch (err) {
    if (err.message === 'HTTP 409') {
      if (confirm('This routine already ran in the last 7 days. Run it again?')) {
        try { await post({ force: true }); onChanged(); return; }
        catch (e2) { /* arc toasted */ }
      }
    }
    setBusy(btn, false);
  }
}

function wireRoutinesSection(view, onChanged) {
  const list = document.getElementById('routines-list');
  if (!list) return;

  const toggle = document.getElementById('new-routine-toggle');
  if (toggle) toggle.addEventListener('click', () => {
    if (workState.routineEditing.has('__new__')) workState.routineEditing.delete('__new__');
    else workState.routineEditing.add('__new__');
    onChanged();
  });

  if (workState.routineEditing.has('__new__')) {
    wireRoutineForm('rf-new', async form => {
      await fetchJSON(`${API}/api/routines`, {
        method: 'POST', body: JSON.stringify(form), label: 'Routine added',
      });
      workState.routineEditing.delete('__new__');
      onChanged();
    });
  }

  list.addEventListener('click', async e => {
    const id = e.target.dataset.routineId;
    if (!id) return;
    if (e.target.matches('.btn-run-routine')) {
      await runRoutineFromUi(id, e.target, onChanged);
    } else if (e.target.matches('.routine-edit-btn')) {
      if (workState.routineEditing.has(id)) workState.routineEditing.delete(id);
      else workState.routineEditing.add(id);
      onChanged();
    } else if (e.target.matches('.btn-delete-routine')) {
      const name = document.querySelector(`#routine-row-${CSS.escape(id)} .routine-name`)?.textContent || id;
      if (!confirm(`Delete routine "${name}"? Tasks already created by past runs are kept.`)) return;
      setBusy(e.target);
      try {
        await fetchJSON(`${API}/api/routines/${encodeURIComponent(id)}`, { method: 'DELETE', label: 'Routine deleted' });
        onChanged();
      } catch (err) { setBusy(e.target, false); }
    }
  });

  workState.routineEditing.forEach(id => {
    if (id === '__new__') return;
    wireRoutineForm(`rf-${id}`, async form => {
      await fetchJSON(`${API}/api/routines/${encodeURIComponent(id)}`, {
        method: 'PATCH', body: JSON.stringify(form), label: 'Routine updated',
      });
      workState.routineEditing.delete(id);
      onChanged();
    });
  });
}
```

- [ ] **Step 3: Section markup in `renderWorkView`** — (a) add `routines` to the parallel fetch: extend the destructuring to `[projects, allTasks, people, allNotes, noteTags, routines]` and append `fetchJSON(`${API}/api/routines`)` to the `Promise.all` array. (b) Build the section HTML before `view.innerHTML`:

```js
  const routineRowsHtml = (routines || []).length
    ? routines.map(r => renderRoutineRow(r, workState.routineEditing.has(r.id))).join('')
    : '<div class="muted" style="font-size:12px">No routines yet.</div>';
  const newRoutineHtml = workState.routineEditing.has('__new__')
    ? `<div class="routine-edit-panel" id="routine-new-panel">${routineFormHtml('rf-new', null)}</div>` : '';
```

(c) Append to the `view.innerHTML` template, after the standalone section's closing `</div>`:

```js
    <div class="routines-section">
      <div class="work-section-header">
        <span class="work-section-label">Routines</span>
        <button class="btn-new-proj" id="new-routine-toggle">+ New Routine</button>
      </div>
      ${newRoutineHtml}
      <div id="routines-list">${routineRowsHtml}</div>
    </div>
```

(d) At the end of `renderWorkView`'s wiring (near the Later-toggle wiring), add: `wireRoutinesSection(view, () => renderWorkView());`

- [ ] **Step 4: CSS** — add next to the `.horizon-chip` rules from Phase 1:

```css
.routines-section { margin-top: 24px; }
.routine-row { border-bottom: 1px solid var(--border, #333); padding: 6px 0; }
.routine-row-main { display: flex; align-items: center; gap: 8px; }
.routine-name { font-weight: 500; }
.routine-trigger-chip { background:#e0f2fe; color:#0369a1; border-radius:10px; padding:1px 8px; font-size:11px; white-space:nowrap; }
.routine-edit-panel { padding: 8px 0 4px 24px; }
.routine-step-row { display: flex; gap: 6px; margin-bottom: 4px; align-items: center; }
.routine-form-footer { display: flex; gap: 8px; align-items: center; margin-top: 6px; }
.btn-run-routine { /* match .btn-done styling — copy its rule values */ }
```

For `.btn-run-routine`, locate the `.btn-done` CSS rule and copy its declarations verbatim (do not guess colors — reuse the exact values so Run buttons match Done buttons).

- [ ] **Step 5: Verify** — re-read each edited region for template-literal/brace balance; extract and `node --check` the JS (method documented in `.superpowers/sdd/task-5-report.md` from Phase 1 if present, else: extract the `<script>` body to a temp file and `node --check` it); run `python3 -m pytest tests/test_server.py tests/test_server_data_layer.py -q` (untouched, regression only).

- [ ] **Step 6: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(routines): routines section in registry UI (list, form, run, delete)"
```

---

### Task 5: Registry UI — group a run's tasks in the standalone list

**Files:**
- Modify: `tools/registry_ui.html` — `renderWorkView()` standalone section only; CSS.

**Interfaces:**
- Consumes: `routines` array already fetched in Task 4; tasks carry `metadata.routine` + `metadata.routine_run` from Task 3's run endpoint. `renderTaskRow`, `notesByTask`, `formatDate`, `esc` as in Phase 1.
- Produces: standalone tasks with `metadata.routine_run` render inside a labeled `.routine-run-group` ("<Routine name> — <formatted date>") below the ungrouped standalone tasks; behind-horizon routine tasks still go to the "Later" section unchanged (horizon partition happens first and is not modified).

- [ ] **Step 1: Partition and render** — in `renderWorkView`, the Phase 1 code computes `standaloneTasks` (visible) and `laterTasks`. Replace the existing `standaloneHtml` construction with:

```js
  const isRunTask = t => !!(t.metadata && t.metadata.routine_run);
  const ungrouped = standaloneTasks.filter(t => !isRunTask(t));
  const runGroups = new Map();
  for (const t of standaloneTasks.filter(isRunTask)) {
    const key = `${t.metadata.routine || ''}|${t.metadata.routine_run}`;
    if (!runGroups.has(key)) runGroups.set(key, []);
    runGroups.get(key).push(t);
  }
  const routineNameById = new Map((routines || []).map(r => [r.id, r.name]));
  const runGroupsHtml = [...runGroups.entries()].map(([key, tasks]) => {
    const [rid, runDate] = key.split('|');
    const label = `${routineNameById.get(rid) || rid || 'Routine'} — ${formatDate(runDate)}`;
    return `<div class="routine-run-group">
      <div class="routine-run-label">${esc(label)}</div>
      ${tasks.map(t => renderTaskRow(t, people, true, notesByTask[t.id] || [])).join('')}
    </div>`;
  }).join('');
  const ungroupedHtml = ungrouped.length
    ? ungrouped.map(t => renderTaskRow(t, people, true, notesByTask[t.id] || [])).join('')
    : (runGroups.size ? '' : '<div class="muted" style="font-size:12px">No standalone tasks.</div>');
  const standaloneHtml = ungroupedHtml + runGroupsHtml;
```

Nothing else changes: `standaloneHtml` is interpolated where it already was, `#standalone-tasks` still wraps all of it, so `wireTaskInteractions` on that container covers grouped rows too (they are inside `#standalone-tasks` — verify this in the template before committing).

- [ ] **Step 2: CSS** — next to the Task 4 rules:

```css
.routine-run-group { border-left: 2px solid #c4b5fd; padding-left: 10px; margin: 8px 0; }
.routine-run-label { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #8b8b94; margin-bottom: 2px; }
```

- [ ] **Step 3: Verify** — same as Task 4 Step 5 (re-read, `node --check`, server pytest regression).

- [ ] **Step 4: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(routines): group routine-run tasks in standalone list"
```

---

### Task 6: Full-suite verification + browser walkthrough + PR

- [ ] **Step 1: Full suite**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -3`
Expected: ALL PASS (Phase 1 baseline: 820 passed, 3 skipped; this branch adds ~20)

- [ ] **Step 2: Browser walkthrough** (controller, on the served worktree UI — same port-8787 procedure as Phase 1; stop/restart the user's server around it):
  1. Create a routine via "+ New Routine": name "ZZTEST OOO", two steps; save → row appears with "2 steps".
  2. Edit it: rename, reorder steps with ↑, remove a step, set trigger "Auto-suggest on calendar OOO" with 5 days; save → chip shows "auto · OOO −5d".
  3. Run it → tasks appear in the standalone list under a "ZZTEST OOO — <today>" group label; routine row's run recorded (verify via `GET /api/routines`).
  4. Run again → confirm dialog (recent run); cancel → nothing created; run again + accept → second batch created.
  5. Set a horizon on one grouped task → it moves to "Later"; the group keeps the rest.
  6. Complete/delete grouped tasks → interactions work inside the group (they're in `#standalone-tasks`).
  7. Delete the routine → row gone; previously created tasks remain.
  8. Clean up: delete all ZZTEST tasks and the routine's tasks via the UI or API.

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin feat/routines-core
gh pr create --title "feat: routines — reusable task batches in the registry" --body "$(cat <<'EOF'
Phase 2 of the Horizon + Routines spec (docs/superpowers/specs/2026-07-04-task-horizon-routines-design.md).

- `data/routines.json` registry + `lib/routines.py` (CRUD, run, recent-run helpers)
- Server: GET/POST/PATCH/DELETE `/api/routines`, POST `/api/routines/<id>/run` (409 recent-run guard, `force` override); routines in snapshot + bootstrap
- Registry UI: Routines section on the Work tab (create/edit with reorderable steps + optional OOO trigger config, run with confirm-on-recent, delete); routine-run tasks render as labeled groups in the standalone list
- Trigger config is stored but inert — detection + brief suggestion + /routine Slack command land in Phase 3

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Merge on GitHub (server-side merge keeps local main from drifting ahead).
