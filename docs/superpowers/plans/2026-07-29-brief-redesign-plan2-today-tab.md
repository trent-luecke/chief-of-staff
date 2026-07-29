# Brief Redesign — Plan 2: Today Tab Shell + Generation Pipeline + Kill Email

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the emailed brief with a pre-computed, git-anchored `brief_today.json` rendered as a new "Today" tab in the Registry UI, showing today's meetings (collapsed cards) and the ≤3 tasks that need attention.

**Architecture:** A new deterministic generator (`processors/today_brief.py`, no LLM) assembles `brief_today.json` from today's calendar events + a new "due-or-surfaced" registry-task query, and runs Plan 1's attendee provisioning. It's called from the existing `main.py` run (writing via the git-anchored `registry_storage`, committed back by `brief.yml`) and re-readable by the Registry UI. The legacy `pipeline.py` keeps running for its non-email work; the email send is gated off by config.

**Tech Stack:** Python 3, pytest, Flask (`tools/server.py`), vanilla-JS single-file UI (`tools/registry_ui.html`), git-anchored `MainStorage`/`registry_storage`, GitHub Actions (`brief.yml`).

## Global Constraints

- **Storage:** `brief_today.json` and `people_registry.json` are git-anchored registry stores. The generator MUST write them via `lib.storage.registry_storage(config)` (LocalStorage on the working tree), NEVER `build_storage` (R2). Registry key for the brief is `"brief_today.json"` (→ `data/brief_today.json`).
- **Commit-back:** `brief.yml` currently has NO commit-back step. This plan ADDS one that runs `git add data/brief_today.json data/people_registry.json` (+ commit/push), or Actions-generated output is silently discarded. Mirror the commit-back shape used by `ask.yml` / `avoma_sync.yml`.
- **Registry UI reads `origin/main`:** the Today tab reads `brief_today.json` from the in-memory `SNAPSHOT`, populated by `rebuild_snapshot()` via `git show origin/main:data/brief_today.json`. Reads never hit the working tree.
- **`brief_today.json` schema (v1):**
  ```json
  {
    "date": "YYYY-MM-DD",
    "generated_at": "ISO-8601-UTC",
    "meetings": [
      {"id": str, "title": str, "start": "ISO|null", "end": "ISO|null",
       "kind": "internal|external", "attendees": [{"email": str, "name": str}],
       "prep": null}
    ],
    "needs_today": [
      {"id": str, "title": str, "reason": "overdue|due|horizon",
       "due_date": "YYYY-MM-DD|null", "project_id": "str|null"}
    ],
    "what_moved": []
  }
  ```
  `prep` is always `null` in Plan 2 (Plans 3/4 populate it). `what_moved` is always `[]` in Plan 2 (Plan 5 populates it). Both fields are present now for forward-compatibility.
- **Needs-today rules:** union of open tasks that are overdue (`due_date < today`), due today (`due_date == today`), or horizon-arrived (per existing `get_surfaced_tasks`). Rank overdue → due → horizon, then oldest date first. **Hard cap of 3.**
- **Meeting rules:** skip `declined` events. `kind` = "external" if the event has ≥1 attendee whose email is not an internal domain, else "internal". Internal domains from `config["demo_scan"]["internal_domains"]`, default `["teambuildr.com"]`.
- **Kill email:** gate the send in `pipeline.py` behind `config["brief"]["email_enabled"]` (default `False`). Do not delete the send code — gate it, so it's reversible and non-dead.
- **Reuse Plan 1:** provisioning is `processors.attendee_provisioner.provision_from_events`; classification uses `lib.identity.is_internal`. Do not reimplement.
- **Test style:** pytest from repo root. Server tests follow `tests/test_server.py` (mutate `SNAPSHOT` in-place, hit `app.test_client()`). No `conftest.py`.
- **Commits:** frequent, one per task.

## File Structure

- **Create `processors/today_brief.py`** — pure assembler `build_today_brief(...)`, ranker `rank_needs(...)`, meeting mapper `_meeting_dict(...)`, and orchestrator `generate_and_write(...)`.
- **Modify `lib/tasks.py`** — add `get_due_or_surfaced(storage, today=None) -> list`.
- **Modify `main.py`** — call the generator after `collect_signals` (guarded, non-fatal).
- **Modify `pipeline.py`** — gate the email send behind `config["brief"]["email_enabled"]`.
- **Modify `config.json`** — add `"brief": {"email_enabled": false}`.
- **Modify `.github/workflows/brief.yml`** — add commit-back for `data/brief_today.json` + `data/people_registry.json`.
- **Modify `tools/server.py`** — `SNAPSHOT.brief`, populate in `rebuild_snapshot`, `GET /api/brief_today`.
- **Modify `tools/registry_ui.html`** — Today tab (nav button, view container, `switchTab`, `setupTabs`, `renderTodayView`, default to Today on load).
- **Tests:** extend `tests/test_tasks.py`, create `tests/test_today_brief.py`, extend `tests/test_server.py`.

---

## Task 1: `get_due_or_surfaced` query in `lib/tasks.py`

**Files:**
- Modify: `lib/tasks.py` (add one function near `get_surfaced_tasks`, ~line 182)
- Test: `tests/test_tasks.py`

**Interfaces:**
- Consumes: existing `get_open_tasks(storage)`, `get_surfaced_tasks(storage, lookback_days=1)`.
- Produces: `get_due_or_surfaced(storage, today: str | None = None) -> list[dict]` — open tasks that are due/overdue (`due_date <= today`) OR horizon-arrived, unioned by `id`, order not guaranteed (caller ranks).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tasks.py` (mirror how that file constructs a storage + appends task events; if it uses a `LocalStorage(tmp_path)` + `add_task`, follow that):

```python
def test_get_due_or_surfaced_unions_due_overdue_and_horizon(tmp_path):
    from lib.storage import LocalStorage
    from lib import tasks
    storage = LocalStorage(base_dir=str(tmp_path))
    today = "2026-07-29"
    # overdue (due before today)
    t_overdue = tasks.add_task(storage, "overdue task", due_date="2026-07-01")
    # due today
    t_due = tasks.add_task(storage, "due today task", due_date="2026-07-29")
    # horizon arrived today
    t_horizon = tasks.add_task(storage, "horizon task", horizon="2026-07-29")
    # future due -> excluded
    tasks.add_task(storage, "future task", due_date="2026-08-30")
    # future horizon -> excluded
    tasks.add_task(storage, "future horizon", horizon="2026-08-30")
    # no dates -> excluded
    tasks.add_task(storage, "someday task")

    got = tasks.get_due_or_surfaced(storage, today=today)
    ids = {t["id"] for t in got}
    assert t_overdue["id"] in ids
    assert t_due["id"] in ids
    assert t_horizon["id"] in ids
    assert len(got) == 3  # the three future/dateless tasks excluded


def test_get_due_or_surfaced_excludes_completed(tmp_path):
    from lib.storage import LocalStorage
    from lib import tasks
    storage = LocalStorage(base_dir=str(tmp_path))
    t = tasks.add_task(storage, "done overdue", due_date="2026-07-01")
    tasks.complete_task_by_id(storage, t["id"])
    got = tasks.get_due_or_surfaced(storage, today="2026-07-29")
    assert got == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -m pytest tests/test_tasks.py -k due_or_surfaced -v`
Expected: FAIL with `AttributeError: module 'lib.tasks' has no attribute 'get_due_or_surfaced'`.

- [ ] **Step 3: Write minimal implementation**

Add to `lib/tasks.py` (after `get_surfaced_tasks`). Note `date` is already imported at the top of the file (`is_behind_horizon`/`get_surfaced_tasks` use it):

```python
def get_due_or_surfaced(storage, today=None) -> list:
    """Open tasks needing attention today: due today, overdue, or horizon-arrived.

    Union (by id) of:
      - open tasks with due_date <= today
      - open tasks surfaced by get_surfaced_tasks (horizon just arrived)
    Ordering is not guaranteed; the caller ranks/caps.
    """
    if today is None:
        today = date.today().isoformat()
    open_tasks = get_open_tasks(storage)
    surfaced_ids = {t["id"] for t in get_surfaced_tasks(storage)}
    result, seen = [], set()
    for t in open_tasks:
        due = t.get("due_date")
        is_due = bool(due) and due <= today
        if (is_due or t["id"] in surfaced_ids) and t["id"] not in seen:
            result.append(t)
            seen.add(t["id"])
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -m pytest tests/test_tasks.py -v`
Expected: PASS (new tests + existing tasks tests green).

- [ ] **Step 5: Commit**

```bash
git add lib/tasks.py tests/test_tasks.py
git commit -m "feat(tasks): get_due_or_surfaced query (due/overdue + horizon union)"
```

---

## Task 2: `processors/today_brief.py` generator

**Files:**
- Create: `processors/today_brief.py`
- Test: `tests/test_today_brief.py`

**Interfaces:**
- Consumes: `collectors.calendar.CalendarEvent` (`id`, `summary`, `start`, `end`, `attendees`, `attendee_details`, `declined`), `lib.identity.is_internal`, `lib.tasks.get_due_or_surfaced`, `processors.attendee_provisioner.provision_from_events`, a `storage` with `write_json`.
- Produces:
  - `rank_needs(tasks: list[dict], today: str, cap: int = 3) -> list[dict]` — maps to `{id,title,reason,due_date,project_id}`, ranks overdue→due→horizon then oldest-first, caps at `cap`.
  - `_meeting_dict(ev, internal_domains) -> dict`
  - `build_today_brief(events, needs_items, internal_domains, today, generated_at) -> dict`
  - `generate_and_write(config, events, storage, today, generated_at) -> dict` (provisions, computes needs, assembles, writes `brief_today.json`, returns the dict).

- [ ] **Step 1: Write the failing test**

Create `tests/test_today_brief.py`:

```python
from collectors.calendar import CalendarEvent
from processors import today_brief as tb


def _ev(eid, title, details, declined=False):
    from datetime import datetime
    return CalendarEvent(
        id=eid, summary=title,
        start=datetime(2026, 7, 29, 9, 0), end=datetime(2026, 7, 29, 9, 30),
        attendees=[d["email"] for d in details],
        attendee_details=details, declined=declined,
    )


def test_rank_needs_orders_and_caps():
    tasks = [
        {"id": "a", "title": "H", "due_date": None, "horizon": "2026-07-29", "project_id": None},
        {"id": "b", "title": "O", "due_date": "2026-07-01", "project_id": None},
        {"id": "c", "title": "D", "due_date": "2026-07-29", "project_id": None},
        {"id": "d", "title": "O2", "due_date": "2026-06-15", "project_id": None},
    ]
    out = tb.rank_needs(tasks, today="2026-07-29", cap=3)
    assert [x["id"] for x in out] == ["d", "b", "c"]  # overdue(oldest first), then due; horizon dropped by cap
    assert out[0]["reason"] == "overdue" and out[2]["reason"] == "due"


def test_meeting_dict_classifies_external_and_internal():
    ext = tb._meeting_dict(
        _ev("m1", "Acme demo", [{"email": "jane@acme.com", "name": "Jane"},
                                {"email": "q@teambuildr.com", "name": "Quinn"}]),
        ["teambuildr.com"])
    assert ext["kind"] == "external"
    assert ext["prep"] is None
    assert ext["attendees"] == [{"email": "jane@acme.com", "name": "Jane"},
                                {"email": "q@teambuildr.com", "name": "Quinn"}]
    internal = tb._meeting_dict(
        _ev("m2", "Team sync", [{"email": "q@teambuildr.com", "name": "Quinn"}]),
        ["teambuildr.com"])
    assert internal["kind"] == "internal"


def test_build_today_brief_skips_declined_and_shapes_payload():
    events = [
        _ev("m1", "Acme demo", [{"email": "jane@acme.com", "name": "Jane"}]),
        _ev("m2", "Declined call", [{"email": "x@acme.com", "name": "X"}], declined=True),
    ]
    needs = [{"id": "t1", "title": "Ship it", "reason": "due", "due_date": "2026-07-29", "project_id": None}]
    brief = tb.build_today_brief(events, needs, ["teambuildr.com"],
                                 today="2026-07-29", generated_at="2026-07-29T11:00:00Z")
    assert brief["date"] == "2026-07-29"
    assert brief["generated_at"] == "2026-07-29T11:00:00Z"
    assert [m["id"] for m in brief["meetings"]] == ["m1"]  # declined skipped
    assert brief["needs_today"] == needs
    assert brief["what_moved"] == []


def test_generate_and_write_persists_and_provisions(tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    storage.write_json("tasks.jsonl", {})  # not used directly; tasks read via get_open_tasks
    events = [_ev("m1", "Acme demo", [{"email": "jane@acme.com", "name": "Jane Smith"}])]
    config = {"demo_scan": {"internal_domains": ["teambuildr.com"]}}
    brief = tb.generate_and_write(config, events, storage,
                                  today="2026-07-29", generated_at="2026-07-29T11:00:00Z")
    saved = storage.read_json("brief_today.json")
    assert saved["date"] == "2026-07-29"
    assert saved["meetings"][0]["title"] == "Acme demo"
    # provisioning created a stub for the external attendee
    people = storage.read_json("people_registry.json")["people"]
    assert any(p["email"] == "jane@acme.com" for p in people)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -m pytest tests/test_today_brief.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'processors.today_brief'`.

- [ ] **Step 3: Write minimal implementation**

Create `processors/today_brief.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -m pytest tests/test_today_brief.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/today_brief.py tests/test_today_brief.py
git commit -m "feat(today-brief): deterministic brief_today.json generator"
```

---

## Task 3: Wire generator into the run + gate off email

**Files:**
- Modify: `main.py` (`_run_inner`, after `collect_signals`)
- Modify: `pipeline.py` (email-send gate, ~line 931)
- Modify: `config.json` (add `"brief": {"email_enabled": false}`)
- Test: `tests/test_pipeline_email_gate.py` (new, focused)

**Interfaces:**
- Consumes: `processors.today_brief.generate_and_write`, `lib.storage.registry_storage`, `collected.today_events`.
- Produces: side effect — `data/brief_today.json` written each run; email send skipped unless `config["brief"]["email_enabled"]` is true.

- [ ] **Step 1: Write the failing test (email gate)**

Create `tests/test_pipeline_email_gate.py`. This tests the gate decision in isolation without running the whole pipeline:

```python
import pipeline


def test_email_disabled_by_config_default():
    # default config (no brief.email_enabled) -> disabled
    assert pipeline._email_enabled({}) is False
    assert pipeline._email_enabled({"brief": {}}) is False
    assert pipeline._email_enabled({"brief": {"email_enabled": False}}) is False


def test_email_enabled_when_config_true():
    assert pipeline._email_enabled({"brief": {"email_enabled": True}}) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -m pytest tests/test_pipeline_email_gate.py -v`
Expected: FAIL with `AttributeError: module 'pipeline' has no attribute '_email_enabled'`.

- [ ] **Step 3: Implement the gate in `pipeline.py`**

Add this helper near the top of `pipeline.py` (after imports, before the dataclasses):

```python
def _email_enabled(config: dict) -> bool:
    """Email delivery is opt-in; the Today tab replaces the emailed brief."""
    return bool(config.get("brief", {}).get("email_enabled", False))
```

Then change the email-send guard. The current line 931 is:

```python
            if dry_run or no_email:
                _email_status = "skipped"
                print("   (email skipped)")
```

Replace it with:

```python
            if dry_run or no_email or not _email_enabled(config):
                _email_status = "skipped"
                reason = "email skipped" if (dry_run or no_email) else "email disabled by config"
                print(f"   ({reason})")
```

- [ ] **Step 4: Add the config flag**

In `config.json`, add a top-level key (place it near `email`):

```json
  "brief": { "email_enabled": false },
```

(Ensure valid JSON — add the comma appropriately relative to surrounding keys.)

- [ ] **Step 5: Wire the generator into `main.py`**

In `main.py`, `_run_inner`, immediately after `collected = collect_signals(config, health, storage)` (line 46) and before `ctx = process_context(...)`, add a guarded generation step. Add the imports at the top of `_run_inner`'s body alongside the existing `from datetime import ...`:

```python
        # Pre-compute the Today brief (git-anchored) — non-fatal.
        try:
            from lib.storage import registry_storage
            from processors.today_brief import generate_and_write
            generate_and_write(
                config,
                collected.today_events,
                registry_storage(config),
                today=date.today().isoformat(),
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
            print("   ✅ brief_today.json generated")
        except Exception as e:
            print(f"⚠️ Today-brief generation error (non-fatal): {e}", file=sys.stderr)
```

(`date`, `datetime`, `timezone` are already imported at the top of `_run_inner`; `sys` is imported at module top.)

- [ ] **Step 6: Run tests + a smoke check**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -m pytest tests/test_pipeline_email_gate.py -v && python3 -c "import json; json.load(open('config.json')); print('config.json valid')"`
Expected: gate tests PASS; `config.json valid` prints (no JSON error).

- [ ] **Step 7: Commit**

```bash
git add main.py pipeline.py config.json tests/test_pipeline_email_gate.py
git commit -m "feat(brief): generate brief_today.json in run; gate email behind config (default off)"
```

---

## Task 4: Commit-back in `brief.yml`

**Files:**
- Modify: `.github/workflows/brief.yml`
- Test: manual YAML validation (verification below)

**Interfaces:**
- Produces: after `python main.py`, the workflow commits `data/brief_today.json` and `data/people_registry.json` to `origin/main`.

- [ ] **Step 1: Inspect the current workflow and a reference commit-back**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && cat .github/workflows/brief.yml && echo "=== reference ===" && sed -n '55,75p' .github/workflows/ask.yml`
Expected: see `brief.yml` (ends after `run: python main.py`) and `ask.yml`'s commit-back block to mirror (git config user, `git add`, `git commit`/`diff --cached` guard, `git push`).

- [ ] **Step 2: Add the commit-back step**

Append a step to `brief.yml` after the `python main.py` step (match the indentation and the auth/push pattern used by `ask.yml`; the reference block from Step 1 is the source of truth for the exact `git config` / push syntax). The step must:

```yaml
      - name: Commit brief_today.json + provisioned people
        if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/brief_today.json data/people_registry.json
          if git diff --cached --quiet; then
            echo "No brief/people changes to commit."
          else
            git commit -m "chore(brief): update brief_today.json + provisioned people [skip ci]"
            git push
          fi
```

If `ask.yml`'s reference block uses a different push invocation (e.g. an explicit `origin HEAD:main` or a token), match THAT verbatim instead of `git push` — the reference is authoritative for this repo's Actions auth.

- [ ] **Step 3: Verify YAML parses**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/brief.yml')); print('brief.yml valid YAML')"`
Expected: `brief.yml valid YAML` (if PyYAML isn't installed, run `python3 -c "import json"` is not applicable — instead visually confirm indentation matches the sibling steps).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/brief.yml
git commit -m "ci(brief): commit brief_today.json + provisioned people back to main"
```

---

## Task 5: `GET /api/brief_today` endpoint

**Files:**
- Modify: `tools/server.py` (`_Snapshot.__init__` ~line 37; `rebuild_snapshot` ~line 71; a new route near the other GETs)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `MainStorage.read_json` via the existing snapshot mechanism.
- Produces: `SNAPSHOT.brief` (dict) and `GET /api/brief_today` returning it as JSON.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py` (mirror the existing pattern — set `SNAPSHOT` field, hit the client):

```python
def test_brief_today_endpoint_returns_snapshot():
    import json
    from tools.server import app, SNAPSHOT
    SNAPSHOT.brief = {
        "date": "2026-07-29",
        "generated_at": "2026-07-29T11:00:00Z",
        "meetings": [{"id": "m1", "title": "Acme demo", "kind": "external",
                      "attendees": [], "prep": None, "start": None, "end": None}],
        "needs_today": [],
        "what_moved": [],
    }
    resp = app.test_client().get("/api/brief_today")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["date"] == "2026-07-29"
    assert body["meetings"][0]["title"] == "Acme demo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -m pytest tests/test_server.py -k brief_today -v`
Expected: FAIL — either `AttributeError` on `SNAPSHOT.brief` or 404 on the route.

- [ ] **Step 3: Implement**

In `tools/server.py`:

(a) In `_Snapshot.__init__`, add alongside the other dataset fields:
```python
        self.brief = {}
```

(b) In `rebuild_snapshot`, add alongside the other `SNAPSHOT.* = store.read_json(...)` lines:
```python
    SNAPSHOT.brief = store.read_json("brief_today.json", default={})
```

(c) Add the route near the other GET routes (e.g. after `list_people`):
```python
@app.route("/api/brief_today", methods=["GET"])
def get_brief_today():
    return jsonify(SNAPSHOT.brief)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 -m pytest tests/test_server.py -v`
Expected: PASS (new test + existing server tests green).

- [ ] **Step 5: Commit**

```bash
git add tools/server.py tests/test_server.py
git commit -m "feat(server): GET /api/brief_today from origin/main snapshot"
```

---

## Task 6: Today tab in `tools/registry_ui.html`

**Files:**
- Modify: `tools/registry_ui.html` (nav ~line 1032; view containers ~line 1040; `switchTab` ~line 1892; `setupTabs` ~line 3113; new `renderTodayView`; `init` default view ~line 3052)
- Test: browser smoke (verification below — HTML/JS isn't unit-tested; the endpoint is covered by Task 5).

**Interfaces:**
- Consumes: `GET /api/brief_today` (Task 5).
- Produces: a "Today" tab that renders meetings as collapsed cards (expand shows a "No prep yet" placeholder — Plans 3/4 fill it) and the needs-today list; a Refresh button that re-pulls main.

- [ ] **Step 1: Add the nav button (make Today the first/leftmost tab)**

In the `<nav class="tabs">` block, add as the FIRST button:
```html
    <button class="tab active" data-view="today">Today</button>
```
and remove `active` from the previously-first button (`data-view="pending"`), so exactly one tab is active.

- [ ] **Step 2: Add the view container**

In `<main>`, add as the first view (and unhide it; hide the previously-visible pending view):
```html
    <div id="view-today" class="view"></div>
```
Change the existing `<div id="view-pending" class="view">` to `<div id="view-pending" class="view hidden">`.

- [ ] **Step 3: Register the view in `switchTab`**

Add `'today'` to the front of the array in `switchTab`:
```javascript
  ['today','pending','registry','observations','work','notes','meetings'].forEach(v => {
    el(`view-${v}`).classList.toggle('hidden', v !== name);
  });
```

- [ ] **Step 4: Wire the click dispatch in `setupTabs`**

Add to the `setupTabs` click handler:
```javascript
      if (view === 'today') renderTodayView();
```

- [ ] **Step 5: Implement `renderTodayView` (mirror `renderMeetingsView`)**

Add this function near `renderMeetingsView`:
```javascript
async function renderTodayView() {
  const view = el('view-today');
  view.innerHTML = '<div class="muted" style="padding:20px">Loading…</div>';
  let brief;
  try {
    brief = await fetchJSON(`${API}/api/brief_today`);
  } catch {
    view.innerHTML = `<div class="empty-state"><h3>Server Offline</h3><p>Run: python tools/server.py</p></div>`;
    return;
  }
  if (!brief || !brief.date) {
    view.innerHTML = `<div class="empty-state"><h3>No brief yet</h3><p>The morning run hasn't generated today's brief.</p></div>`;
    return;
  }
  const meetings = brief.meetings || [];
  const needs = brief.needs_today || [];

  const meetingsHtml = meetings.length ? meetings.map((m, i) => {
    const time = m.start ? new Date(m.start).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}) : '';
    const who = (m.attendees || []).map(a => esc(a.name || a.email)).join(', ');
    return `<div class="today-mtg" data-idx="${i}">
      <div class="today-mtg-head">
        <span class="today-mtg-time">${esc(time)}</span>
        <span class="today-mtg-title">${esc(m.title || '(no title)')}</span>
        <span class="today-mtg-kind">${esc(m.kind)}</span>
      </div>
      <div class="today-mtg-prep hidden">
        ${m.prep ? esc(JSON.stringify(m.prep)) : '<span class="muted">No prep yet.</span>'}
        ${who ? `<div class="muted" style="margin-top:6px">${who}</div>` : ''}
      </div>
    </div>`;
  }).join('') : '<div class="muted">No meetings today.</div>';

  const needsHtml = needs.length ? needs.map(n =>
    `<li><span class="today-need-reason">${esc(n.reason)}</span> ${esc(n.title)}</li>`
  ).join('') : '<li class="muted">Nothing due.</li>';

  const gen = brief.generated_at ? new Date(brief.generated_at).toLocaleString() : '';
  view.innerHTML = `
    <div class="today-header">
      <h2>Today — ${esc(brief.date)}</h2>
      <button id="today-refresh" class="btn-secondary">Refresh</button>
      <span class="muted" style="margin-left:8px">generated ${esc(gen)}</span>
    </div>
    <section><h3>Meetings</h3>${meetingsHtml}</section>
    <section><h3>Needs you today</h3><ul class="today-needs">${needsHtml}</ul></section>
  `;
  view.querySelectorAll('.today-mtg-head').forEach(head => {
    head.addEventListener('click', () => head.nextElementSibling.classList.toggle('hidden'));
  });
  el('today-refresh').addEventListener('click', async () => {
    await refreshFromMain();
    renderTodayView();
  });
}
```

- [ ] **Step 6: Make Today the default view on load**

In `init()`, where it renders the initial view in server mode (currently the Pending view), render Today instead:
```javascript
    switchTab('today');
    renderTodayView();
```
(Place this where the existing initial-render call is; keep `setupTabs()` being called. If `init` currently calls a pending render explicitly, replace that call — do not render both.)

- [ ] **Step 7: Add minimal styles**

Near the other component styles in the `<style>` block, add:
```css
    .today-mtg { border: 1px solid var(--border, #333); border-radius: 6px; margin: 6px 0; }
    .today-mtg-head { display: flex; gap: 10px; align-items: center; padding: 8px 12px; cursor: pointer; }
    .today-mtg-time { font-variant-numeric: tabular-nums; opacity: .8; }
    .today-mtg-title { font-weight: 600; flex: 1; }
    .today-mtg-kind { font-size: 11px; text-transform: uppercase; opacity: .6; }
    .today-mtg-prep { padding: 0 12px 10px; }
    .today-header { display: flex; align-items: center; gap: 8px; }
    .today-needs { list-style: none; padding-left: 0; }
    .today-need-reason { display: inline-block; min-width: 62px; font-size: 11px; text-transform: uppercase; opacity: .7; }
```
(If the stylesheet uses different variable names for border/muted, match the existing convention rather than inventing `--border`.)

- [ ] **Step 8: Browser smoke verification**

Start the server and confirm the tab renders. Seed a `brief_today.json` on `origin/main` is NOT required for the smoke — with no brief, the empty-state must show cleanly.
1. Start the Registry UI (`registry-ui` skill or `python3 tools/server.py`).
2. Open `http://localhost:8787`. Confirm: the **Today** tab is leftmost and active on load; with no brief it shows the "No brief yet" empty state (not a JS error); switching to other tabs and back works.
3. Check the browser console for errors (there must be none from `renderTodayView`).
Capture a screenshot for the report.

- [ ] **Step 9: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(ui): Today tab — meetings cards + needs-today, default view"
```

---

## Self-Review

**Spec coverage (against `2026-07-29-daily-brief-redesign-design.md` → tab layout ①/②, generation, kill email):**
- ① Meetings today, one line each, external+configured-internal as collapsed cards → Task 2 (`_meeting_dict`, `kind`) + Task 6 (collapsed cards, expand). Internal-meeting *prep recipes* are Plan 4; Plan 2 renders every meeting as a card with a `prep=null` placeholder. ✅
- ② Needs you today, ≤3 due/at-risk, "nothing due" when empty → Task 1 (`get_due_or_surfaced`) + Task 2 (`rank_needs` cap 3) + Task 6 ("Nothing due"). ✅
- ③ What moved → deferred to Plan 5; `what_moved: []` present for forward-compat. ✅ (explicitly out of scope here)
- Pre-computed in the ~7am run, committed to `origin/main`, read by the UI → Task 3 (main.py wiring) + Task 4 (commit-back) + Task 5 (endpoint) + Task 6 (render). ✅
- Kill the email send → Task 3 (config gate, default off). ✅
- Registry-storage-not-R2 → Task 2 writes via injected `storage`; Task 3 injects `registry_storage(config)`; Global Constraints. ✅
- Provisioning runs in the morning run → Task 2 `generate_and_write` calls `provision_from_events`; Task 4 commits `people_registry.json` (the carry-forward the Plan 1 review flagged). ✅

**Deferred / out of scope (documented):** true server-side recompute on Refresh (Plan 2 Refresh re-pulls main — a deliberate trim to avoid coupling Flask to Google/Claude auth before there's LLM prep to recompute); external meeting prep content (Plan 3); internal prep recipes (Plan 4); "what moved" (Plan 5).

**Placeholder scan:** none — every code step contains complete code and exact commands. Task 4 Step 2 intentionally defers to `ask.yml`'s exact push syntax as the authoritative reference (the implementer reads it in Step 1), rather than guessing this repo's Actions auth.

**Type consistency:** `generate_and_write(config, events, storage, today, generated_at)` matches the `main.py` call in Task 3; `build_today_brief(events, needs_items, internal_domains, today, generated_at)` and `rank_needs(task_list, today, cap)` are consistent between Task 2's code and tests; `brief_today.json` schema identical across Global Constraints, Task 2, Task 5 test, and Task 6 render; `SNAPSHOT.brief` consistent across Task 5 (a)/(b)/(c) and its test.
```
