# Linked Notes + Slack `/note` — Design

**Date:** 2026-06-11
**Status:** Approved for planning

## Goal

Expand the existing Notes capability in two ways:

1. **Linked notes inline** — surface notes on the People and Work tabs, attached to the
   person and/or project (and/or task) they reference. Today notes carry `person_id` and
   `task_id` but nothing reads them back contextually, and there is no direct project link.
2. **`/note` Slack slash command** — capture a note from Slack, with optional person,
   project, and tag links, mirroring the existing `/task` pipeline.

## Context — what already exists

- **Notes tab** is fully built. `data/notes.jsonl` is an event-sourced log
  (`create`/`update`/`pin`/`delete`) replayed by `lib/notes.py::replay_notes`. Each note has
  `body`, `tags`, `person_id`, `task_id`, `brief`, `pinned`. CRUD lives in `tools/server.py`
  (`GET/POST /api/notes`, `PATCH/DELETE /api/notes/<id>`, tag endpoints). The capture modal in
  `tools/registry_ui.html` already has person + task typeahead pickers. **There is no
  `project_id`.**
- **Work tab** (`renderWorkView`) renders projects as collapsible groups (`proj-group-header`
  / `proj-group-body`) with task rows (`renderTaskRow`) underneath, plus a standalone-tasks
  section. Loads `projects`, `tasks`, `people` together via `Promise.all`.
- **People tab** (`renderRegistryView`, `data-view="registry"`) is a list of rows; clicking a
  row expands an inline `registry-detail` panel built by `buildDetailReadOnlyHtml(person, obs)`.
- **`/task` Slack flow** is the template for Item 2 and works end-to-end:
  `telegram-bridge.js` route `/slack/task` → `task_add.yml` → `scripts/slack_add_task.py` →
  `add_task()` → commit `tasks.jsonl` to `main`. It has natural-language date parsing, fuzzy
  owner matching against `people_registry.json`, and interactive disambiguation buttons handled
  by `/slack/interactive`.
- **Registry UI writes to `origin/main`** via a throwaway git worktree. The Slack flow commits
  to `main` from the GitHub Actions runner. Both target `main`.
- **`.gitattributes`** declares `data/tasks.jsonl merge=union` but **not** `data/notes.jsonl`.

## Item 1 — Linked notes inline on People & Work tabs

### Data model

Add `project_id` to the note record alongside `person_id` and `task_id`. A note may carry any
combination — person, project, task, or none.

- `lib/notes.py::replay_notes` — carry `project_id` through `create` and `update` events and
  into the replayed record (default `None`), exactly as `person_id` is handled today.
- `tools/server.py` — `POST /api/notes` reads `project_id` from the body (default `None`);
  `PATCH` accepts it in the update patch. No new endpoints.

The read path for all surfacing is the existing `GET /api/notes`, filtered client-side. No new
server work for reads — consistent with how the Work tab already loads its data.

### Capture modal (`tools/registry_ui.html`)

Add a third typeahead picker — **"Project (optional)"** — between the existing Person and Task
pickers, fed by `GET /api/projects`. Identical wiring to the person/task pickers
(`wireTypeahead`), writing to a hidden `note-project-id` input. The save path includes
`project_id` in the POST/PATCH body.

### People tab surfacing

In `buildDetailReadOnlyHtml` (the expanded person detail), append a **Linked Notes** section:

- Lists notes where `person_id === person.id`, newest first.
- Each note is a compact line: timestamp, tag chips, body snippet.
- Clicking a line opens the existing note edit modal (`openNoteModal`).
- The section is omitted entirely when the person has no linked notes.

The person detail is read-only HTML; the notes list is fetched once (the People tab can fetch
`GET /api/notes` alongside its existing registry load, or lazily on detail expand — fetch on
expand keeps the People-tab initial load unchanged).

### Work tab surfacing

`renderWorkView` already loads projects/tasks/people; add `GET /api/notes` to its `Promise.all`.

- **Project group body:** a **Notes** sub-section inside the expandable project body, listing
  notes where `project_id === p.id`. Same compact line format; click opens the edit modal.
- **Task rows:** a note affordance showing the count of notes linked to that task
  (`task_id === t.id`). Clicking the count **expands the linked note bodies inline** on the row
  (compact lines, each click-through to the edit modal) — not just a badge. Notes linked to a
  task also **roll up** into their parent project's Notes section, so nothing attached to a
  project's task is invisible at the project level.

Both tabs read the full notes list once and filter in memory.

## Item 2 — `/note` Slack slash command

Mirrors the `/task` pipeline:

```
Slack /note → telegram-bridge.js (/slack/note) → note_add.yml → scripts/slack_add_note.py
            → append create event to notes.jsonl → commit to main
```

### Worker (`cloudflare/telegram-bridge.js`)

New `/slack/note` route (clone of `handleSlackTask`):

- Verify Slack signature (reuse `verifySlackSig`).
- Parse order-independent tokens from `text`: `person:<name>` (single word), `project:<name>`
  (single word), `tag:<TAG>` (single word). Everything not consumed by a token is the note body.
- Dispatch `note_add.yml` with `body`, `person_raw`, `project_raw`, `tag`, `response_url`,
  `channel_id`, `user_id`.
- Return `"Adding note..."` ephemeral immediately; post a failure ephemeral on dispatch error.

### Workflow (`.github/workflows/note_add.yml`)

Clone of `task_add.yml` with note inputs. Commits `data/notes.jsonl` to `main`.

### Script (`scripts/slack_add_note.py`)

- **Person:** reuse `/task`'s fuzzy-match logic against `people_registry.json`. Ambiguous match
  → post interactive disambiguation buttons (see below); do not create the note yet.
- **Project:** fuzzy-match against `projects_registry.json` (new helper, same shape as the person
  matcher). **Best-match-or-skip:** take the top match; if none match, create the note with
  `project_id = None` and say so in the confirmation. No buttons for project.
- **Tag:** match against `notes_tags.json`. **Unknown tag → drop it** and note that in the
  confirmation. No silent tag creation from Slack — the tag vocabulary stays curated in the UI.
- Append a `create` event to `notes.jsonl` (`brief=false`, `pinned=false`), commit.
- Ephemeral confirmation, e.g. `Note added → Jane Doe / Acme Onboarding [SALES]`, listing only
  the links that resolved, plus any "tag X not found, skipped" / "no project match" notice.

### Disambiguation depth (decided)

**Person uses full interactive buttons; project uses best-match-or-skip.** The existing
`/slack/interactive` handler is hardcoded to dispatch `task_add`. Generalize it to route by
action-id prefix:

- `assign_owner*` → `task_add.yml` (unchanged behavior).
- `link_note_person*` → `note_add.yml`, carrying the note body / project_raw / tag forward in
  the button `value` payload so the note is created once the person is chosen.

This keeps exactly one interactive path for notes (person) and avoids doubling the button
machinery for project.

## Cross-cutting

- **`.gitattributes`:** add `data/notes.jsonl merge=union`. Without it, a Registry-UI write and a
  Slack write racing on `main` conflict on push. (`tasks.jsonl` already has this driver.)
- **Brief:** `lib/notes.py::_format_note_line` may optionally append the linked **project** name
  (it already appends the linked person). Minor, in-scope.
- **Tests:**
  - Extend `tests/test_notes_lib.py` — `project_id` carried through create/update replay.
  - New `tests/test_slack_add_note.py` — mirrors `test_slack_add_task.py`: token parsing
    (body/person/project/tag extraction), fuzzy person match, project best-match-or-skip,
    unknown-tag drop, confirmation formatting.

## Out of scope

- No `brief` flag on the `/note` command — Slack notes default to un-flagged and are triaged in
  the UI.
- No silent tag creation from Slack.
- No interactive disambiguation for project links.

## File map

| File | Change |
|------|--------|
| `lib/notes.py` | Carry `project_id` through replay; optional project name in `_format_note_line` |
| `tools/server.py` | Accept `project_id` in `POST`/`PATCH /api/notes` |
| `tools/registry_ui.html` | Project picker in capture modal; Linked Notes on person detail; Notes sub-section + expandable task-row notes on Work tab; `GET /api/notes` in Work load |
| `cloudflare/telegram-bridge.js` | `/slack/note` route; generalize `/slack/interactive` routing by action prefix |
| `.github/workflows/note_add.yml` | **Create** — clone of `task_add.yml` |
| `scripts/slack_add_note.py` | **Create** — note creation + person/project/tag resolution |
| `.gitattributes` | Add `data/notes.jsonl merge=union` |
| `tests/test_notes_lib.py` | `project_id` replay tests |
| `tests/test_slack_add_note.py` | **Create** — Slack note parsing/resolution tests |
