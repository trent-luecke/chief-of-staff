# Parse Internal Meeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill that parses internal team-meeting transcripts from Trent's seat — bucketing action items, filtering noise, and writing approved results into the meeting registry (sessions/threads/tasks/notes/decisions) via the Registry server's origin/main write path.

**Architecture:** A markdown reference-frame skill (`SKILL.md`) drives in-context parsing and a review loop; on approval it invokes a thin Python orchestrator (`scripts/meeting_writeback.py`) that POSTs approved items to the Registry server (`http://localhost:8787`). Using the server's HTTP endpoints (not direct file writes) is deliberate: the server's `_write_main` commits every write to `origin/main` through a throwaway worktree, so writes land where the Registry UI reads regardless of the local working-tree branch. The only missing write primitive — appending to `decisions.md` — is added as a new endpoint.

**Tech Stack:** Python 3, Flask (existing `tools/server.py`), `requests`, pytest, vanilla JS (`tools/registry_ui.html`). Storage via `lib.storage` / `lib.main_storage` (rooted at `data/`).

## Global Constraints

- Registry writes MUST go through the Registry server HTTP API (which uses `_write_main` → `origin/main`). NEVER write registry files directly from the session working tree, and NEVER use `build_storage` (R2) for registry stores.
- Task/meeting/note record shapes MUST match the existing server endpoints exactly (see `tools/server.py`).
- `owner` is the action-vs-monitor axis: `owner` = Trent's person_id for his commitments; `owner` = the other person's id for owed-to-me and team tasks. Set `owner` on every task write.
- One-off meetings MUST NOT create a meeting record (nothing in the Meetings tab); their summary goes to a `MEETING_NOTES`-tagged note and every action item becomes a Work-tab task.
- Recurring meetings reuse-or-create a meeting series; summary → session, loops → threads, commitments → thread promoted to task.
- Any ambiguity about which meeting a transcript ties to is a HARD STOP: the skill asks Trent to pick/name/declare; it never auto-creates a series or guesses.
- `decisions.md` entries use the existing format: one line per entry, `YYYY-MM-DD: <text>`.
- `MEETING_NOTES` tag id is exactly `MEETING_NOTES`; color `#6b7280`.
- Follow existing test patterns: `tmp_path` + `LocalStorage` for storage logic; mock `requests` for HTTP orchestration.

---

## File Structure

- `lib/decisions.py` (**create**) — `append_decision(storage, text, date_str)`: appends a dated line to `memory/decisions.md`. Single responsibility: the decisions-file write primitive.
- `tools/server.py` (**modify**) — add `POST /api/decisions` endpoint calling `lib.decisions.append_decision` via `_write_main`.
- `scripts/meeting_writeback.py` (**create**) — orchestrator: reads an approved-items JSON, POSTs to the server endpoints per the recurring/one-off path, prints a confirmation summary. No parsing judgment.
- `tests/test_decisions.py` (**create**) — unit tests for `append_decision`.
- `tests/test_meeting_writeback.py` (**create**) — unit tests for the orchestrator with mocked `requests`.
- `data/notes_tags.json` (**modify, via API**) — register the `MEETING_NOTES` tag.
- `tools/registry_ui.html` (**modify**) — hide `MEETING_NOTES` notes by default with a "Show meeting notes" toggle.
- `.claude/skills/parse-internal-meeting/SKILL.md` (**create**) — the reference frame that ties it together.

---

## Task 1: `decisions.md` write primitive + endpoint

**Files:**
- Create: `lib/decisions.py`
- Create: `tests/test_decisions.py`
- Modify: `tools/server.py` (add `POST /api/decisions` near the notes endpoints, ~line 535)

**Interfaces:**
- Produces: `lib.decisions.append_decision(storage, text: str, date_str: str) -> str` — appends the line `f"{date_str}: {text}"` to `memory/decisions.md` and returns the line written.
- Produces: `POST /api/decisions` — body `{"text": str, "date": "YYYY-MM-DD" (optional, defaults to today UTC)}`; returns `{"decision": "<line>", "push": {...}}` on 200/201, error+`push` on 5xx (mirrors `create_note`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decisions.py
from lib.storage import LocalStorage
from lib.decisions import append_decision


def test_append_decision_appends_dated_line(tmp_path):
    storage = LocalStorage(str(tmp_path))
    # seed an existing decisions file (no trailing newline) to prove append behavior
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "decisions.md").write_text("2026-01-01: existing decision", encoding="utf-8")

    line = append_decision(storage, "Ship parse-internal-meeting skill", "2026-07-23")

    assert line == "2026-07-23: Ship parse-internal-meeting skill"
    content = (tmp_path / "memory" / "decisions.md").read_text(encoding="utf-8")
    assert content.splitlines()[-1] == "2026-07-23: Ship parse-internal-meeting skill"
    # existing content preserved
    assert content.splitlines()[0] == "2026-01-01: existing decision"


def test_append_decision_creates_file_when_missing(tmp_path):
    storage = LocalStorage(str(tmp_path))
    line = append_decision(storage, "First decision", "2026-07-23")
    assert line == "2026-07-23: First decision"
    content = (tmp_path / "memory" / "decisions.md").read_text(encoding="utf-8")
    assert "2026-07-23: First decision" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_decisions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.decisions'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/decisions.py
"""Write primitive for the durable decisions log (data/memory/decisions.md).

Format: one line per entry, "YYYY-MM-DD: <text>". Storage is anything with
.read(key) and .append_line(key, line) rooted at data/ (LocalStorage or
MainStorage). Caller is responsible for committing.
"""
from __future__ import annotations

DECISIONS_KEY = "memory/decisions.md"


def append_decision(storage, text: str, date_str: str) -> str:
    line = f"{date_str}: {text}"
    storage.append_line(DECISIONS_KEY, line)
    return line
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_decisions.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add the endpoint**

In `tools/server.py`, immediately before the `# --- Notes Tags ---` comment (~line 533), add:

```python
# --- Decisions ---

@app.route("/api/decisions", methods=["POST"])
def create_decision():
    body = request.get_json(force=True)
    if not body or not body.get("text"):
        return jsonify({"error": "text is required"}), 400
    date_str = body.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    line, push, status = _write_main(
        lambda store: decisions_lib.append_decision(store, body["text"], date_str),
        lambda ln: f"data: append decision {date_str}",
    )
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    return jsonify({"decision": line, "push": push}), 201
```

Add the import near the other `lib` imports (~line 27, after `import lib.meetings as meetings_lib`):

```python
import lib.decisions as decisions_lib
```

- [ ] **Step 6: Verify the endpoint imports cleanly**

Run: `python -c "import tools.server"`
Expected: no output, exit 0 (module imports without error)

- [ ] **Step 7: Commit**

```bash
git add lib/decisions.py tests/test_decisions.py tools/server.py
git commit -m "feat: decisions.md append primitive + POST /api/decisions endpoint"
```

---

## Task 2: `meeting_writeback.py` orchestrator

**Files:**
- Create: `scripts/meeting_writeback.py`
- Create: `tests/test_meeting_writeback.py`

**Interfaces:**
- Consumes: Registry server endpoints — `POST /api/meetings`, `POST /api/meetings/<id>/sessions`, `POST /api/meetings/<id>/threads`, `POST /api/meetings/<id>/threads/<tid>/promote`, `POST /api/tasks`, `POST /api/notes`, `POST /api/decisions` (Task 1).
- Produces: `meeting_writeback.write_back(payload: dict, base_url: str = "http://localhost:8787") -> dict` — performs the writes and returns a summary dict `{"created": [<human-readable strings>], "errors": [<strings>]}`.
- Produces: the **approved-items payload schema** (built by the skill, consumed here):

```json
{
  "meeting": {
    "kind": "recurring" | "oneoff",
    "meeting_id": "marketing_sync",
    "name": "Marketing Sync",
    "people_ids": ["nicole-x", "rachel-y"],
    "date": "2026-07-23"
  },
  "summary": "Headline + summary + FYI/status context as one body string.",
  "commitments": [{"text": "Send Nicole the Q3 deck", "owner": "trent-luecke"}],
  "owed_to_me":  [{"text": "Rachel to confirm ad budget", "owner": "rachel-y"}],
  "team_tasks":  [{"text": "Nicole to draft campaign brief", "owner": "nicole-x"}],
  "decisions":   ["Retro Miami Vice aesthetic confirmed for summer campaign"]
}
```

For `kind: "recurring"`, `meeting_id` is the existing series slug when known; if empty/absent the orchestrator creates the series from `name`+`people_ids` and uses the returned id. For `kind: "oneoff"`, `meeting_id`/series are never created.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meeting_writeback.py
import json
from unittest.mock import patch, MagicMock

from scripts import meeting_writeback


def _resp(payload, status=201):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload
    m.raise_for_status = MagicMock()
    return m


def test_oneoff_writes_note_tasks_and_decisions():
    payload = {
        "meeting": {"kind": "oneoff", "name": "Impromptu Sync",
                    "people_ids": [], "date": "2026-07-23"},
        "summary": "Talked pricing.",
        "commitments": [{"text": "Send recap", "owner": "trent-luecke"}],
        "owed_to_me": [{"text": "Rachel confirms budget", "owner": "rachel-y"}],
        "team_tasks": [{"text": "Nicole drafts brief", "owner": "nicole-x"}],
        "decisions": ["Hold pricing flat for Q3"],
    }
    with patch("scripts.meeting_writeback.requests.post") as post:
        post.side_effect = [
            _resp({"note": {"id": "n-1"}}),        # POST /api/notes
            _resp({"task": {"id": "t-1"}}),        # commitment task
            _resp({"task": {"id": "t-2"}}),        # owed_to_me task
            _resp({"task": {"id": "t-3"}}),        # team task
            _resp({"decision": "2026-07-23: Hold pricing flat for Q3"}),  # decision
        ]
        summary = meeting_writeback.write_back(payload, base_url="http://x")

    urls = [c.args[0] for c in post.call_args_list]
    assert urls == [
        "http://x/api/notes",
        "http://x/api/tasks",
        "http://x/api/tasks",
        "http://x/api/tasks",
        "http://x/api/decisions",
    ]
    # note tagged MEETING_NOTES
    assert post.call_args_list[0].kwargs["json"]["tags"] == ["MEETING_NOTES"]
    # every task carries its owner
    assert post.call_args_list[1].kwargs["json"]["owner"] == "trent-luecke"
    assert post.call_args_list[2].kwargs["json"]["owner"] == "rachel-y"
    assert post.call_args_list[3].kwargs["json"]["owner"] == "nicole-x"
    assert len(summary["created"]) == 5
    assert summary["errors"] == []


def test_recurring_creates_session_threads_and_promotes_commitment():
    payload = {
        "meeting": {"kind": "recurring", "meeting_id": "marketing_sync",
                    "name": "Marketing Sync", "people_ids": ["nicole-x"],
                    "date": "2026-07-23"},
        "summary": "Weekly marketing sync.",
        "commitments": [{"text": "Send deck", "owner": "trent-luecke"}],
        "owed_to_me": [{"text": "Rachel budget", "owner": "rachel-y"}],
        "team_tasks": [],
        "decisions": [],
    }
    with patch("scripts.meeting_writeback.requests.post") as post:
        post.side_effect = [
            _resp({"meeting": {"id": "marketing_sync"}}),               # add session
            _resp({"meeting": {"threads": [{"thread_id": "th-1"}]}}),   # commitment thread
            _resp({"task": {"id": "t-9"}}),                             # promote commitment
            _resp({"meeting": {"threads": [{"thread_id": "th-2"}]}}),   # owed_to_me thread
        ]
        summary = meeting_writeback.write_back(payload, base_url="http://x")

    urls = [c.args[0] for c in post.call_args_list]
    assert urls == [
        "http://x/api/meetings/marketing_sync/sessions",
        "http://x/api/meetings/marketing_sync/threads",
        "http://x/api/meetings/marketing_sync/threads/th-1/promote",
        "http://x/api/meetings/marketing_sync/threads",
    ]
    # commitment thread carries person_id = owner
    assert post.call_args_list[1].kwargs["json"]["person_id"] == "trent-luecke"
    assert summary["errors"] == []


def test_recurring_creates_series_when_meeting_id_absent():
    payload = {
        "meeting": {"kind": "recurring", "meeting_id": "", "name": "New Sync",
                    "people_ids": ["nicole-x"], "date": "2026-07-23"},
        "summary": "First occurrence.",
        "commitments": [], "owed_to_me": [], "team_tasks": [], "decisions": [],
    }
    with patch("scripts.meeting_writeback.requests.post") as post:
        post.side_effect = [
            _resp({"id": "new_sync"}),                    # create meeting
            _resp({"meeting": {"id": "new_sync"}}),       # add session
        ]
        summary = meeting_writeback.write_back(payload, base_url="http://x")

    urls = [c.args[0] for c in post.call_args_list]
    assert urls[0] == "http://x/api/meetings"
    assert urls[1] == "http://x/api/meetings/new_sync/sessions"
    assert summary["errors"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_meeting_writeback.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.meeting_writeback'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/meeting_writeback.py
"""Orchestrate approved internal-meeting items into the Registry via HTTP.

The Registry server (tools/server.py, default http://localhost:8787) commits
every write to origin/main, so this must run against a RUNNING server. This
module contains NO parsing judgment — it just maps an approved-items payload
to endpoint calls. See docs/superpowers/plans/2026-07-23-parse-internal-meeting.md
for the payload schema.
"""
from __future__ import annotations

import json
import sys

import requests

MEETING_NOTES_TAG = "MEETING_NOTES"
TIMEOUT = 30


def _post(base_url: str, path: str, body: dict) -> dict:
    resp = requests.post(f"{base_url}{path}", json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def write_back(payload: dict, base_url: str = "http://localhost:8787") -> dict:
    created: list[str] = []
    errors: list[str] = []
    mtg = payload["meeting"]
    date = mtg.get("date")

    try:
        if mtg["kind"] == "oneoff":
            _oneoff(base_url, payload, mtg, date, created)
        else:
            _recurring(base_url, payload, mtg, date, created)
        for text in payload.get("decisions", []):
            out = _post(base_url, "/api/decisions", {"text": text, "date": date})
            created.append(f"decision: {out['decision']}")
    except requests.RequestException as e:
        errors.append(str(e))

    return {"created": created, "errors": errors}


def _source(mtg: dict) -> str:
    return f"meeting-{mtg.get('name', 'internal')}-{mtg.get('date', '')}"


def _oneoff(base_url, payload, mtg, date, created):
    body = f"# {mtg.get('name', 'Meeting')} — {date}\n\n{payload.get('summary', '')}"
    note = _post(base_url, "/api/notes", {"body": body, "tags": [MEETING_NOTES_TAG]})
    created.append(f"note {note['note']['id']} (MEETING_NOTES)")
    for bucket in ("commitments", "owed_to_me", "team_tasks"):
        for item in payload.get(bucket, []):
            task = _post(base_url, "/api/tasks", {
                "title": item["text"], "owner": item.get("owner"),
                "source": _source(mtg),
            })
            created.append(f"task {task['task']['id']} ({bucket}, owner={item.get('owner')})")


def _recurring(base_url, payload, mtg, date, created):
    meeting_id = mtg.get("meeting_id")
    if not meeting_id:
        made = _post(base_url, "/api/meetings", {
            "name": mtg["name"], "people_ids": mtg.get("people_ids", []),
            "calendar_pattern": "",
        })
        meeting_id = made["id"]
        created.append(f"meeting series {meeting_id}")

    _post(base_url, f"/api/meetings/{meeting_id}/sessions",
          {"date": date, "body": payload.get("summary", "")})
    created.append(f"session on {meeting_id} ({date})")

    # commitments: thread owned by Trent, then promoted to a task
    for item in payload.get("commitments", []):
        doc = _post(base_url, f"/api/meetings/{meeting_id}/threads",
                    {"text": item["text"], "person_id": item.get("owner")})
        thread_id = doc["meeting"]["threads"][-1]["thread_id"]
        _post(base_url, f"/api/meetings/{meeting_id}/threads/{thread_id}/promote", {})
        created.append(f"thread {thread_id} + task (commitment)")

    # owed-to-me and team tasks: stay as threads (person_id = owner)
    for bucket in ("owed_to_me", "team_tasks"):
        for item in payload.get(bucket, []):
            doc = _post(base_url, f"/api/meetings/{meeting_id}/threads",
                        {"text": item["text"], "person_id": item.get("owner")})
            thread_id = doc["meeting"]["threads"][-1]["thread_id"]
            created.append(f"thread {thread_id} ({bucket})")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m scripts.meeting_writeback <payload.json> [base_url]", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        payload = json.load(f)
    base_url = argv[1] if len(argv) > 1 else "http://localhost:8787"
    summary = write_back(payload, base_url=base_url)
    print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Ensure `scripts/` is a package (needed for `from scripts import ...`)**

Run: `test -f scripts/__init__.py && echo exists || touch scripts/__init__.py`
Expected: prints `exists` OR creates the file silently. (Only `git add` it in Step 6 if newly created.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_meeting_writeback.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add scripts/meeting_writeback.py tests/test_meeting_writeback.py
git add scripts/__init__.py 2>/dev/null || true
git commit -m "feat: meeting_writeback orchestrator (recurring + one-off paths)"
```

---

## Task 3: `MEETING_NOTES` tag + Notes UI default-hidden toggle

This task has no unit test (no JS test harness in the repo); it is verified by observation in the browser preview, with explicit expected results.

**Files:**
- Modify: `data/notes_tags.json` (via the running server's tag API — do NOT hand-edit the working-tree file, per Global Constraints)
- Modify: `tools/registry_ui.html` (`notesState` init ~line 3128; filter in `renderNotesView` ~line 3290; header bar ~line 3352; wiring ~line 3389)

**Interfaces:**
- Produces: a `MEETING_NOTES` tag record (`{"id": "MEETING_NOTES", "color": "#6b7280"}`) in `notes_tags.json`.
- Produces: `notesState.showMeetingNotes` (bool, default `false`) and a "Show meeting notes" toggle button in the Notes header.

- [ ] **Step 1: Start the Registry server**

Run: `python tools/server.py` (runs on port 8787). Leave it running in a background terminal.
Expected: server logs show it listening; `curl -s http://localhost:8787/api/notes/tags` returns the current tag list JSON.

- [ ] **Step 2: Register the `MEETING_NOTES` tag via the API**

Run:
```bash
curl -s -X POST http://localhost:8787/api/notes/tags \
  -H 'Content-Type: application/json' \
  -d '{"id": "MEETING_NOTES", "color": "#6b7280"}'
```
Expected: `{"tag": {"id": "MEETING_NOTES", "color": "#6b7280"}}` with HTTP 201. The endpoint (`create_note_tag`, `tools/server.py:540`) uppercases the `id` and commits `notes_tags.json` to origin/main. If it returns HTTP 409 `{"error": "tag already exists"}`, the tag is already registered — proceed. Confirm with `curl -s http://localhost:8787/api/notes/tags` — `MEETING_NOTES` is present.

- [ ] **Step 3: Add `showMeetingNotes` to `notesState`**

In `tools/registry_ui.html`, in the `notesState` object (~line 3128), add the flag after `showTagMgmt: false,`:

```javascript
  showTagMgmt: false,
  showMeetingNotes: false,
```

- [ ] **Step 4: Exclude `MEETING_NOTES` notes by default in the filter**

In `renderNotesView`, inside the `notes.filter(...)` callback (~line 3290), add this as the FIRST check inside the callback (before the search check):

```javascript
  let filtered = notes.filter(n => {
    if (!notesState.showMeetingNotes && (n.tags || []).includes('MEETING_NOTES')) return false;
    if (notesState.search) {
```

- [ ] **Step 5: Add the toggle button to the header bar**

In the `view.innerHTML` header template (~line 3358), add a button after the compact button:

```javascript
      <button class="notes-compact-btn${notesState.compact ? ' active' : ''}" id="notes-compact-btn">Compact</button>
      <button class="notes-compact-btn${notesState.showMeetingNotes ? ' active' : ''}" id="notes-meeting-toggle-btn">Show meeting notes</button>
```

- [ ] **Step 6: Wire the toggle**

In the "Wire header controls" block (~line 3389), after the `notes-compact-btn` listener, add:

```javascript
  el('notes-compact-btn').addEventListener('click', () => {
    notesState.compact = !notesState.compact;
    renderNotesView();
  });
  el('notes-meeting-toggle-btn').addEventListener('click', () => {
    notesState.showMeetingNotes = !notesState.showMeetingNotes;
    renderNotesView();
  });
```

- [ ] **Step 7: Create a test MEETING_NOTES note and verify hide/show behavior**

Create a note tagged `MEETING_NOTES` via the API:
```bash
curl -s -X POST http://localhost:8787/api/notes \
  -H 'Content-Type: application/json' \
  -d '{"body": "TEST meeting-notes visibility", "tags": ["MEETING_NOTES"]}'
```

Then in the browser preview open the Registry UI Notes view and verify:
- Expected (default): the "TEST meeting-notes visibility" note is NOT visible.
- Click "Show meeting notes": the note appears; the button shows the active state.
- Click again: the note disappears.
- A note WITHOUT the tag stays visible in both states.

Verify via the preview workflow: `preview_start` the registry UI, `read_page` the Notes view to confirm the test note's absence/presence, and screenshot the toggled-on state.

- [ ] **Step 8: Delete the test note (cleanup)**

Find its id (`curl -s http://localhost:8787/api/notes` → locate the TEST note id), then:
```bash
curl -s -X DELETE http://localhost:8787/api/notes/<note_id>
```
Expected: `{"deleted": "<note_id>", ...}`.

- [ ] **Step 9: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: hide MEETING_NOTES notes by default with a Show-meeting-notes toggle"
```

(Note: `data/notes_tags.json` is committed to `origin/main` by the server's tag-create call in Step 2 — it is NOT staged here.)

---

## Task 4: `parse-internal-meeting` SKILL.md

This task creates the reference frame. It is verified by a scripted walkthrough on a sample transcript, not a unit test — the deliverable is a markdown playbook whose correctness is its instructions.

**Files:**
- Create: `.claude/skills/parse-internal-meeting/SKILL.md`

**Interfaces:**
- Consumes: `scripts/meeting_writeback.py::write_back` (via `python -m scripts.meeting_writeback <payload.json>`), the Registry server endpoints `GET /api/bootstrap` (people + meetings list for resolution), and the payload schema from Task 2.

- [ ] **Step 1: Write the SKILL.md**

Create `.claude/skills/parse-internal-meeting/SKILL.md` with this content:

````markdown
---
name: parse-internal-meeting
description: Use when Trent drops an INTERNAL team-meeting transcript (Slack huddle / Loom recording) and wants it parsed into action items, decisions, and a summary — e.g. "parse my huddle with Nicole and Rachel", "here's the marketing sync transcript", "process this internal meeting". NOT for external customer/prospect calls (use query-avoma) and NOT for looking up existing recordings.
---

# Parse Internal Meeting

Parse an internal team-meeting transcript from Trent's seat: bucket what matters to him,
filter noise, review with him, then write approved items to the registry.

Spec: `docs/superpowers/specs/2026-07-23-parse-internal-meeting-design.md`.

## Scope

INTERNAL team meetings only (Trent + colleagues: Nicole, Rachel, Luke, Teofe, Quinn, etc.).
For external customer/prospect calls, stop and use `query-avoma` instead.

## Step 1 — Get the input

You need two things:
1. The transcript (pasted, or a file path). Loom transcripts are usually UNLABELED (no
   speaker names) — that is expected.
2. A one-line context header from Trent: **who was in it (+ roles) and what it was about.**

If the header is missing, ASK for it before parsing — attribution depends on it. If the
transcript has no speaker labels, attribute best-effort and FLAG every uncertain
attribution in the readout; never guess silently.

## Step 2 — Load context (read the room first)

Before parsing, load:
- `data/people/*.md` for each named attendee (roles, history, how Trent refers to them).
- `data/projects.md` and `data/memory/decisions.md` (always).
- If the meeting maps to an existing recurring series (see Step 4), load its prior sessions
  from `GET /api/bootstrap` → `meetings` → the matching meeting's `sessions` — that is the
  accumulated context that makes this parse sharper.
- Pull vector memory / pipeline cache only if the topics clearly call for it.

Speak Trent's language: product split is OS vs Strength (tag facts by product); use people's
short names; know GTM/pipeline terms. When unsure of a term, check the people files and
decisions.md rather than guessing.

## Step 3 — Parse into four buckets (never one flat list)

1. **I owe** — commitments Trent made.
2. **Owed to me** — commitments others made that Trent is waiting on.
3. **Decisions made** — conclusions to remember/act on (NOT tasks).
4. **Team tasks I own the outcome of** — assigned to others, Trent accountable.

FILTER OUT / demote to a one-line footnote (do NOT make these action items):
- Unresolved brainstorming (ideas floated, not decided).
- Others' internal tasks Trent has no stake in.
- Hypotheticals / "someday" (no owner, deadline, or real intent).

KEEP as context (put in the summary, NEVER as a task): status updates / FYI.

## Step 4 — Resolve which meeting this ties to (HARD STOP on ambiguity)

Call `GET /api/bootstrap` and read `meetings` (each has `id`, `name`, `people_ids`).
- If the transcript clearly matches exactly one recurring series (by name + attendees),
  use it (`kind: "recurring"`, that `meeting_id`).
- If it is a brand-new recurring meeting, propose creating the series (`kind: "recurring"`,
  empty `meeting_id`).
- If it is a one-off / impromptu meeting, use `kind: "oneoff"` (no series is created).
- If there is ANY ambiguity — no clear match, multiple plausible matches, or unclear whether
  it recurs — STOP and ask Trent to pick from the existing meetings, name a new series, or
  declare it one-off. Never auto-create a series or guess.

Resolve attendee names to `people_ids` using `GET /api/bootstrap` → `people` (each `{id,
name}`). Trent's own id is his people-registry id (look it up; do not hardcode). If a name
does not resolve, ask.

## Step 5 — Present the readout (tight, ranked)

Show:
- One-line headline: what the meeting was really about.
- The four buckets, each ranked by importance.
- Low-confidence items and uncertain attributions flagged inline.
- Nothing else.

## Step 6 — Review + comment loop

Ask Trent to comment freely — drop items, recategorize, fix an owner, add something you
missed. Revise and re-present. Do NOT write anything until he explicitly says commit.

Remember the owner rule (the action-vs-monitor axis):
- I owe → owner = Trent.
- Owed to me → owner = the person who owes it.
- Team task I own → owner = the assignee.

## Step 7 — Write back (only on explicit approval)

1. Ensure the Registry server is running (`GET http://localhost:8787/api/bootstrap` succeeds).
   If not, launch it (see the `registry-ui` skill or `python3 tools/server.py`).
2. Build the approved-items payload (schema below) and write it to a temp file in the
   scratchpad.
3. Run: `python -m scripts.meeting_writeback <payload.json>`
4. Report back exactly what was written (the command prints a `created` list), including
   any `errors`. If there are errors, surface them — the write did NOT fully land.

Payload schema:

```json
{
  "meeting": {"kind": "recurring|oneoff", "meeting_id": "<slug or empty>",
              "name": "<meeting name>", "people_ids": ["..."], "date": "YYYY-MM-DD"},
  "summary": "Headline + summary + FYI/status context as one body string.",
  "commitments": [{"text": "...", "owner": "<trent id>"}],
  "owed_to_me":  [{"text": "...", "owner": "<person id>"}],
  "team_tasks":  [{"text": "...", "owner": "<person id>"}],
  "decisions":   ["..."]
}
```

Write-back routing (handled by the orchestrator — do not re-implement, just build the payload):
- **Recurring:** summary → session; commitments → thread (owner) promoted to task;
  owed-to-me + team tasks → threads (owner = person_id); decisions → decisions.md.
- **One-off:** summary → `MEETING_NOTES`-tagged note; ALL action items → Work-tab tasks with
  their owner; decisions → decisions.md. No meeting record is created.
````

- [ ] **Step 2: Verify the skill is discoverable**

Run: `python -c "import yaml,io; d=yaml.safe_load(io.open('.claude/skills/parse-internal-meeting/SKILL.md').read().split('---')[1]); print(d['name']); assert d['name']=='parse-internal-meeting'"`
Expected: prints `parse-internal-meeting` (front-matter parses, name correct).

- [ ] **Step 3: Dry-run walkthrough on a sample transcript (no writes)**

Create a small sample transcript file with an unlabeled 3-person marketing huddle and a
context header. In a Claude Code session, invoke the skill and confirm it:
- asks for the header if omitted,
- produces exactly the four buckets (not a flat list),
- filters at least one brainstorming/hypothetical item to a footnote,
- keeps a status update in the summary (not as a task),
- flags an uncertain attribution,
- stops and asks when the meeting tie is ambiguous.

Do NOT approve the write step in this dry run. Record the observed readout in the PR/notes.

- [ ] **Step 4: End-to-end verification against a test meeting**

With the Registry server running, invoke the skill on the sample transcript, declare it a
one-off, and approve the write. Confirm via `curl`:
- `GET /api/notes` shows a `MEETING_NOTES`-tagged note with the summary.
- `GET /api/tasks` shows one task per action item, each with the correct `owner`.
- `tail data/... decisions` on `origin/main` (or `GET /api/bootstrap`) reflects the decision line.
Then delete the test note/tasks created (via DELETE endpoints) to clean up.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/parse-internal-meeting/SKILL.md
git commit -m "feat: parse-internal-meeting skill (reference frame + write-back orchestration)"
```

---

## Self-Review Notes

- **Spec coverage:** input contract + graceful degradation (Task 4 Step 1); context load incl. prior sessions (Task 4 Step 2); four buckets + filter + keep-FYI (Task 4 Step 3); meeting-tie hard stop (Task 4 Step 4); tight ranked readout (Step 5); comment/approval loop (Step 6); two-path write-back + owner semantics (Task 2 + Task 4 Step 7); MEETING_NOTES note + default-hidden toggle (Task 3); decisions.md write (Task 1). Deferred fast-follow (Work-page Mine/Watching split) intentionally NOT in this plan.
- **Owner semantics** consistent across Task 2 (`owner` on every task; `person_id` on threads) and Task 4 (Step 6 rule).
- **Write path** consistent: all registry writes via HTTP → `_write_main` → origin/main; no direct working-tree registry writes.
