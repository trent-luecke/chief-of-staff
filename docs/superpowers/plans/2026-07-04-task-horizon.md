# Task Horizon Implementation Plan (Phase 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `horizon` date to tasks that hides them from active views (Registry UI, morning brief) until that date arrives, settable from the UI and Slack `/task`.

**Architecture:** `horizon` becomes a first-class field on task `create` events in the `data/tasks.jsonl` event log, replayed by `lib/tasks.py`. The API keeps returning behind-horizon tasks — hiding is a presentation decision made per surface (UI collapses them; brief excludes them and announces arrivals). A single shared helper `is_behind_horizon()` defines visibility.

**Tech Stack:** Python 3.11 (Flask server, pytest), vanilla JS in a single HTML file (`tools/registry_ui.html`), Cloudflare Worker JS, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-04-task-horizon-routines-design.md` (Feature 1). Phases 2–3 (Routines, Triggers) get separate plan docs after this phase merges.

## Global Constraints

- All dates are ISO strings `YYYY-MM-DD`. **Behind horizon** means `horizon > today` (string compare is safe for ISO dates). On the horizon date itself the task is fully visible.
- The API and `get_open_tasks()` MUST keep returning behind-horizon tasks. Never filter at the storage layer.
- No Telegram changes: do not touch `processors/query_tools.py` or `processors/query.py`.
- Existing events in `tasks.jsonl` have no `horizon` key — every reader must tolerate its absence (`.get("horizon")`).
- `horizon` must NOT be added to the `_PROTECTED` set in `lib/tasks.py` — it must stay patchable.
- Never save a task state where `horizon > due_date` (both set). UI and Slack paths guard this.
- Work on branch `feat/task-horizon` off fresh `origin/main`. Never hand-edit `data/*.jsonl` files.
- Run tests with `python -m pytest tests/<file> -v` from the repo root.

---

### Task 1: `horizon` field + visibility helpers in `lib/tasks.py`

**Files:**
- Modify: `lib/tasks.py` (create-event replay ~line 60, `add_task` ~line 87)
- Test: `tests/test_tasks.py`

**Interfaces:**
- Produces: `add_task(storage, title, ..., horizon: Optional[str] = None) -> dict` (task dict gains `"horizon"` key); `is_behind_horizon(task: dict, today: Optional[str] = None) -> bool`; `get_surfaced_tasks(storage, lookback_days: int = 1) -> list` (open tasks whose horizon arrived within the window `today - lookback_days < horizon <= today`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_tasks.py` (note: this file's existing imports are `add_task, complete_task, get_open_tasks, get_recent_completions, edit_task`; extend that import line):

```python
from datetime import date, timedelta
from lib.tasks import is_behind_horizon, get_surfaced_tasks


# --- Horizon ---

def test_add_task_with_horizon(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Renew SSL", horizon="2099-01-01")
    assert task["horizon"] == "2099-01-01"
    assert get_open_tasks(s)[0]["horizon"] == "2099-01-01"


def test_add_task_defaults_horizon_none(tmp_path):
    assert add_task(_s(tmp_path), "Send deck")["horizon"] is None


def test_replay_tolerates_legacy_events_without_horizon(tmp_path):
    s = _s(tmp_path)
    s.append_line("tasks.jsonl", json.dumps({
        "event": "create", "task_id": "t-legacy", "title": "Old task",
        "source": "slack", "created_at": "2026-01-01", "due_date": None,
        "metadata": {}, "project_id": None, "collaborators": [],
    }))
    tasks = get_open_tasks(s)
    assert tasks[0]["horizon"] is None


def test_edit_task_sets_and_clears_horizon(tmp_path):
    s = _s(tmp_path)
    t = add_task(s, "Send deck")
    assert edit_task(s, t["id"], {"horizon": "2099-01-01"})["horizon"] == "2099-01-01"
    assert edit_task(s, t["id"], {"horizon": None})["horizon"] is None
    assert get_open_tasks(s)[0]["horizon"] is None


def test_is_behind_horizon():
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=1)).isoformat()
    past = (date.today() - timedelta(days=1)).isoformat()
    assert is_behind_horizon({"horizon": None}) is False
    assert is_behind_horizon({}) is False
    assert is_behind_horizon({"horizon": today}) is False   # visible ON the horizon date
    assert is_behind_horizon({"horizon": future}) is True
    assert is_behind_horizon({"horizon": past}) is False


def test_is_behind_horizon_explicit_today():
    assert is_behind_horizon({"horizon": "2026-07-10"}, today="2026-07-09") is True
    assert is_behind_horizon({"horizon": "2026-07-10"}, today="2026-07-10") is False


def test_get_surfaced_tasks(tmp_path):
    s = _s(tmp_path)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    future = (date.today() + timedelta(days=3)).isoformat()
    add_task(s, "Arrived today", horizon=today)
    add_task(s, "Arrived yesterday", horizon=yesterday)
    add_task(s, "Still deferred", horizon=future)
    add_task(s, "No horizon")
    assert [t["title"] for t in get_surfaced_tasks(s)] == ["Arrived today"]


def test_get_surfaced_tasks_excludes_completed(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Done already", horizon=date.today().isoformat())
    complete_task(s, "Done already")
    assert get_surfaced_tasks(s) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tasks.py -v -k "horizon or surfaced"`
Expected: FAIL — `ImportError: cannot import name 'is_behind_horizon'`

- [ ] **Step 3: Implement in `lib/tasks.py`**

(a) In `_replay()`, in the `create` branch dict (after the `"due_date"` line), add:

```python
                "horizon": event.get("horizon"),
```

(b) In `add_task()`, add the parameter `horizon: Optional[str] = None` (after `owner`), add `"horizon": horizon,` to the `event` dict (after `"due_date": due_date,`), and add `"horizon": horizon,` to the returned dict (after `"due_date": due_date,`).

(c) Add at module level (after `get_recent_completions`):

```python
def is_behind_horizon(task: dict, today: Optional[str] = None) -> bool:
    """True when the task's horizon date is strictly after today.

    Behind-horizon tasks stay in the data and API; each surface decides
    how to de-emphasize them. On the horizon date itself this is False.
    """
    horizon = task.get("horizon")
    if not horizon:
        return False
    return horizon > (today or date.today().isoformat())


def get_surfaced_tasks(storage, lookback_days: int = 1) -> list:
    """Open tasks whose horizon arrived within the last lookback_days.

    Window: today - lookback_days < horizon <= today. Used by the brief to
    announce tasks that just came off the horizon.
    """
    today = date.today()
    since = (today - timedelta(days=lookback_days)).isoformat()
    today_s = today.isoformat()
    return [
        t for t in get_open_tasks(storage)
        if t.get("horizon") and since < t["horizon"] <= today_s
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tasks.py -v`
Expected: ALL PASS (existing tests must stay green — `horizon` is additive)

- [ ] **Step 5: Commit**

```bash
git add lib/tasks.py tests/test_tasks.py
git commit -m "feat(horizon): add horizon field and visibility helpers to task lib"
```

---

### Task 2: Server create endpoint passes `horizon`

**Files:**
- Modify: `tools/server.py` (`create_task()`, ~line 164)
- Test: `tests/test_server_data_layer.py`

**Interfaces:**
- Consumes: `add_task(..., horizon=...)` from Task 1.
- Produces: `POST /api/tasks` accepts optional `"horizon"` in the JSON body; `GET /api/tasks` responses include `"horizon"`. (`PATCH /api/tasks/<id>` already passes `horizon` through — `edit_task` takes an arbitrary patch and `horizon` is not protected.)

- [ ] **Step 1: Write the failing test** — append to `tests/test_server_data_layer.py` (uses the existing `client` fixture with the in-memory fake of origin/main):

```python
def test_create_task_with_horizon_roundtrips(client):
    r = client.post("/api/tasks", json={"title": "Renew SSL", "horizon": "2099-01-01"})
    assert r.status_code == 201
    assert json.loads(r.data)["task"]["horizon"] == "2099-01-01"
    tasks = json.loads(client.get("/api/tasks").data)
    assert tasks[0]["horizon"] == "2099-01-01"


def test_patch_task_horizon(client):
    r = client.post("/api/tasks", json={"title": "Send deck"})
    task_id = json.loads(r.data)["task"]["id"]
    r = client.patch(f"/api/tasks/{task_id}", json={"horizon": "2099-01-01"})
    assert r.status_code == 200
    assert json.loads(r.data)["task"]["horizon"] == "2099-01-01"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_server_data_layer.py -v -k horizon`
Expected: `test_create_task_with_horizon_roundtrips` FAILS (`horizon` missing/None — create endpoint drops it); `test_patch_task_horizon` may already pass (generic patch) — keep it as a regression guard.

- [ ] **Step 3: Implement** — in `tools/server.py` `create_task()`, add one line to the `add_task` call (after `due_date=body.get("due_date"),`):

```python
            horizon=body.get("horizon"),
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_server_data_layer.py tests/test_server.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tools/server.py tests/test_server_data_layer.py
git commit -m "feat(horizon): accept horizon on task create endpoint"
```

---

### Task 3: Brief's project context excludes behind-horizon tasks

**Files:**
- Modify: `lib/projects.py` (`project_context_for_brief()`, ~line 102–125)
- Test: `tests/test_projects.py`

**Interfaces:**
- Consumes: `is_behind_horizon` from Task 1.
- Produces: `project_context_for_brief()` entries' `open_tasks` lists contain only visible (not behind-horizon) tasks.

- [ ] **Step 1: Write the failing test** — append to `tests/test_projects.py` (file already imports `add_project`, `project_context_for_brief`, and has the `_s(tmp_path)` helper):

```python
def test_project_context_excludes_behind_horizon_tasks(tmp_path):
    from datetime import date, timedelta
    from lib.tasks import add_task
    s = _s(tmp_path)
    p = add_project(s, canonical_name="Q3 Launch")
    future = (date.today() + timedelta(days=5)).isoformat()
    add_task(s, "Visible now", project_id=p["id"])
    add_task(s, "Deferred", project_id=p["id"], horizon=future)
    ctx = project_context_for_brief(s)
    assert [t["title"] for t in ctx[0]["open_tasks"]] == ["Visible now"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_projects.py -v -k behind_horizon`
Expected: FAIL — both titles present

- [ ] **Step 3: Implement** — in `lib/projects.py::project_context_for_brief`, change the import line and the `p_tasks` filter:

```python
    from lib.tasks import get_open_tasks, is_behind_horizon
```

```python
        p_tasks = [
            t for t in all_tasks
            if t.get("project_id") == pid and not is_behind_horizon(t)
        ]
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_projects.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add lib/projects.py tests/test_projects.py
git commit -m "feat(horizon): hide behind-horizon tasks from brief project context"
```

---

### Task 4: "Surfaced Today" section in the morning brief

**Files:**
- Modify: `processors/brief.py` (`_build_prompt()`, inside the `if storage is not None:` block that builds "Structured Projects", ~line 126–147)
- Test: `tests/test_brief.py`

**Interfaces:**
- Consumes: `get_surfaced_tasks(storage)` from Task 1.
- Produces: prompt section `## Surfaced Today (deferred tasks whose horizon arrived — announce these)` when any task surfaced; omitted otherwise.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_brief.py` (mirrors the existing `test_brief_includes_project_section` pattern):

```python
def test_brief_includes_surfaced_today_section(tmp_path):
    from datetime import date
    from lib.storage import LocalStorage
    from lib.tasks import add_task
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary

    storage = LocalStorage(str(tmp_path))
    add_task(storage, title="Renew SSL cert", horizon=date.today().isoformat())

    prompt = _build_prompt(
        today_events=[], tomorrow_events=[], projects=[], due_tasks=[],
        loop_summary=LoopSummary(), open_issues=[], meeting_prep=[],
        inbox_text="", storage=storage,
    )
    assert "Surfaced Today" in prompt
    assert "Renew SSL cert" in prompt


def test_brief_omits_surfaced_today_when_none(tmp_path):
    from lib.storage import LocalStorage
    from lib.tasks import add_task
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary

    storage = LocalStorage(str(tmp_path))
    add_task(storage, title="Plain task")

    prompt = _build_prompt(
        today_events=[], tomorrow_events=[], projects=[], due_tasks=[],
        loop_summary=LoopSummary(), open_issues=[], meeting_prep=[],
        inbox_text="", storage=storage,
    )
    assert "Surfaced Today" not in prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_brief.py -v -k surfaced`
Expected: FAIL — "Surfaced Today" not in prompt

- [ ] **Step 3: Implement** — in `processors/brief.py::_build_prompt`, directly AFTER the Structured Projects `try/except` block (still inside `if storage is not None:`), add:

```python
        try:
            from lib.tasks import get_surfaced_tasks
            surfaced = get_surfaced_tasks(storage)
            if surfaced:
                sections += section(
                    "## Surfaced Today (deferred tasks whose horizon arrived — announce these)",
                    [
                        f"  - {t['title']}"
                        + (f" (due {t['due_date']})" if t.get("due_date") else "")
                        for t in surfaced
                    ],
                )
        except Exception:
            pass  # non-fatal — brief continues without this section
```

Note: the announcement window is "horizon arrived since yesterday's run" (`lookback_days=1`). If a brief run is skipped, that day's arrivals aren't called out — but they still appear as normal visible tasks, so nothing is lost. Do not build run-date state for this.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_brief.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add processors/brief.py tests/test_brief.py
git commit -m "feat(horizon): announce surfaced tasks in morning brief"
```

---

### Task 5: Registry UI — horizon chip, Later section, project chip, form field, guards

**Files:**
- Modify: `tools/registry_ui.html` — functions `renderTaskRow` (~2066), `wireTaskInteractions` (~2203), `renderAddTaskForm` (~2261), `wireAddTaskForm` (~2278), `renderWorkView` (~2490); the `workState` object (search `const workState`); the CSS block containing `.due-chip`.

**Interfaces:**
- Consumes: `GET /api/tasks` items with `horizon`; `POST /api/tasks` body `horizon`; `PATCH /api/tasks/<id>` body `{horizon}`. Existing helpers `formatDate(iso)`, `esc()`, `showDatePicker(anchor, current, onSelect)`, `sortTasks()`.

No JS test harness exists in this repo — this task is verified in the browser (Step 6). Keep each edit surgical; the file is 3800+ lines.

- [ ] **Step 1: Add the visibility helper + horizon chip renderer** — insert after `renderDueDateChip` (~line 2043):

```js
function isBehindHorizon(t) {
  const today = new Date().toISOString().slice(0, 10);
  return !!(t.horizon && t.horizon > today);
}

function renderHorizonChip(task) {
  if (!task.horizon) return `<span class="horizon-ghost" data-task-id="${esc(task.id)}">+ horizon</span>`;
  const today = new Date().toISOString().slice(0, 10);
  const label = task.horizon > today ? `until ${formatDate(task.horizon)}` : formatDate(task.horizon);
  return `<span class="horizon-chip" data-task-id="${esc(task.id)}" data-horizon="${esc(task.horizon)}">${esc(label)}</span>`;
}
```

- [ ] **Step 2: Wire the chip into task rows** — in `renderTaskRow`, (a) change the opening row div to carry both dates for cross-field guards:

```js
    <div class="task-row" id="task-row-${esc(task.id)}" data-due="${esc(task.due_date || '')}" data-horizon="${esc(task.horizon || '')}">
```

(b) insert `${renderHorizonChip(task)}` on a new line directly after the due-chip line (the line rendering `renderDueDateChip(task)` / `.due-ghost`).

- [ ] **Step 3: Interactions + guards** — in `wireTaskInteractions`:

(a) Add a horizon handler after the due-chip handler block (before the owner-chip block):

```js
    if (e.target.matches('.horizon-chip') || e.target.matches('.horizon-ghost')) {
      const taskId = e.target.dataset.taskId;
      const cur = e.target.dataset.horizon || null;
      const row = document.getElementById(`task-row-${taskId}`);
      const due = row?.dataset.due || null;
      showDatePicker(e.target, cur, async iso => {
        if (iso === cur) return;
        if (iso && due && iso > due) {
          alert(`Horizon ${formatDate(iso)} is after the due date ${formatDate(due)} — move or clear the due date first.`);
          return;
        }
        try {
          await fetchJSON(`${API}/api/tasks/${encodeURIComponent(taskId)}`, {
            method: 'PATCH', body: JSON.stringify({ horizon: iso }), label: 'Task updated',
          });
          onChanged();
        } catch (err) { /* arc toasted; leave view unchanged */ }
      });
      return;
    }
```

(b) In the EXISTING due-chip handler, add the mirror guard at the top of its `showDatePicker` callback (before the `if (iso !== cur)` fetch):

```js
        const row = document.getElementById(`task-row-${taskId}`);
        const horizon = row?.dataset.horizon || null;
        if (iso && horizon && horizon > iso) {
          alert(`This task's horizon ${formatDate(horizon)} is after the new due date ${formatDate(iso)} — move or clear the horizon first.`);
          return;
        }
```

- [ ] **Step 4: Create form** — in `renderAddTaskForm`, add after the due input line:

```js
      <input class="add-task-input add-task-horizon" id="${formId}-horizon" placeholder="Horizon" style="width:90px;cursor:pointer;caret-color:transparent" readonly />
```

In `wireAddTaskForm`: (a) add `const horizonInput = document.getElementById(`${formId}-horizon`);` beside the other lookups; (b) duplicate the `dueInput` click-wiring block for `horizonInput` (same `showDatePicker` pattern, storing to `horizonInput.dataset.isoDate`); (c) in `submit`, before the fetch add:

```js
    const dueIso = dueInput?.dataset.isoDate || null;
    const horizonIso = horizonInput?.dataset.isoDate || null;
    if (dueIso && horizonIso && horizonIso > dueIso) {
      alert('Horizon is after the due date — adjust one.');
      return;
    }
```

and add `horizon: horizonIso,` to the POST body (after `due_date: ...`).

- [ ] **Step 5: Later section + project horizon chips** — in `renderWorkView`:

(a) Find `const workState` (object with `expanded`/`editing` sets) and add two fields: `laterExpanded: false, horizonShown: new Set(),`.

(b) Replace the standalone split:

```js
  const standaloneAll = sortTasks((allTasks || []).filter(t => !t.project_id));
  const standaloneTasks = standaloneAll.filter(t => !isBehindHorizon(t));
  const laterTasks = standaloneAll.filter(isBehindHorizon).sort((a, b) => (a.horizon < b.horizon ? -1 : 1));
```

(c) In the per-project map, replace the `pTasks` line with:

```js
        const pAll = sortTasks((allTasks || []).filter(t => t.project_id === p.id));
        const pTasks = pAll.filter(t => !isBehindHorizon(t));
        const pLater = pAll.filter(isBehindHorizon).sort((a, b) => (a.horizon < b.horizon ? -1 : 1));
        const showLater = workState.horizonShown.has(p.id);
```

In the project header template, after the `proj-group-count` span, add:

```js
              ${pLater.length ? `<span class="proj-horizon-chip" data-proj-id="${esc(p.id)}">${pLater.length} on horizon</span>` : ''}
```

In the project body, after `<div id="group-tasks-...">${taskRowsHtml}</div>`, add:

```js
              ${showLater && pLater.length ? `<div class="proj-later-rows">${pLater.map(t => renderTaskRow(t, people, false, notesByTask[t.id] || [])).join('')}</div>` : ''}
```

(d) Build the Later section and append it inside the standalone section markup, after `${renderAddTaskForm(null, people)}`:

```js
  const laterHtml = laterTasks.length ? `
    <div class="later-section">
      <div class="later-header" id="later-toggle">
        <span class="proj-group-chevron">${workState.laterExpanded ? '▼' : '▶'}</span>
        <span class="work-section-label">Later (${laterTasks.length})</span>
      </div>
      <div id="later-tasks" class="${workState.laterExpanded ? '' : 'hidden'}">
        ${laterTasks.map(t => renderTaskRow(t, people, true, notesByTask[t.id] || [])).join('')}
      </div>
    </div>` : '';
```

(declare `laterHtml` before the `view.innerHTML =` template; interpolate `${laterHtml}` after the standalone add-task form).

(e) Wire the toggles (near the other wiring at the bottom of `renderWorkView`):

```js
  const laterToggle = document.getElementById('later-toggle');
  if (laterToggle) laterToggle.addEventListener('click', () => {
    workState.laterExpanded = !workState.laterExpanded;
    renderWorkView();
  });
  view.querySelectorAll('.proj-horizon-chip').forEach(chip => {
    chip.addEventListener('click', e => {
      e.stopPropagation();  // header click also toggles project expand
      const pid = chip.dataset.projId;
      if (workState.horizonShown.has(pid)) workState.horizonShown.delete(pid);
      else { workState.horizonShown.add(pid); workState.expanded.add(pid); }
      renderWorkView();
    });
  });
```

(f) CSS — find the rule block containing `.due-chip` and add siblings:

```css
.horizon-chip { background:#ede9fe; color:#6d28d9; border-radius:10px; padding:1px 8px; font-size:11px; cursor:pointer; white-space:nowrap; }
.horizon-ghost { color:#bbb; font-size:11px; cursor:pointer; }
.proj-horizon-chip { background:#ede9fe; color:#6d28d9; border-radius:10px; padding:1px 8px; font-size:11px; cursor:pointer; white-space:nowrap; }
.later-section { margin-top:18px; opacity:.9; }
.later-header { display:flex; align-items:center; gap:6px; cursor:pointer; padding:4px 0; }
.proj-later-rows { border-top:1px dashed #ddd; margin-top:6px; padding-top:6px; }
```

- [ ] **Step 6: Verify in the browser** — start the server (`python3 tools/server.py`, port 8787) and check:
  1. Create a standalone task with horizon = tomorrow → it appears only under "Later (1)" (collapsed by default; expands on click).
  2. Create a project task with horizon = tomorrow → project shows "1 on horizon" chip; clicking the chip reveals the row; header count reflects visible tasks only.
  3. Set a horizon later than a due date via chip → alert, no save. Set due earlier than an existing horizon → alert, no save.
  4. Clear a horizon via the chip's "Clear date" → task returns to the normal list.
  5. Horizon = today → task stays in the normal list (not "Later").
  6. Check the server terminal: each change committed to origin/main without error.

Note: writes go to origin/main — creating test tasks is fine, but delete the throwaway tasks via the UI when done.

- [ ] **Step 7: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(horizon): Later section, horizon chips, and guards in registry UI"
```

---

### Task 6: Slack `/task` horizon token

**Files:**
- Modify: `cloudflare/telegram-bridge.js` (the `/task` handler: token parsing ~line 84–101 and both usage strings; plus the `assign_owner` interactive handler that re-dispatches `task_add.yml`)
- Modify: `.github/workflows/task_add.yml` (new input + env var)
- Modify: `scripts/slack_add_task.py` (`format_confirmation` ~line 70, `post_ambiguous_message` ~line 102, `main()` ~line 152)
- Test: `tests/test_slack_add_task.py`

**Interfaces:**
- Consumes: `add_task(..., horizon=...)` from Task 1; existing `parse_due_date(raw)` (reused verbatim for horizon phrases).
- Produces: `/task <title> [owner:<name>] [due:<date>] [horizon:<date>]`; workflow input `horizon_raw` → env `HORIZON_RAW`; `format_confirmation(title, due_date, owner_name=None, horizon=None) -> str`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_slack_add_task.py`:

```python
def test_format_confirmation_with_horizon():
    result = format_confirmation("Renew SSL", None, horizon="2026-09-01")
    assert result == "Task added: Renew SSL — on horizon until 2026-09-01"


def test_format_confirmation_due_and_horizon():
    result = format_confirmation("Renew SSL", "2026-09-15", horizon="2026-09-01")
    assert result == "Task added: Renew SSL — due 2026-09-15 — on horizon until 2026-09-01"


def test_horizon_conflict_message():
    from scripts.slack_add_task import horizon_conflict_message
    assert horizon_conflict_message("2026-09-15", "2026-09-01") is not None
    assert "2026-09-15" in horizon_conflict_message("2026-09-15", "2026-09-01")
    assert horizon_conflict_message("2026-09-01", "2026-09-15") is None  # horizon before due: fine
    assert horizon_conflict_message(None, "2026-09-01") is None
    assert horizon_conflict_message("2026-09-01", None) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_slack_add_task.py -v -k horizon`
Expected: FAIL — `format_confirmation` rejects `horizon` kwarg; `horizon_conflict_message` doesn't exist

- [ ] **Step 3: Implement `scripts/slack_add_task.py`**

(a) Replace `format_confirmation` with:

```python
def format_confirmation(title: str, due_date, owner_name: str | None = None, horizon: str | None = None) -> str:
    parts = [f"Task added: {title}"]
    if owner_name:
        parts.append(f"owner: {owner_name}")
    if due_date:
        parts.append(f"due {due_date}")
    if horizon:
        parts.append(f"on horizon until {horizon}")
    return " — ".join(parts)
```

(b) Add below `parse_due_date`:

```python
def horizon_conflict_message(horizon, due_date):
    """Error string when horizon lands after the due date, else None."""
    if horizon and due_date and horizon > due_date:
        return (
            f"⚠️ Horizon ({horizon}) is after the due date ({due_date}) — "
            "task not created. Adjust one and retry."
        )
    return None
```

(c) In `post_ambiguous_message`, add parameter `horizon_raw: str = ""` (after `due_date_raw`) and add `"horizon_raw": horizon_raw` to BOTH `json.dumps({...})` value payloads (the per-person buttons and "Assign to me").

(d) In `main()`: read `horizon_raw = os.environ.get("HORIZON_RAW", "")` beside the other env reads; after `due_date = parse_due_date(due_date_raw)` add:

```python
    horizon = parse_due_date(horizon_raw)  # same parser; "sept 1" → "2026-09-01"
    conflict = horizon_conflict_message(horizon, due_date)
    if conflict:
        post_to_slack(response_url, conflict)
        print(conflict)
        return
```

Pass `horizon_raw` into the `post_ambiguous_message(...)` call in the ambiguous branch; change the create call to `add_task(storage, title=title, source="slack", due_date=due_date, owner=owner_id, horizon=horizon)`; change the confirmation to `format_confirmation(title, due_date, display_owner, horizon)`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_slack_add_task.py -v`
Expected: ALL PASS

- [ ] **Step 5: Workflow env** — in `.github/workflows/task_add.yml`, add under `inputs:` (after `due_date_raw`):

```yaml
      horizon_raw:
        description: "Raw horizon date string — task hidden from active views until this date"
        required: false
        default: ""
```

and under the "Add task" step's `env:` (after `DUE_DATE_RAW`):

```yaml
          HORIZON_RAW: ${{ inputs.horizon_raw }}
```

- [ ] **Step 6: Worker parsing** — in `cloudflare/telegram-bridge.js` `/task` handler, replace the due-extraction block (the `dueMatch` lines through the `title` assignment) with segment-based token parsing so `due:` and `horizon:` work in either order, each consuming text up to the next token:

```js
  // Extract due:<date> and horizon:<date> tokens (multi-word values; either order)
  const tokenRe = /\b(due|horizon):/gi;
  const tokens = [...textWithoutOwner.matchAll(tokenRe)];
  const title = tokens.length
    ? textWithoutOwner.slice(0, tokens[0].index).trim()
    : textWithoutOwner.trim();
  let dueDateRaw = "";
  let horizonRaw = "";
  tokens.forEach((m, i) => {
    const start = m.index + m[0].length;
    const end = i + 1 < tokens.length ? tokens[i + 1].index : textWithoutOwner.length;
    const val = textWithoutOwner.slice(start, end).trim();
    if (m[1].toLowerCase() === "due") dueDateRaw = val;
    else horizonRaw = val;
  });
```

Add `horizon_raw: horizonRaw,` to the `dispatchToGitHub(env, "task_add.yml", {...})` payload (after `due_date_raw: dueDateRaw,`). Update BOTH usage strings in this handler to:

```
"Usage: /task <title> [owner:<name>] [due:<date>] [horizon:<date>]"
```

- [ ] **Step 7: Worker interactive handler passthrough** — in `cloudflare/telegram-bridge.js`, find the `assign_owner` action handler (search `assign_owner`) — it `JSON.parse`s the button `value` (`{title, due_date_raw, owner_raw}`) and re-dispatches `task_add.yml`. Add `horizon_raw: value.horizon_raw || ""` to its dispatch payload, mirroring `due_date_raw`.

- [ ] **Step 8: Commit** (worker deploys via `deploy-worker.yml` when the PR merges to main)

```bash
git add cloudflare/telegram-bridge.js .github/workflows/task_add.yml scripts/slack_add_task.py tests/test_slack_add_task.py
git commit -m "feat(horizon): parse horizon:<date> token in Slack /task"
```

---

### Task 7: Full-suite verification + PR

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest tests/ -v --timeout=120 2>&1 | tail -20`
Expected: ALL PASS, zero regressions

- [ ] **Step 2: Repeat the browser walkthrough** from Task 5 Step 6 against the final branch state.

- [ ] **Step 3: Push branch and open PR**

```bash
git push -u origin feat/task-horizon
gh pr create --title "feat: task horizon — defer task visibility until a date" --body "$(cat <<'EOF'
Phase 1 of the Horizon + Routines spec (docs/superpowers/specs/2026-07-04-task-horizon-routines-design.md).

- `horizon` field on task create/edit events; `is_behind_horizon()` + `get_surfaced_tasks()` in lib/tasks.py
- Registry UI: collapsed "Later (N)" standalone section, "N on horizon" project chips, horizon chip + create-form field, due/horizon conflict guards
- Slack: `/task <title> [due:<date>] [horizon:<date>]`
- Brief: behind-horizon tasks excluded from project context; "Surfaced Today" announcement when a horizon arrives
- No Telegram changes

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Merge on GitHub (server-side merge keeps local main from drifting ahead).
