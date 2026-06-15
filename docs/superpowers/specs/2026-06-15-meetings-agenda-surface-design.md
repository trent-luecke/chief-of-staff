# Meetings Agenda Surface — Design

**Date:** 2026-06-15
**Status:** Approved (design); ready for implementation planning
**Scope:** Project 1 of 2 (the editable surface). Project 2 (move nudge/reply channel to Slack) is a separate follow-on spec.

## Problem

Trent has several standing internal meetings (1:1s and group syncs) that recur weekly. He wants one place per meeting to:

- **Prep before** — review what's still open and prioritize talking points.
- **Capture during/after** — log what was discussed, record new action items, close out open loops.

He framed this as possibly fitting in the Notes or People tab. It does not — those are single-record card surfaces. A per-meeting running document with prep + persistent open loops + dated history is its own thing.

## Key finding: ~80% already exists, but it's invisible

The repo already has a meeting-memory system:

- [data/meeting_index.json](../../../data/meeting_index.json) maps 6 recurring meetings (by calendar pattern) to `data/meeting_memory/*.md` docs.
- Each doc has **Current State / Open Threads / Session Log** sections.
- It is populated reactively: [nudger.py](../../../nudger.py) sends a Telegram nudge after a meeting → Trent replies → [reply_collector.py](../../../reply_collector.py) calls `rewrite_meeting_memory` ([processors/meeting_memory.py:76](../../../processors/meeting_memory.py)) which has Claude **rewrite the whole doc**.
- The morning brief surfaces the last session via `load_last_session_summary` ([pipeline.py:158](../../../pipeline.py)).
- These files are git-tracked (the `.gitignore` allow-list un-ignores `data/meeting_memory/**`).

### The three real gaps

1. **Invisible & read-only outside email.** No way to open, scan loops, or edit.
2. **Reactive only.** Contributions happen *after* a meeting; there's no place to prep *before*.
3. **AI-synthesized & auto-pruned.** The full rewrite drops threads cold for 2 sessions and entries >30 days old — so anything Trent wants to *keep* can silently vanish.

## Approved decisions

| Decision | Choice |
|----------|--------|
| AI vs. manual ownership | **Manual owns Agenda + Open Threads; AI only ever appends to the Session Log.** Never rewrites curated sections. |
| Nudge/reply channel | Move Telegram → **Slack** — **deferred to Project 2** (orthogonal channel swap). |
| Action items ↔ Tasks registry | **Self-contained in the meeting doc, with optional promote-to-task** into the Work tab. |
| Surface location | **New "Meetings" tab** in the Registry UI (not Notes/People). |
| Adding new meetings | **"New Meeting" form in v1** writes config + seeds the doc — no hand-editing JSON. |
| People links | **Multiple** people per meeting, linked from the People registry. |
| Storage | **Event-sourced `data/meetings.jsonl`** (`merge=union`), modeled on `notes.jsonl`. |

## Project decomposition

- **Project 1 (this spec): the Meetings surface.** New tab + structured editing (Agenda / Open Threads / Session Log) + New Meeting form + promote-to-task + backend endpoints/git-sync + the Option-1 safety change (reply append-only, no full rewrite). Delivers the full prep+capture value **even with nudges still on Telegram**.
- **Project 2 (follow-on spec): Slack channel migration.** `nudger.py` sends to Slack; reply collection reads the Slack thread. No UI or data-model change.

The append-only safety change lives in Project 1 because it is what makes manual ownership safe; the channel is independent.

## The document: three zones

When a meeting is opened, the UI shows one scrollable doc, top to bottom:

### 1. Agenda (prep — user-owned)
Editable, reorderable list of talking points for *next time*. Persists until the user clears items. Nothing auto-deletes it. This is the open-before-the-meeting surface.

### 2. Open Threads (open loops — user-owned)
Checklist of unresolved items carrying across meetings. Each thread has:
- a **checkbox to close it** (closed items grey out, then drop off after a short window so the list stays live);
- an optional **→ person** tag (owner), chosen from the meeting's linked people / registry;
- a **↗ promote-to-task** button that creates a real task in the Work tab linked back to this meeting; the returned `task_id` is stored on the thread (button then shows "linked").

### 3. Session Log (history — user + AI append-only)
Dated entries (`YYYY-MM-DD`), newest first, of what was discussed. The user can add an entry by hand any time. Once Project 2 is live, nudge replies are AI-drafted into a new entry here. **This is the only zone automation ever writes to.**

**Header:** meeting name, linked people (clickable → People records), last-met date.

**Mental model:** Agenda flows down into the Session Log. Prep talking points → meet → record a session entry → unresolved items become Open Threads → closed threads drop off. All manual; AI only *adds* session history.

## Adding / editing meetings

A recurring meeting = one [meeting_index.json](../../../data/meeting_index.json) entry + its doc content. A **"New Meeting"** form captures:

- **Display name** → derives the `memory_file` slug.
- **Calendar match pattern** (optional) → ties the doc to calendar events for brief prep / nudges. Blank = standalone agenda doc that won't auto-match an event.
- **People links** (optional, multiple) → from the People registry.
- **Nudge settings** (subject + minutes-after, optional, sensible defaults) → only matters once Project 2 lands.

The form writes the `meeting_index.json` entry and seeds a `create` event in `meetings.jsonl`, both committed to `origin/main` via the existing git-sync path. **v1 = add + edit.** Delete/archive is deferred.

## Storage & data model

### `data/meetings.jsonl` (new, event-sourced, `merge=union`)
Modeled on [notes.jsonl](../../../data/notes.jsonl) / [lib/notes.py](../../../lib/notes.py). Replayed server-side by a new **`lib/meetings.py`**. Event types (illustrative):

- `create` — `{meeting_id (slug), ts}` (config/metadata lives in `meeting_index.json`)
- `update_agenda` — replaces the ordered agenda item list
- `add_thread` / `update_thread` / `toggle_thread` / `delete_thread` — open-thread lifecycle; `update_thread` carries `person_id` and/or `task_id`
- `add_session` — appends a dated Session Log entry `{date, body}` (used by manual add **and** the reply append path)

`lib/meetings.py` provides:
- `replay_meetings(path)` → current state per meeting (agenda list, open threads with state/links, session log).
- `render_for_prep(meeting)` → markdown rendering of open threads + recent sessions, for the brief/prep prompt (drop-in for what `storage.read(markdown)` returned).
- `last_session(meeting)` → last session text, for `pipeline.py`.

**Concurrency rationale:** the AI session-append and live UI edits both push to `origin/main` and will collide. `merge=union` (already used for `tasks.jsonl` and `notes.jsonl`) makes concurrent appends conflict-free. A single JSON-per-meeting file would produce 502 push-conflicts when a nudge reply lands mid-edit. Add `data/meetings.jsonl merge=union` to [.gitattributes](../../../.gitattributes).

### `data/meeting_index.json` (existing, extended)
Add `name` and `people_ids` to each entry; keep `calendar_pattern`, `memory_file`, `nudge_subject`, `nudge_minutes_after`. Written by the New Meeting form + edits.

## Backend (Flask, `tools/server.py`)

New endpoints following the Notes pattern (read from replay; every write appends an event and pushes to `origin/main` via the existing git-sync helpers; offline → 503, failed push → 502):

- `GET /api/meetings` — list meetings (config from `meeting_index.json` joined with replayed doc state).
- `GET /api/meetings/<id>` — one meeting's full doc.
- `POST /api/meetings` — New Meeting (writes `meeting_index.json` entry + `create` event).
- `PATCH /api/meetings/<id>` — update config (name, people_ids, calendar pattern, nudge settings).
- `PUT /api/meetings/<id>/agenda` — replace agenda list (`update_agenda`).
- `POST /api/meetings/<id>/threads`, `PATCH .../threads/<tid>`, `DELETE .../threads/<tid>` — thread lifecycle (incl. close, person tag).
- `POST /api/meetings/<id>/threads/<tid>/promote` — create a registry task and link it back.
- `POST /api/meetings/<id>/sessions` — add a Session Log entry.

Add `data/meetings.jsonl` (and `meeting_index.json` when touched) to the git-sync commit set.

## UI (`tools/registry_ui.html`)

- New **"Meetings"** tab button + view, vanilla JS in the single file (same pattern as the Notes tab).
- Meeting list → click opens the three-zone doc.
- Agenda: editable reorderable list. Open Threads: checklist with close / person-tag / promote-to-task. Session Log: dated entries, newest first, with "add session" + manual entry.
- "New Meeting" form (modal) writing `POST /api/meetings`.
- Reuses existing People typeahead (for person tags / people links) and the task-create plumbing (for promote).

## Integration changes (repoint from markdown → replay)

- [reply_collector.py:94](../../../reply_collector.py) — **drop `rewrite_meeting_memory`**; replies append a **session event** only (Option-1 safety change). Keeps Telegram for now (channel swap is Project 2).
- [ask.py:99](../../../ask.py) — same append-session change.
- [pipeline.py:158](../../../pipeline.py) `load_last_session_summary` → `lib/meetings.last_session(...)`.
- [processors/meeting_prep.py:360](../../../processors/meeting_prep.py) `build_recurring_internal_context` → `lib/meetings.render_for_prep(...)` instead of `storage.read(markdown)`.
- Keep `load_meeting_index` / `find_meeting_for_event` in [processors/meeting_memory.py](../../../processors/meeting_memory.py) (still used). `rewrite_meeting_memory` is no longer called.

## One-time migration

The 6 existing `meeting_memory/*.md` files are nearly empty (a "Current State" blurb; no threads/log yet). A small migration script:
1. Seeds a `create` event per meeting in `meetings.jsonl`.
2. Carries each "Current State" blurb in as the first dated `add_session` entry (labeled background) so nothing is lost.
3. Backfills `name` / `people_ids` defaults into `meeting_index.json`.

The old markdown files are then retired (untracked/removed once the replay is the source of truth).

## Error handling

- Server offline → 503 + UI banner (existing Registry UI behavior).
- Failed `origin/main` push → 502, no phantom success (existing behavior).
- Concurrent appends → resolved by `merge=union`; no user-visible conflict.
- AI session-append (reply path) remains **non-fatal**: a failed draft/append must not break the nudge flow.
- Promote-to-task failure → thread stays un-linked; surfaced as an error, no partial state.

## Testing

- `lib/meetings.py` unit tests (modeled on [tests/test_notes_lib.py](../../../tests/test_notes_lib.py)): replay of each event type, thread close/drop-off window, `render_for_prep` / `last_session` output, empty/missing file.
- Endpoint smoke tests for each route (create meeting, agenda replace, thread lifecycle, promote-to-task, add session).
- Migration script: assert 6 meetings created, Current State preserved as first session, `meeting_index.json` backfilled.
- Regression: brief still renders last-session text; `meeting_prep` still produces recurring-internal context.

## Out of scope (Project 1)

- Slack nudge/reply channel (Project 2).
- Delete/archive meetings in the UI.
- Editing the AI's behavior beyond append-only.
- "Current State" as a maintained AI-synthesized zone (dropped from the model; replaced by user-owned Agenda + Open Threads).
