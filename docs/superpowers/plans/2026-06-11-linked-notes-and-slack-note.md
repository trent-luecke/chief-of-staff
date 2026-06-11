# Linked Notes + Slack `/note` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a direct project link to notes, surface notes inline on the People and Work tabs, and add a `/note` Slack slash command that captures notes with person/project/tag links.

**Architecture:** Notes stay event-sourced in `data/notes.jsonl` (`lib/notes.py`). A new `project_id` field rides alongside the existing `person_id`/`task_id`. The Registry UI reads the full notes list (`GET /api/notes`) and filters client-side to surface linked notes on each tab. The `/note` command mirrors the proven `/task` pipeline: Cloudflare Worker → GitHub Actions `workflow_dispatch` → Python script appends to `notes.jsonl` and commits to `main`.

**Tech Stack:** Python/Flask (server + Slack script), vanilla JS/CSS in a single HTML file (UI), Cloudflare Worker (JS), GitHub Actions (YAML), pytest (Python tests). UI/worker tasks use manual browser/curl verification — the repo has no JS test harness.

**Spec:** `docs/superpowers/specs/2026-06-11-linked-notes-and-slack-note-design.md`

---

## File Map

| File | Change |
|------|--------|
| `lib/notes.py` | **Modify** — `project_id` in replay create block; `add_note()` helper; project name in `_format_note_line` + `load_notes_for_brief` |
| `tools/server.py` | **Modify** — `project_id` in `POST /api/notes` create event |
| `.gitattributes` | **Modify** — add `data/notes.jsonl merge=union` |
| `tools/registry_ui.html` | **Modify** — project picker in modal; `openNoteModal(note, onChange)`; shared linked-notes renderer + CSS; project line on note cards; People-tab Linked Notes; Work-tab project Notes + expandable task-row notes |
| `scripts/slack_add_note.py` | **Create** — note creation + person fuzzy-match/disambiguation, project best-match, tag resolution |
| `.github/workflows/note_add.yml` | **Create** — clone of `task_add.yml` for notes |
| `cloudflare/telegram-bridge.js` | **Modify** — `/slack/note` route; generalize `/slack/interactive` routing by action-id prefix |
| `tests/test_notes_lib.py` | **Modify** — `project_id` replay + `add_note` tests |
| `tests/test_slack_add_note.py` | **Create** — token resolution, fuzzy match, tag handling, confirmation formatting |

---

## Task 1: `lib/notes.py` — `project_id` in replay, `add_note()` helper, project in brief

**Files:**
- Modify: `lib/notes.py`
- Test: `tests/test_notes_lib.py`

- [ ] **Step 1: Add failing tests to `tests/test_notes_lib.py`**

Append these tests to the end of `tests/test_notes_lib.py`:

```python
# ── project_id replay ─────────────────────────────────────────────────────────

def test_replay_create_carries_project_id(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "project_id": "proj-acme", "brief": False, "pinned": False}
    ])
    notes = replay_notes(p)
    assert notes[0]["project_id"] == "proj-acme"


def test_replay_create_defaults_project_id_none(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "brief": False, "pinned": False}
    ])
    notes = replay_notes(p)
    assert notes[0]["project_id"] is None


def test_replay_update_sets_project_id(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-01T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "brief": False, "pinned": False},
        {"event": "update", "id": "n-aaa111", "ts": "2026-06-02T10:00:00",
         "project_id": "proj-acme"},
    ])
    notes = replay_notes(p)
    assert notes[0]["project_id"] == "proj-acme"


# ── add_note ──────────────────────────────────────────────────────────────────

class _CapturingStorage:
    """Minimal storage stub capturing append_line writes into an in-memory file."""
    def __init__(self):
        self._lines = []
    def append_line(self, key, line):
        self._lines.append(line)
    def content(self):
        return "\n".join(self._lines) + "\n"


def test_add_note_appends_create_event_with_links():
    from lib.notes import add_note, replay_notes_content
    store = _CapturingStorage()
    out = add_note(store, body="call Acme", tags=["SALES"],
                   person_id="jane", project_id="proj-acme", task_id=None)
    assert out["body"] == "call Acme"
    assert out["project_id"] == "proj-acme"
    assert out["person_id"] == "jane"
    assert out["id"].startswith("n-")
    replayed = replay_notes_content(store.content())
    assert len(replayed) == 1
    assert replayed[0]["tags"] == ["SALES"]
    assert replayed[0]["project_id"] == "proj-acme"
    assert replayed[0]["brief"] is False


# ── project name in brief line ────────────────────────────────────────────────

def test_format_note_line_includes_project_name():
    line = _format_note_line(
        {"body": "ship it", "tags": [], "person_id": None,
         "project_id": "proj-acme", "task_id": None},
        people_by_id={},
        projects_by_id={"proj-acme": "Acme Onboarding"},
    )
    assert "Acme Onboarding" in line
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest tests/test_notes_lib.py -k "project_id or add_note or project_name" -v 2>&1 | tail -20
```

Expected: failures — `add_note` import error, `project_id` KeyError/None mismatch, `_format_note_line` unexpected `projects_by_id` kwarg.

- [ ] **Step 3: Add `project_id` to the replay create block**

In `lib/notes.py`, in `replay_notes_content`, the create block currently reads:

```python
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
```

Add the `project_id` line after `task_id`:

```python
        if etype == "create":
            notes[nid] = {
                "id": nid,
                "ts": ev["ts"],
                "body": ev["body"],
                "tags": ev.get("tags", []),
                "person_id": ev.get("person_id"),
                "task_id": ev.get("task_id"),
                "project_id": ev.get("project_id"),
                "brief": ev.get("brief", False),
                "pinned": ev.get("pinned", False),
            }
```

(The `update` branch already applies arbitrary patch keys via `notes[nid].update(patch)`, so `project_id` updates work without change.)

- [ ] **Step 4: Add the `add_note()` helper**

In `lib/notes.py`, update the imports at the top:

```python
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
```

Then add this function after `replay_notes_content` (before `load_notes_for_brief`):

```python
def add_note(
    storage,
    body: str,
    tags: list | None = None,
    person_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
    brief: bool = False,
    pinned: bool = False,
) -> dict:
    """Append a create event to notes.jsonl and return the event dict.

    Mirrors the create path in tools/server.py so Slack-created notes match
    UI-created notes exactly. Caller is responsible for committing the file.
    """
    note_id = "n-" + secrets.token_hex(3)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ev = {
        "event": "create",
        "id": note_id,
        "ts": ts,
        "body": body,
        "tags": tags or [],
        "person_id": person_id,
        "task_id": task_id,
        "project_id": project_id,
        "brief": brief,
        "pinned": pinned,
    }
    storage.append_line("notes.jsonl", json.dumps(ev))
    return ev
```

- [ ] **Step 5: Add project name support to `_format_note_line` and `load_notes_for_brief`**

In `lib/notes.py`, replace `_format_note_line` with:

```python
def _format_note_line(note: dict, people_by_id: dict, projects_by_id: dict | None = None) -> str:
    """Format a single note as a brief-ready bullet line."""
    projects_by_id = projects_by_id or {}
    extras = []
    if note.get("tags"):
        extras.append(f"[{', '.join(note['tags'])}]")
    if note.get("person_id") and note["person_id"] in people_by_id:
        extras.append(f"→ {people_by_id[note['person_id']]}")
    if note.get("project_id") and note["project_id"] in projects_by_id:
        extras.append(f"⊕ {projects_by_id[note['project_id']]}")
    suffix = f"  ({' '.join(extras)})" if extras else ""
    return f"  - {note['body']}{suffix}"
```

In `load_notes_for_brief`, after the `people_by_id` block (the `try/except` that loads `people_registry.json`), add a `projects_by_id` loader:

```python
    projects_by_id: dict[str, str] = {}
    try:
        preg = json.loads((storage.base_dir / "projects_registry.json").read_text())
        projects_by_id = {
            p["id"]: p.get("canonical_name", p["id"])
            for p in preg.get("projects", [])
        }
    except Exception:
        pass
```

Then update the two `_format_note_line(n, people_by_id)` calls in that function to pass projects:

```python
            lines.append(_format_note_line(n, people_by_id, projects_by_id))
```

- [ ] **Step 6: Run all notes-lib tests**

```bash
python -m pytest tests/test_notes_lib.py -v 2>&1 | tail -25
```

Expected: all tests PASS (the original suite plus the 5 new ones).

- [ ] **Step 7: Commit**

```bash
git add lib/notes.py tests/test_notes_lib.py
git commit -m "feat: notes carry project_id; add_note helper; project name in brief"
```

---

## Task 2: `tools/server.py` — `project_id` in `POST /api/notes`

**Files:**
- Modify: `tools/server.py` (the `create_note` route)

- [ ] **Step 1: Add `project_id` to the create event**

In `tools/server.py`, `create_note()` builds `ev` as:

```python
    ev = {
        "event": "create", "id": note_id, "ts": ts,
        "body": body["body"], "tags": body.get("tags", []),
        "person_id": body.get("person_id"), "task_id": body.get("task_id"),
        "brief": body.get("brief", False), "pinned": body.get("pinned", False),
    }
```

Add `project_id` after `task_id`:

```python
    ev = {
        "event": "create", "id": note_id, "ts": ts,
        "body": body["body"], "tags": body.get("tags", []),
        "person_id": body.get("person_id"), "task_id": body.get("task_id"),
        "project_id": body.get("project_id"),
        "brief": body.get("brief", False), "pinned": body.get("pinned", False),
    }
```

(The `PATCH` route already spreads arbitrary body keys into the update event, so `project_id` edits already work.)

- [ ] **Step 2: Verify the server imports cleanly**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -c "from tools.server import app; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Manual smoke test (requires online git remote — POST writes to origin/main)**

```bash
# Terminal 1
python tools/server.py
# Terminal 2
curl -s -X POST http://localhost:8787/api/notes \
  -H "Content-Type: application/json" \
  -d '{"body":"proj link test","project_id":"captains-coaches-coaches-course"}' | python3 -m json.tool
# Expected: note object with "project_id":"captains-coaches-coaches-course"
curl -s http://localhost:8787/api/notes | python3 -m json.tool | grep project_id
# Expected: the project_id present on the new note
```

> If you cannot exercise the live origin/main write here, the unit coverage in Task 1 plus the import check in Step 2 are sufficient; note that you skipped the live POST.

- [ ] **Step 4: Commit**

```bash
git add tools/server.py
git commit -m "feat: accept project_id in POST /api/notes"
```

---

## Task 3: `.gitattributes` — union merge for notes.jsonl

**Files:**
- Modify: `.gitattributes`

- [ ] **Step 1: Add the merge driver line**

`.gitattributes` currently contains:

```
data/tasks.jsonl merge=union
```

Add a second line so it reads:

```
data/tasks.jsonl merge=union
data/notes.jsonl merge=union
```

- [ ] **Step 2: Verify git recognizes the attribute**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
git check-attr merge -- data/notes.jsonl
```

Expected: `data/notes.jsonl: merge: union`

- [ ] **Step 3: Commit**

```bash
git add .gitattributes
git commit -m "chore: union merge driver for notes.jsonl (UI + Slack concurrent appends)"
```

---

## Task 4: `tools/registry_ui.html` — project picker in capture modal

**Files:**
- Modify: `tools/registry_ui.html`

- [ ] **Step 1: Add the project picker HTML to the modal**

Find the Person/Task picker block in the modal body. It currently reads:

```html
        <div class="note-field-label" style="margin-top:10px">Person (optional)</div>
        <div class="note-picker-wrap">
          <input id="note-person-input" class="note-field-input" placeholder="Search people…" autocomplete="off" />
          <div id="note-person-dropdown" class="note-picker-dropdown hidden"></div>
        </div>
        <input type="hidden" id="note-person-id" />

        <div class="note-field-label" style="margin-top:10px">Task (optional)</div>
```

Insert a Project block between the person hidden input and the Task label:

```html
        <div class="note-field-label" style="margin-top:10px">Person (optional)</div>
        <div class="note-picker-wrap">
          <input id="note-person-input" class="note-field-input" placeholder="Search people…" autocomplete="off" />
          <div id="note-person-dropdown" class="note-picker-dropdown hidden"></div>
        </div>
        <input type="hidden" id="note-person-id" />

        <div class="note-field-label" style="margin-top:10px">Project (optional)</div>
        <div class="note-picker-wrap">
          <input id="note-project-input" class="note-field-input" placeholder="Search projects…" autocomplete="off" />
          <div id="note-project-dropdown" class="note-picker-dropdown hidden"></div>
        </div>
        <input type="hidden" id="note-project-id" />

        <div class="note-field-label" style="margin-top:10px">Task (optional)</div>
```

- [ ] **Step 2: Add `_projects` to `notesState`**

Find the `notesState` object. It contains:

```javascript
  _tags: [],
  _people: [],
  _tasks: [],
```

Change to:

```javascript
  _tags: [],
  _people: [],
  _tasks: [],
  _projects: [],
```

- [ ] **Step 3: Load projects in `renderNotesView`**

In `renderNotesView`, the data load currently reads:

```javascript
  let notes, tags, people, tasks;
  try {
    [notes, tags, people, tasks] = await Promise.all([
      fetchJSON(`${API}/api/notes`),
      fetchJSON(`${API}/api/notes/tags`),
      fetchJSON(`${API}/api/people`),
      fetchJSON(`${API}/api/tasks`),
    ]);
  } catch {
```

Change to:

```javascript
  let notes, tags, people, tasks, projects;
  try {
    [notes, tags, people, tasks, projects] = await Promise.all([
      fetchJSON(`${API}/api/notes`),
      fetchJSON(`${API}/api/notes/tags`),
      fetchJSON(`${API}/api/people`),
      fetchJSON(`${API}/api/tasks`),
      fetchJSON(`${API}/api/projects`),
    ]);
  } catch {
```

And the assignments below it:

```javascript
  notesState._tags = tags;
  notesState._people = people;
  notesState._tasks = tasks;
```

Change to:

```javascript
  notesState._tags = tags;
  notesState._people = people;
  notesState._tasks = tasks;
  notesState._projects = projects;
```

- [ ] **Step 4: Load + wire the project picker in `openNoteModal`**

In `openNoteModal`, the pre-load guard currently reads:

```javascript
  if (!notesState._people.length || !notesState._tasks.length) {
    try {
      const [tags, people, tasks] = await Promise.all([
        fetchJSON(`${API}/api/notes/tags`),
        fetchJSON(`${API}/api/people`),
        fetchJSON(`${API}/api/tasks`),
      ]);
      notesState._tags = tags;
      notesState._people = people;
      notesState._tasks = tasks;
    } catch (e) {
      console.error('[openNoteModal] fetch failed:', e.message);
    }
  }

  const tags = notesState._tags;
  const people = notesState._people;
  const tasks = notesState._tasks;
```

Change to:

```javascript
  if (!notesState._people.length || !notesState._tasks.length || !notesState._projects.length) {
    try {
      const [tags, people, tasks, projects] = await Promise.all([
        fetchJSON(`${API}/api/notes/tags`),
        fetchJSON(`${API}/api/people`),
        fetchJSON(`${API}/api/tasks`),
        fetchJSON(`${API}/api/projects`),
      ]);
      notesState._tags = tags;
      notesState._people = people;
      notesState._tasks = tasks;
      notesState._projects = projects;
    } catch (e) {
      console.error('[openNoteModal] fetch failed:', e.message);
    }
  }

  const tags = notesState._tags;
  const people = notesState._people;
  const tasks = notesState._tasks;
  const projects = notesState._projects;
```

In the same function, after the task input value block:

```javascript
  el('note-task-input').value = isEdit && note.task_id
    ? (tasks.find(t => t.id === note.task_id)?.title || note.task_id) : '';
  el('note-task-id').value = isEdit ? (note.task_id || '') : '';
```

add the project input value block:

```javascript
  el('note-project-input').value = isEdit && note.project_id
    ? (projects.find(p => p.id === note.project_id)?.canonical_name || note.project_id) : '';
  el('note-project-id').value = isEdit ? (note.project_id || '') : '';
```

In the save payload, currently:

```javascript
    const payload = {
      body,
      tags: [...selectedTags],
      person_id: el('note-person-id').value || null,
      task_id: el('note-task-id').value || null,
      brief: el('note-brief-check').checked,
    };
```

change to:

```javascript
    const payload = {
      body,
      tags: [...selectedTags],
      person_id: el('note-person-id').value || null,
      project_id: el('note-project-id').value || null,
      task_id: el('note-task-id').value || null,
      brief: el('note-brief-check').checked,
    };
```

In the edit-diff block, after the `task_id` diff line:

```javascript
        if (payload.task_id !== note.task_id) patch.task_id = payload.task_id;
```

add:

```javascript
        if (payload.project_id !== note.project_id) patch.project_id = payload.project_id;
```

Finally, in the typeahead wiring at the end of `openNoteModal`, after the task typeahead:

```javascript
  wireTypeahead(
    el('note-task-input'), el('note-task-dropdown'), el('note-task-id'),
    tasks.map(t => ({ id: t.id, label: t.title }))
  );
```

add the project typeahead:

```javascript
  wireTypeahead(
    el('note-project-input'), el('note-project-dropdown'), el('note-project-id'),
    projects.map(p => ({ id: p.id, label: p.canonical_name }))
  );
```

- [ ] **Step 5: Manual browser verification**

```bash
python tools/server.py
# Open http://localhost:8787 → Notes tab → click the + FAB
```

Confirm: a "Project (optional)" search field appears between Person and Task. Typing a project name shows matches; selecting one and saving creates a note. Re-open the note (click its card) — the project field is pre-filled. No console errors.

- [ ] **Step 6: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: project picker in note capture modal"
```

---

## Task 5: `tools/registry_ui.html` — shared linked-notes renderer, `onChange` callback, project on cards

**Files:**
- Modify: `tools/registry_ui.html`

- [ ] **Step 1: Add CSS for linked-note lines and task-row notes**

Find the `/* ── Notes tab ── */` CSS block (it starts with `.note-masonry`). Immediately after the `.note-card:hover` rule, add:

```css
    /* Linked notes (People + Work tabs) */
    .linked-notes-section { margin-top: 10px; }
    .linked-notes-label {
      font-size: 10px; font-weight: 600; color: var(--muted);
      text-transform: uppercase; letter-spacing: .06em; margin-bottom: 5px;
    }
    .linked-note-line {
      display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap;
      padding: 4px 6px; border-left: 2px solid var(--border);
      margin-bottom: 4px; cursor: pointer; border-radius: 0 3px 3px 0;
    }
    .linked-note-line:hover { background: var(--surface2); }
    .linked-note-ts { font-size: 10px; color: var(--muted); flex-shrink: 0; }
    .linked-note-body { font-size: 12px; color: var(--text); line-height: 1.4; }
    /* Task-row note affordance */
    .task-note-toggle {
      font-size: 11px; color: var(--muted); cursor: pointer;
      padding: 0 4px; user-select: none;
    }
    .task-note-toggle:hover { color: var(--accent); }
    .task-note-drawer {
      flex-basis: 100%; margin: 4px 0 2px 0; padding-left: 8px;
    }
    .task-note-drawer.hidden { display: none; }
```

- [ ] **Step 2: Add the shared `linkedNoteLinesHtml` + `wireLinkedNoteClicks` helpers**

Add these functions immediately before `function renderNoteCard(` :

```javascript
// ── Shared linked-notes rendering (People + Work tabs) ────────────────────────
function linkedNoteLinesHtml(notes, tags) {
  return notes.map(n => {
    const tagObjects = (n.tags || []).map(tid => tags.find(t => t.id === tid)).filter(Boolean);
    const tagHtml = tagObjects.map(t =>
      `<span class="note-tag-chip" style="color:${t.color};border-color:${t.color}">${esc(t.id)}</span>`
    ).join('');
    const shortTs = (n.ts || '').slice(0, 16).replace('T', ' ');
    return `<div class="linked-note-line" data-note-id="${esc(n.id)}">
      <span class="linked-note-ts">${esc(shortTs)}</span>
      ${tagHtml}
      <span class="linked-note-body">${esc(n.body)}</span>
    </div>`;
  }).join('');
}

// Wire click → edit modal for any .linked-note-line inside containerEl.
// allNotes: the full notes array; onChange: re-render callback after edit/save.
function wireLinkedNoteClicks(containerEl, allNotes, onChange) {
  containerEl.querySelectorAll('.linked-note-line').forEach(line => {
    line.addEventListener('click', e => {
      e.stopPropagation();
      const note = allNotes.find(n => n.id === line.dataset.noteId);
      if (note) openNoteModal(note, onChange);
    });
  });
}
```

- [ ] **Step 3: Give `openNoteModal` an optional `onChange` callback**

Change the function signature:

```javascript
async function openNoteModal(note) {
```

to:

```javascript
async function openNoteModal(note, onChange) {
  const afterChange = onChange || renderNotesView;
```

Then, in the same function, replace every `renderNotesView();` call that runs after a successful save/delete/pin with `afterChange();`. There are three such calls — inside `note-save-btn` `onclick`, `note-delete-btn` `onclick`, and `note-pin-btn` `onclick`. Each currently reads:

```javascript
        closeNoteModal();
        renderNotesView();
```

Change each to:

```javascript
        closeNoteModal();
        afterChange();
```

(Leave the new-tag handler's `renderModalTagChips` calls untouched — only the post-save/delete/pin `renderNotesView()` calls change.)

- [ ] **Step 4: Show the project link on note cards**

In `renderNoteCard`, after the line:

```javascript
  const taskTitle = note.task_id ? (tasks.find(t => t.id === note.task_id)?.title || null) : null;
```

add:

```javascript
  const projectName = note.project_id ? (notesState._projects.find(p => p.id === note.project_id)?.canonical_name || null) : null;
```

Then in the returned template, after the person `note-link` line:

```javascript
      ${personName ? `<div class="note-link">→ ${esc(personName)}</div>` : ''}
```

add a project line:

```javascript
      ${projectName ? `<div class="note-link">⊕ ${esc(projectName)}</div>` : ''}
```

- [ ] **Step 5: Manual browser verification**

```bash
python tools/server.py
# Open http://localhost:8787 → Notes tab
```

Confirm: a note linked to a project shows a `⊕ Project Name` line on its card. Clicking a card still opens the editor and saving still refreshes the Notes tab (no regression from the `afterChange` change). No console errors.

- [ ] **Step 6: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: shared linked-notes renderer, openNoteModal onChange, project on cards"
```

---

## Task 6: `tools/registry_ui.html` — Linked Notes on the People tab

**Files:**
- Modify: `tools/registry_ui.html`

- [ ] **Step 1: Make `openDetailReadOnly` async and append a Linked Notes section**

`openDetailReadOnly` currently reads:

```javascript
function openDetailReadOnly(person, detail) {
  detail.innerHTML = buildDetailReadOnlyHtml(person, getPersonObs(person.id));
  detail.classList.remove('hidden');
  detail.querySelector('[data-edit-person]').addEventListener('click', () => {
    openDetailEdit(person, detail);
  });
  detail.querySelector('[data-merge-person]').addEventListener('click', () => {
    openMergeSearch(person, detail);
  });
}
```

Replace it with:

```javascript
async function openDetailReadOnly(person, detail) {
  detail.innerHTML = buildDetailReadOnlyHtml(person, getPersonObs(person.id));
  detail.classList.remove('hidden');
  detail.querySelector('[data-edit-person]').addEventListener('click', () => {
    openDetailEdit(person, detail);
  });
  detail.querySelector('[data-merge-person]').addEventListener('click', () => {
    openMergeSearch(person, detail);
  });
  await appendLinkedNotesForPerson(person, detail);
}

// Fetch notes + tags, render the notes linked to this person, and wire edit clicks.
async function appendLinkedNotesForPerson(person, detail) {
  let notes, tags;
  try {
    [notes, tags] = await Promise.all([
      fetchJSON(`${API}/api/notes`),
      fetchJSON(`${API}/api/notes/tags`),
    ]);
  } catch {
    return; // server offline — silently skip the notes section
  }
  notesState._projects = notesState._projects.length
    ? notesState._projects
    : await fetchJSON(`${API}/api/projects`).catch(() => []);
  const linked = notes
    .filter(n => n.person_id === person.id)
    .sort((a, b) => (a.ts < b.ts ? 1 : -1));
  if (!linked.length) return;
  const section = document.createElement('div');
  section.className = 'linked-notes-section';
  section.innerHTML = `<div class="linked-notes-label">Linked Notes (${linked.length})</div>`
    + linkedNoteLinesHtml(linked, tags);
  detail.appendChild(section);
  wireLinkedNoteClicks(section, notes, () => openDetailReadOnly(person, detail));
}
```

- [ ] **Step 2: Manual browser verification**

```bash
python tools/server.py
# In the UI: create a note via the FAB linked to a person (e.g. yourself).
# Then go to the People tab → click that person's row to expand.
```

Confirm: a "Linked Notes (N)" section appears at the bottom of the expanded detail listing that note. Clicking the note opens the editor; after saving an edit, the detail re-renders with the change. People with no linked notes show no section. No console errors.

- [ ] **Step 3: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: Linked Notes section on People tab person detail"
```

---

## Task 7: `tools/registry_ui.html` — Work tab project Notes + expandable task-row notes

**Files:**
- Modify: `tools/registry_ui.html`

- [ ] **Step 1: Load notes (+ tags) in `renderWorkView`**

`renderWorkView` currently loads:

```javascript
  let projects, allTasks, people;
  try {
    [projects, allTasks, people] = await Promise.all([
      fetchJSON(`${API}/api/projects`),
      fetchJSON(`${API}/api/tasks`),
      fetchJSON(`${API}/api/people`),
    ]);
  } catch {
```

Change to:

```javascript
  let projects, allTasks, people, allNotes, noteTags;
  try {
    [projects, allTasks, people, allNotes, noteTags] = await Promise.all([
      fetchJSON(`${API}/api/projects`),
      fetchJSON(`${API}/api/tasks`),
      fetchJSON(`${API}/api/people`),
      fetchJSON(`${API}/api/notes`),
      fetchJSON(`${API}/api/notes/tags`),
    ]);
  } catch {
```

Right after that `try/catch` (before `const activeProjects = ...`), cache projects for card rendering and build a per-task notes index:

```javascript
  notesState._projects = projects || [];
  const notesByTask = {};
  for (const n of (allNotes || [])) {
    if (n.task_id) (notesByTask[n.task_id] = notesByTask[n.task_id] || []).push(n);
  }
```

- [ ] **Step 2: Render a Notes sub-section inside each project group body**

In `renderWorkView`, the project group body template currently reads:

```javascript
            <div class="proj-group-body${workState.editing.has(p.id) ? ' edit-active' : ''}${isExpanded ? '' : ' hidden'}" id="group-body-${esc(p.id)}">
              <div class="proj-edit-panel hidden" id="edit-panel-${esc(p.id)}"></div>
              <div id="group-tasks-${esc(p.id)}">${taskRowsHtml}</div>
              ${renderAddTaskForm(p.id, people)}
            </div>
```

Just before this template is built (inside the `.map(p => {` callback, after `const taskRowsHtml = ...`), compute the project's notes — those linked directly to the project, plus those rolled up from its tasks:

```javascript
        const projTaskIds = new Set(pTasks.map(t => t.id));
        const projNotes = (allNotes || [])
          .filter(n => n.project_id === p.id || (n.task_id && projTaskIds.has(n.task_id)))
          .sort((a, b) => (a.ts < b.ts ? 1 : -1));
        const projNotesHtml = projNotes.length
          ? `<div class="linked-notes-section" id="proj-notes-${esc(p.id)}">
               <div class="linked-notes-label">Notes (${projNotes.length})</div>
               ${linkedNoteLinesHtml(projNotes, noteTags)}
             </div>`
          : '';
```

Then add `${projNotesHtml}` into the group body, after the add-task form:

```javascript
            <div class="proj-group-body${workState.editing.has(p.id) ? ' edit-active' : ''}${isExpanded ? '' : ' hidden'}" id="group-body-${esc(p.id)}">
              <div class="proj-edit-panel hidden" id="edit-panel-${esc(p.id)}"></div>
              <div id="group-tasks-${esc(p.id)}">${taskRowsHtml}</div>
              ${renderAddTaskForm(p.id, people)}
              ${projNotesHtml}
            </div>
```

- [ ] **Step 3: Pass per-task notes into `renderTaskRow` and render the affordance**

Change the `renderTaskRow` signature:

```javascript
function renderTaskRow(task, people, withLinkProj = false) {
```

to:

```javascript
function renderTaskRow(task, people, withLinkProj = false, notesForTask = []) {
```

Inside `renderTaskRow`, after the `linkChip` line, add:

```javascript
  const noteToggle = notesForTask.length
    ? `<span class="task-note-toggle" data-task-id="${esc(task.id)}" title="Show linked notes">💬 ${notesForTask.length}</span>`
    : '';
  const noteDrawer = notesForTask.length
    ? `<div class="task-note-drawer hidden" id="task-notes-${esc(task.id)}">${linkedNoteLinesHtmlForTask(notesForTask)}</div>`
    : '';
```

Then in the returned `task-row` template, add `${noteToggle}` after `${linkChip}` and `${noteDrawer}` after the delete button:

```javascript
  return `
    <div class="task-row" id="task-row-${esc(task.id)}">
      <button class="btn-done" data-task-id="${esc(task.id)}">Done</button>
      <span class="task-title">${esc(task.title)}</span>
      ${task.due_date ? renderDueDateChip(task) : `<span class="due-ghost" data-task-id="${esc(task.id)}">+ due</span>`}
      <span style="position:relative;display:inline-flex;align-items:center">
        ${renderOwnerChip(task, people)}
      </span>
      ${linkChip}
      ${noteToggle}
      <button class="btn-delete-task" data-task-id="${esc(task.id)}" title="Delete task">×</button>
      ${noteDrawer}
    </div>`;
```

Add a tags-free line renderer used by the drawer (the Work view's `noteTags` isn't in `renderTaskRow`'s scope, so the drawer renders without tag chips), immediately before `renderTaskRow`:

```javascript
// Compact note lines for a task drawer (no tag chips — keeps renderTaskRow tag-agnostic).
function linkedNoteLinesHtmlForTask(notes) {
  return notes
    .slice()
    .sort((a, b) => (a.ts < b.ts ? 1 : -1))
    .map(n => {
      const shortTs = (n.ts || '').slice(0, 16).replace('T', ' ');
      return `<div class="linked-note-line" data-note-id="${esc(n.id)}">
        <span class="linked-note-ts">${esc(shortTs)}</span>
        <span class="linked-note-body">${esc(n.body)}</span>
      </div>`;
    }).join('');
}
```

- [ ] **Step 4: Pass task notes at both `renderTaskRow` call sites**

In `renderWorkView`, the project task rows are built as:

```javascript
        const taskRowsHtml = pTasks.length
          ? pTasks.map(t => renderTaskRow(t, people)).join('')
          : '<span class="muted" style="font-size:12px">No open tasks.</span>';
```

Change to:

```javascript
        const taskRowsHtml = pTasks.length
          ? pTasks.map(t => renderTaskRow(t, people, false, notesByTask[t.id] || [])).join('')
          : '<span class="muted" style="font-size:12px">No open tasks.</span>';
```

The standalone task rows are built as:

```javascript
  const standaloneHtml = standaloneTasks.length
    ? standaloneTasks.map(t => renderTaskRow(t, people, true)).join('')
    : '<div class="muted" style="font-size:12px">No standalone tasks.</div>';
```

Change to:

```javascript
  const standaloneHtml = standaloneTasks.length
    ? standaloneTasks.map(t => renderTaskRow(t, people, true, notesByTask[t.id] || [])).join('')
    : '<div class="muted" style="font-size:12px">No standalone tasks.</div>';
```

- [ ] **Step 5: Wire the project-notes clicks and task-drawer toggles**

At the end of `renderWorkView`, after the existing wiring (after the standalone wiring block), add:

```javascript
  // Wire project-level linked notes → edit modal
  activeProjects.forEach(p => {
    const sec = document.getElementById(`proj-notes-${p.id}`);
    if (sec) wireLinkedNoteClicks(sec, allNotes, () => renderWorkView());
  });

  // Wire task-row note toggles (expand/collapse) and drawer note clicks
  view.querySelectorAll('.task-note-toggle').forEach(toggle => {
    toggle.addEventListener('click', e => {
      e.stopPropagation();
      const drawer = document.getElementById(`task-notes-${toggle.dataset.taskId}`);
      if (drawer) drawer.classList.toggle('hidden');
    });
  });
  view.querySelectorAll('.task-note-drawer').forEach(drawer => {
    wireLinkedNoteClicks(drawer, allNotes, () => renderWorkView());
  });
```

- [ ] **Step 6: Manual browser verification**

```bash
python tools/server.py
# Create: a note linked to a project directly, and a note linked to a task in that project.
# Open the Work tab → expand the project.
```

Confirm: the project body shows a "Notes (N)" section containing both the directly-linked note and the task-linked note (roll-up). The task row shows a `💬 1` affordance; clicking it expands the linked note body inline; clicking the note opens the editor. Saving an edit re-renders the Work view. No console errors.

- [ ] **Step 7: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: Work tab project Notes section + expandable task-row notes"
```

---

## Task 8: `scripts/slack_add_note.py` + tests — note creation & link resolution

**Files:**
- Create: `scripts/slack_add_note.py`
- Create: `tests/test_slack_add_note.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_slack_add_note.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.slack_add_note import (
    fuzzy_match_people,
    best_match_project,
    resolve_tag,
    format_confirmation,
)


def _write_people(tmp_path, people):
    p = tmp_path / "people_registry.json"
    p.write_text(json.dumps({"version": 1, "people": people}))
    return p


def _write_projects(tmp_path, projects):
    p = tmp_path / "projects_registry.json"
    p.write_text(json.dumps({"version": 1, "projects": projects}))
    return p


def _write_tags(tmp_path, tags):
    p = tmp_path / "notes_tags.json"
    p.write_text(json.dumps(tags))
    return p


# ── fuzzy_match_people ────────────────────────────────────────────────────────

def test_fuzzy_match_people_single(tmp_path):
    reg = _write_people(tmp_path, [
        {"id": "jane-doe", "canonical_name": "Jane Doe", "aliases": []},
        {"id": "bob-smith", "canonical_name": "Bob Smith", "aliases": []},
    ])
    matches = fuzzy_match_people("jane", reg)
    assert len(matches) == 1
    assert matches[0]["id"] == "jane-doe"


def test_fuzzy_match_people_ambiguous(tmp_path):
    reg = _write_people(tmp_path, [
        {"id": "jane-doe", "canonical_name": "Jane Doe", "aliases": []},
        {"id": "jane-roe", "canonical_name": "Jane Roe", "aliases": []},
    ])
    matches = fuzzy_match_people("jane", reg)
    assert len(matches) == 2


def test_fuzzy_match_people_none(tmp_path):
    reg = _write_people(tmp_path, [{"id": "bob", "canonical_name": "Bob", "aliases": []}])
    assert fuzzy_match_people("zzz", reg) == []


# ── best_match_project ────────────────────────────────────────────────────────

def test_best_match_project_hit(tmp_path):
    reg = _write_projects(tmp_path, [
        {"id": "acme-onboarding", "canonical_name": "Acme Onboarding", "aliases": []},
        {"id": "beta-launch", "canonical_name": "Beta Launch", "aliases": []},
    ])
    match = best_match_project("acme", reg)
    assert match is not None
    assert match["id"] == "acme-onboarding"


def test_best_match_project_miss(tmp_path):
    reg = _write_projects(tmp_path, [{"id": "beta-launch", "canonical_name": "Beta Launch", "aliases": []}])
    assert best_match_project("acme", reg) is None


def test_best_match_project_empty_raw(tmp_path):
    reg = _write_projects(tmp_path, [{"id": "beta-launch", "canonical_name": "Beta Launch", "aliases": []}])
    assert best_match_project("", reg) is None


# ── resolve_tag ───────────────────────────────────────────────────────────────

def test_resolve_tag_known(tmp_path):
    tags = _write_tags(tmp_path, [{"id": "SALES", "color": "#2a6b3a"}])
    resolved, dropped = resolve_tag("sales", tags)
    assert resolved == "SALES"
    assert dropped is None


def test_resolve_tag_unknown_is_dropped(tmp_path):
    tags = _write_tags(tmp_path, [{"id": "SALES", "color": "#2a6b3a"}])
    resolved, dropped = resolve_tag("zzz", tags)
    assert resolved is None
    assert dropped == "ZZZ"


def test_resolve_tag_empty(tmp_path):
    tags = _write_tags(tmp_path, [{"id": "SALES", "color": "#2a6b3a"}])
    assert resolve_tag("", tags) == (None, None)


# ── format_confirmation ───────────────────────────────────────────────────────

def test_format_confirmation_plain():
    assert format_confirmation("call Acme", None, None, None, None) == "Note added: call Acme"


def test_format_confirmation_with_links():
    out = format_confirmation("call Acme", "Jane Doe", "Acme Onboarding", "SALES", None)
    assert "Note added: call Acme" in out
    assert "Jane Doe" in out
    assert "Acme Onboarding" in out
    assert "SALES" in out


def test_format_confirmation_with_dropped_tag():
    out = format_confirmation("call Acme", None, None, None, "ZZZ")
    assert "ZZZ" in out
    assert "not found" in out.lower()


def test_format_confirmation_no_project_match_note():
    out = format_confirmation("call Acme", None, None, None, None, project_missed="acme")
    assert "acme" in out
    assert "no project" in out.lower()
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest tests/test_slack_add_note.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError: No module named 'scripts.slack_add_note'`.

- [ ] **Step 3: Create `scripts/slack_add_note.py`**

```python
#!/usr/bin/env python3
"""Add a note from a Slack slash command. Called by note_add.yml.

Mirrors scripts/slack_add_task.py. Person links use the same fuzzy-match +
interactive-disambiguation pattern as /task; project links use best-match-or-skip;
unknown tags are dropped (the tag vocabulary stays curated in the Registry UI).
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.storage import LocalStorage
from lib.notes import add_note


def _load(path: Path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def fuzzy_match_people(raw_name: str, registry_path: Path) -> list:
    """Return [{id, canonical_name}] for every person whose name/aliases match raw_name."""
    if not raw_name or not raw_name.strip():
        return []
    registry = _load(registry_path, {})
    needle = raw_name.lower()
    matches = []
    for person in registry.get("people", []):
        candidates = [person.get("canonical_name", "")] + person.get("aliases", [])
        if any(needle in c.lower() or c.lower() in needle for c in candidates if c):
            matches.append({"id": person["id"], "canonical_name": person.get("canonical_name", person["id"])})
    return matches


def best_match_project(raw_name: str, registry_path: Path):
    """Return {id, canonical_name} for the first project matching raw_name, else None."""
    if not raw_name or not raw_name.strip():
        return None
    registry = _load(registry_path, {})
    needle = raw_name.lower()
    for proj in registry.get("projects", []):
        candidates = [proj.get("canonical_name", "")] + proj.get("aliases", [])
        if any(needle in c.lower() or c.lower() in needle for c in candidates if c):
            return {"id": proj["id"], "canonical_name": proj.get("canonical_name", proj["id"])}
    return None


def resolve_tag(raw_tag: str, tags_path: Path):
    """Return (resolved_tag_id_or_None, dropped_tag_or_None).

    A known tag (case-insensitive) resolves; an unknown non-empty tag is dropped
    and returned (normalized) so the caller can mention it in the confirmation.
    """
    if not raw_tag or not raw_tag.strip():
        return (None, None)
    normalized = raw_tag.strip().upper().replace(" ", "_")
    tags = _load(tags_path, [])
    for t in tags:
        if t.get("id", "").upper() == normalized:
            return (t["id"], None)
    return (None, normalized)


def format_confirmation(body, person_name, project_name, tag, dropped_tag, project_missed=None):
    parts = [f"Note added: {body}"]
    if person_name:
        parts.append(f"→ {person_name}")
    if project_name:
        parts.append(f"⊕ {project_name}")
    if tag:
        parts.append(f"[{tag}]")
    line = " — ".join(parts)
    notices = []
    if dropped_tag:
        notices.append(f"tag {dropped_tag} not found, skipped")
    if project_missed:
        notices.append(f"no project match for '{project_missed}'")
    if notices:
        line += f" ({'; '.join(notices)})"
    return line


def _post_json(response_url: str, payload: dict) -> None:
    if not response_url:
        return
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        response_url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Warning: failed to post to Slack response_url: {e}", file=sys.stderr)


def post_to_slack(response_url: str, text: str, replace: bool = False) -> None:
    payload = {"response_type": "ephemeral", "text": text}
    if replace:
        payload["replace_original"] = True
    _post_json(response_url, payload)


def post_ambiguous_people(response_url, raw_name, matches, body, project_raw, tag):
    """Post interactive buttons (one per candidate person) for note person disambiguation."""
    if not response_url:
        print("Warning: missing response_url — cannot post interactive message", file=sys.stderr)
        return
    capped = matches[:4]
    overflow = f"\n_Showing first 4 of {len(matches)} matches._" if len(matches) > 4 else ""
    buttons = []
    for person in capped:
        value = json.dumps({"body": body, "project_raw": project_raw, "tag": tag,
                            "person_raw": person["canonical_name"]})
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": person["canonical_name"]},
            "action_id": f"link_note_person_{person['id']}",
            "value": value,
        })
    none_value = json.dumps({"body": body, "project_raw": project_raw, "tag": tag, "person_raw": ""})
    buttons.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "No person"},
        "action_id": "link_note_person_none",
        "value": none_value,
    })
    _post_json(response_url, {
        "response_type": "ephemeral",
        "text": f"Multiple matches for '{raw_name}' — who did you mean?",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"Multiple matches for *{raw_name}* — who did you mean?{overflow}"}},
            {"type": "actions", "elements": buttons},
        ],
    })


def main():
    body = os.environ.get("NOTE_BODY", "").strip()
    person_raw = os.environ.get("PERSON_RAW", "").strip()
    project_raw = os.environ.get("PROJECT_RAW", "").strip()
    tag_raw = os.environ.get("TAG_RAW", "").strip()
    response_url = os.environ.get("RESPONSE_URL", "")

    if not body:
        print("Error: NOTE_BODY is required", file=sys.stderr)
        sys.exit(1)

    data_dir = ROOT / "data"
    people_path = data_dir / "people_registry.json"
    projects_path = data_dir / "projects_registry.json"
    tags_path = data_dir / "notes_tags.json"

    # Person: fuzzy match; ambiguous → buttons (note not created yet)
    person_id, person_name = None, None
    if person_raw:
        matches = fuzzy_match_people(person_raw, people_path)
        if len(matches) == 1:
            person_id = matches[0]["id"]
            person_name = matches[0]["canonical_name"]
        elif len(matches) > 1 and response_url:
            post_ambiguous_people(response_url, person_raw, matches, body, project_raw, tag_raw)
            print(f"Ambiguous person '{person_raw}' — posted buttons, note not created")
            return
        elif len(matches) > 1:
            person_id = matches[0]["id"]
            person_name = matches[0]["canonical_name"]
        # len == 0: leave unlinked; mentioned implicitly (person omitted from confirmation)

    # Project: best-match-or-skip
    project_id, project_name, project_missed = None, None, None
    if project_raw:
        proj = best_match_project(project_raw, projects_path)
        if proj:
            project_id, project_name = proj["id"], proj["canonical_name"]
        else:
            project_missed = project_raw

    # Tag: known resolves, unknown dropped
    tag, dropped_tag = resolve_tag(tag_raw, tags_path)

    storage = LocalStorage(base_dir=str(data_dir))
    add_note(storage, body=body, tags=[tag] if tag else [],
             person_id=person_id, project_id=project_id, task_id=None)

    confirmation = format_confirmation(body, person_name, project_name, tag, dropped_tag, project_missed)
    post_to_slack(response_url, confirmation, replace=bool(person_raw))
    print(confirmation)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
python -m pytest tests/test_slack_add_note.py -v 2>&1 | tail -25
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/slack_add_note.py tests/test_slack_add_note.py
git commit -m "feat: slack_add_note script (person/project/tag resolution) + tests"
```

---

## Task 9: `.github/workflows/note_add.yml` — Slack note workflow

**Files:**
- Create: `.github/workflows/note_add.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/note_add.yml`:

```yaml
name: Add Note from Slack

on:
  workflow_dispatch:
    inputs:
      body:
        description: "Note body"
        required: true
      response_url:
        description: "Slack response_url for posting confirmation"
        required: false
        default: ""
      person_raw:
        description: "Raw person name to fuzzy-match against people registry"
        required: false
        default: ""
      project_raw:
        description: "Raw project name to fuzzy-match against projects registry"
        required: false
        default: ""
      tag_raw:
        description: "Raw tag to match against notes_tags.json"
        required: false
        default: ""
      channel_id:
        description: "Slack channel ID"
        required: false
        default: ""
      user_id:
        description: "Slack user ID of the person who ran the command"
        required: false
        default: ""

permissions:
  contents: write

jobs:
  add-note:
    runs-on: ubuntu-latest
    env:
      TZ: America/Chicago
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Add note
        env:
          NOTE_BODY: ${{ inputs.body }}
          RESPONSE_URL: ${{ inputs.response_url }}
          PERSON_RAW: ${{ inputs.person_raw }}
          PROJECT_RAW: ${{ inputs.project_raw }}
          TAG_RAW: ${{ inputs.tag_raw }}
          CHANNEL_ID: ${{ inputs.channel_id }}
          USER_ID: ${{ inputs.user_id }}
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
        run: python scripts/slack_add_note.py

      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/notes.jsonl
          git diff --staged --quiet || git commit -m "chore: add note from slack [skip ci]"
          git push origin main || true
```

- [ ] **Step 2: Validate the YAML parses**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -c "import yaml; yaml.safe_load(open('.github/workflows/note_add.yml')); print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/note_add.yml
git commit -m "feat: note_add.yml workflow for Slack /note"
```

---

## Task 10: `cloudflare/telegram-bridge.js` — `/slack/note` route + generalized interactive routing

**Files:**
- Modify: `cloudflare/telegram-bridge.js`

- [ ] **Step 1: Add the `handleSlackNote` handler**

In `cloudflare/telegram-bridge.js`, add this function immediately after `handleSlackTask` (before `handleSlackInteractive`):

```javascript
async function handleSlackNote(request, env, ctx) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp") || "";
  const signature = request.headers.get("X-Slack-Signature") || "";

  if (!timestamp || !signature) return new Response("Unauthorized", { status: 401 });

  const rawBody = await request.text();

  if (!await verifySlackSig(env.SLACK_SIGNING_SECRET, timestamp, rawBody, signature)) {
    return new Response("Unauthorized", { status: 401 });
  }

  const params = new URLSearchParams(rawBody);
  const text = (params.get("text") || "").trim();
  const responseUrl = params.get("response_url") || "";
  const channelId = params.get("channel_id") || "";
  const userId = params.get("user_id") || "";

  const usage = "Usage: /note <body> [person:<name>] [project:<name>] [tag:<TAG>]";
  if (!text) {
    return Response.json({ response_type: "ephemeral", text: usage });
  }

  // Extract single-word tokens; order-independent. Body is whatever remains.
  let rest = text;
  const grab = (re) => {
    const m = rest.match(re);
    if (!m) return "";
    rest = rest.replace(m[0], "").replace(/\s+/g, " ").trim();
    return m[1];
  };
  const personRaw = grab(/\bperson:(\S+)/i);
  const projectRaw = grab(/\bproject:(\S+)/i);
  const tagRaw = grab(/\btag:(\S+)/i);
  const body = rest.trim();

  if (!body) {
    return Response.json({ response_type: "ephemeral", text: usage });
  }

  ctx.waitUntil(
    dispatchToGitHub(env, "note_add.yml", {
      body,
      response_url: responseUrl,
      person_raw: personRaw,
      project_raw: projectRaw,
      tag_raw: tagRaw,
      channel_id: channelId,
      user_id: userId,
    }).then(ok => {
      if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue note — GitHub dispatch error. Try again or check the PAT.");
    })
  );

  return Response.json({ response_type: "ephemeral", text: "Adding note..." });
}
```

- [ ] **Step 2: Generalize `handleSlackInteractive` to route by action-id prefix**

In `handleSlackInteractive`, the current logic reads:

```javascript
  const action = payload.actions?.[0];
  if (!action || !action.action_id.startsWith("assign_owner")) {
    return Response.json({ text: "Unknown action." });
  }

  let taskData;
  try {
    taskData = JSON.parse(action.value);
  } catch {
    return Response.json({ text: "Invalid action data." });
  }

  const { title, due_date_raw = "", owner_raw } = taskData;
  const responseUrl = payload.response_url || "";

  ctx.waitUntil(
    dispatchToGitHub(env, "task_add.yml", {
      title,
      response_url: responseUrl,
      due_date_raw,
      owner_raw,
    }).then(ok => {
      if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue task — GitHub dispatch error. Try again or check the PAT.");
    })
  );

  // Replace the buttons immediately with a visible processing state
  return Response.json({
    replace_original: true,
    text: `⏳ Assigning to ${owner_raw}...`,
    blocks: [
      {
        type: "section",
        text: { type: "mrkdwn", text: `⏳ Assigning *${title}* to ${owner_raw}...` },
      },
    ],
  });
```

Replace that entire span (from `const action = payload.actions?.[0];` through the final `});` of the task `Response.json`) with:

```javascript
  const action = payload.actions?.[0];
  const responseUrl = payload.response_url || "";

  let data;
  try {
    data = JSON.parse(action?.value || "{}");
  } catch {
    return Response.json({ text: "Invalid action data." });
  }

  // Note person disambiguation → note_add.yml
  if (action?.action_id?.startsWith("link_note_person")) {
    const { body, project_raw = "", tag = "", person_raw = "" } = data;
    ctx.waitUntil(
      dispatchToGitHub(env, "note_add.yml", {
        body,
        response_url: responseUrl,
        person_raw,
        project_raw,
        tag_raw: tag,
      }).then(ok => {
        if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue note — GitHub dispatch error. Try again or check the PAT.");
      })
    );
    const who = person_raw || "no one";
    return Response.json({
      replace_original: true,
      text: `⏳ Saving note (→ ${who})...`,
      blocks: [
        { type: "section", text: { type: "mrkdwn", text: `⏳ Saving note (→ ${who})...` } },
      ],
    });
  }

  // Task owner disambiguation → task_add.yml (unchanged behavior)
  if (action?.action_id?.startsWith("assign_owner")) {
    const { title, due_date_raw = "", owner_raw } = data;
    ctx.waitUntil(
      dispatchToGitHub(env, "task_add.yml", {
        title,
        response_url: responseUrl,
        due_date_raw,
        owner_raw,
      }).then(ok => {
        if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue task — GitHub dispatch error. Try again or check the PAT.");
      })
    );
    return Response.json({
      replace_original: true,
      text: `⏳ Assigning to ${owner_raw}...`,
      blocks: [
        { type: "section", text: { type: "mrkdwn", text: `⏳ Assigning *${title}* to ${owner_raw}...` } },
      ],
    });
  }

  return Response.json({ text: "Unknown action." });
```

- [ ] **Step 3: Add the `/slack/note` route**

In the `fetch` handler, the routes currently read:

```javascript
    if (url.pathname === "/slack/task") {
      return handleSlackTask(request, env, ctx);
    }

    if (url.pathname === "/slack/interactive") {
      return handleSlackInteractive(request, env, ctx);
    }
```

Add the note route:

```javascript
    if (url.pathname === "/slack/task") {
      return handleSlackTask(request, env, ctx);
    }

    if (url.pathname === "/slack/note") {
      return handleSlackNote(request, env, ctx);
    }

    if (url.pathname === "/slack/interactive") {
      return handleSlackInteractive(request, env, ctx);
    }
```

- [ ] **Step 4: Syntax-check the worker**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
node --check cloudflare/telegram-bridge.js && echo "ok"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add cloudflare/telegram-bridge.js
git commit -m "feat: /slack/note route + generalized interactive routing"
```

- [ ] **Step 6: Deploy + Slack app config (manual, requires credentials)**

These steps happen outside the repo and require Cloudflare + Slack admin access:

1. Deploy the worker: `cd cloudflare && npx wrangler deploy` (uses `wrangler.toml`).
2. In the Slack app config, create a slash command `/note` pointing at `https://<worker-host>/slack/note`.
3. Confirm the Interactivity Request URL is `https://<worker-host>/slack/interactive` (already set for `/task`; unchanged).
4. End-to-end test in Slack:
   - `/note ping test` → ephemeral "Adding note...", then "Note added: ping test". Verify a new line in `data/notes.jsonl` on `main`.
   - `/note call Acme project:acme tag:SALES` → confirmation shows the project name and `[SALES]`.
   - `/note follow up person:<ambiguous first name>` → disambiguation buttons appear; clicking one (or "No person") creates the note.
   - `/note idea tag:NONSENSE` → confirmation notes the tag was skipped.

> If you lack deploy/Slack access, stop after Step 5; the route logic is covered by the `node --check` in Step 4 and the script's unit tests in Task 8. Note that deployment was not performed.

---

## Self-Review

**Spec coverage:**
- `project_id` data-model field → Task 1 (replay) + Task 2 (POST). ✓
- Project picker in capture modal → Task 4. ✓
- Linked Notes on People tab → Task 6. ✓
- Project Notes sub-section + expandable task-row notes (with roll-up) on Work tab → Task 7. ✓
- `/note` worker route with person/project/tag tokens → Task 10. ✓
- `note_add.yml` → Task 9. ✓
- `slack_add_note.py` with person fuzzy/disambiguation, project best-match-or-skip, unknown-tag drop → Task 8. ✓
- Person interactive disambiguation; generalized `/slack/interactive` by action prefix → Task 8 (buttons) + Task 10 (routing). ✓
- `.gitattributes` union merge → Task 3. ✓
- Project name in brief (`_format_note_line` + `load_notes_for_brief`) → Task 1. ✓
- Tests: `test_notes_lib.py` extended (Task 1), new `test_slack_add_note.py` (Task 8). ✓
- Out-of-scope honored: no `brief` flag on `/note` (Task 10 tokens omit it); no silent tag creation (Task 8 `resolve_tag` drops unknowns); no project disambiguation buttons (Task 8 `best_match_project`). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type/name consistency:** `add_note` signature (Task 1) matches the call in Task 8. `openNoteModal(note, onChange)` (Task 5) matches calls in Tasks 6 & 7. `linkedNoteLinesHtml`/`wireLinkedNoteClicks` (Task 5) used in Tasks 6 & 7. `renderTaskRow(task, people, withLinkProj, notesForTask)` (Task 7) matches both call sites updated in the same task. `notesState._projects` introduced in Task 4, reused in Task 5 (`renderNoteCard`) and Task 6. Worker `note_add.yml` inputs (`body`, `person_raw`, `project_raw`, `tag_raw`, `response_url`, `channel_id`, `user_id`) in Task 10 match the workflow inputs in Task 9 and the env vars read in Task 8. ✓
