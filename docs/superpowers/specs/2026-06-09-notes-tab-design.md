# Notes Tab — Design Spec

**Date:** 2026-06-09  
**Status:** Approved  
**Branch:** feat/brief-overhaul-doc2

---

## Overview

A personal note-capture surface built into the Registry UI. Replaces the habit of using Slack DMs as an unstructured capture inbox. Notes can be tagged, linked to people and tasks at creation time, and flagged to surface in the morning brief.

This is a net-new 5th tab in `registry_ui.html`. No existing tabs (Pending, People, Observations, Work) are modified.

---

## Scope

### In scope
- Notes tab with masonry card layout
- Floating `+` capture button accessible from every tab
- Note creation and editing modal
- Tag system with custom colors
- Searchable person and task pickers (linking at creation time)
- "Include in brief" flag with calendar-date-based brief integration
- 8 new API endpoints in `server.py`
- `data/notes.jsonl` and `data/notes_tags.json` new data files
- `main.py` brief integration — Today's Notes / Yesterday's Notes sections

### Backlog (not in this build)
- **Option C** — linked notes surfacing inline on People and Work tab cards
- **Slack bot `/note` command** — remote capture via slash command that writes to `data/notes.jsonl`
- **Query surface migration** — Telegram → Slack bot, `get_notes(person_id)` tool in `query_tools.py`, Pinecone ingest at note creation (immediate follow-on spec)

---

## Data Model

### `data/notes.jsonl`

Event-sourced JSONL, same pattern as `data/tasks.jsonl`. Server replays events to derive current state. Deletes are tombstones; updates are partial patches.

```jsonl
{"event":"create","id":"n-abc123","ts":"2026-06-09T09:14:00","body":"Acme Corp seems close — follow up after board meeting Thursday.","tags":["SALES"],"person_id":"jake-thompson","task_id":null,"brief":false,"pinned":false}
{"event":"update","id":"n-abc123","ts":"2026-06-09T09:20:00","tags":["SALES","ACTION"],"brief":true}
{"event":"pin","id":"n-abc123","ts":"2026-06-09T09:26:00","pinned":true}
{"event":"delete","id":"n-abc123","ts":"2026-06-09T09:30:00"}
```

**Fields on `create` events:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `event` | string | yes | `"create"` |
| `id` | string | yes | `n-<hex>` prefix |
| `ts` | ISO datetime | yes | Creation timestamp — used for brief bucketing |
| `body` | string | yes | Note text |
| `tags` | string[] | yes | Tag IDs from `notes_tags.json`; may be empty |
| `person_id` | string\|null | yes | Slug from `people_registry.json` |
| `task_id` | string\|null | yes | ID from `tasks.jsonl` |
| `brief` | boolean | yes | Whether to surface in morning brief |
| `pinned` | boolean | yes | Whether pinned to top of Notes tab |

`person_id` and `task_id` are nullable — linking is always optional. The slug is the join key for future Pinecone integration (follow-on spec).

**Important:** `brief: true` is never auto-cleared in the JSONL. The brief flag is treated as expired by the UI and `main.py` based on `creation_date` relative to today's date (see Brief Integration section). This preserves full history and allows re-flagging to resurface a note.

### `data/notes_tags.json`

Tag registry. Simple array, no sub-tags.

```json
[
  {"id": "SALES", "color": "#2a6b3a"},
  {"id": "ACTION", "color": "#3a5a8a"},
  {"id": "IDEAS", "color": "#5a3a7a"},
  {"id": "PERSONAL", "color": "#6b4a2a"}
]
```

Tag IDs are uppercase, no spaces. Color is a hex string used to tint note card borders in the UI.

---

## Notes Tab UI

### Layout

A 5th tab added to `registry_ui.html` after Work. Header bar + masonry grid below.

**Header bar:**
- Search input — filters by text content or date string
- Active tag filter chips — one chip per tag; clicking toggles filter; multiple active tags = AND filter; all tags shown as inactive chips by default
- `Manage Tags` button — opens tag management panel (see Tag Management section)
- Sort toggle: newest first (default) / oldest first
- Group by date toggle: inserts date section headers between day groups in the grid
- Compact view toggle: reduces card padding and font size

**Masonry grid:**
- CSS `columns: 3` — no JS masonry library; native CSS columns
- Pinned notes rendered in a `PINNED` section above the main grid (same pattern as MindChuk)
- Cards are variable height — content is never truncated

**Note card anatomy:**
- Border colored to match the card's primary tag (first tag in the array); grey if no tags
- Timestamp top-left
- Tag chips below timestamp
- Body text — full content, no truncation
- If `person_id` is set: `→ [Person Name]` link indicator
- If `task_id` is set: `↗ [Task Title]` link indicator
- If `brief: true` AND `creation_date >= today - 2 days` (calendar): brief badge shown
- If pinned: pin icon top-right

Clicking a card opens the edit modal.

---

## Capture Modal + Floating Button

### Floating button

A fixed `+` button in the bottom-right corner of the app, rendered outside any tab panel so it is visible on all tabs. Clicking opens the capture modal.

No context pre-population in this build (backlogged as part of Option C).

### Capture modal

Fields in order:

1. **Text area** — free-form note body; autofocused on modal open
2. **Tag selector** — existing tags shown as chips; click to toggle; `+ New Tag` opens inline name + color picker to create a tag without leaving the modal
3. **Person picker** — searchable typeahead against `GET /api/people`; optional; clears to null if emptied
4. **Task picker** — searchable typeahead against `GET /api/tasks`; optional; only open tasks shown; clears to null if emptied
5. **Include in brief** — toggle, off by default
6. **Save / Cancel** — Save writes `create` event to `notes.jsonl` via `POST /api/notes`

Both pickers are type-to-search — user types a name/title and matching results appear as a dropdown. Not static dropdowns.

### Edit modal

Same layout as capture modal, pre-populated with existing note data. Adds:
- **Delete button** (bottom-left) — writes `delete` tombstone event via `DELETE /api/notes/<id>`
- **Pin / Unpin button** — writes `pin` event via `PATCH /api/notes/<id>`

Save in edit modal writes an `update` event with only changed fields.

---

## Tag Management

Accessed via `Manage Tags` button in Notes tab header. Opens an inline panel listing all tags from `notes_tags.json`.

**Per-tag actions:**
- Rename — edits the `id` field; updates tag references on existing notes in-memory (UI re-renders with new name; backend patches affected notes in JSONL)
- Recolor — opens color picker inline
- Delete — removes from `notes_tags.json`; existing notes retain the tag string but render it in grey (no color treatment)

Tag names: uppercase, no spaces. Tag colors: hex string.

---

## Server API

All new endpoints added to `tools/server.py`. Notes are stored in `data/notes.jsonl`; tags in `data/notes_tags.json`.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/notes` | Replay events, return current note state as array |
| `POST` | `/api/notes` | Append `create` event |
| `PATCH` | `/api/notes/<id>` | Append `update` or `pin` event |
| `DELETE` | `/api/notes/<id>` | Append `delete` tombstone event |
| `GET` | `/api/notes/tags` | Return `notes_tags.json` |
| `POST` | `/api/notes/tags` | Append new tag to `notes_tags.json` |
| `PATCH` | `/api/notes/tags/<id>` | Rename or recolor a tag |
| `DELETE` | `/api/notes/tags/<id>` | Remove tag from `notes_tags.json` |

Existing endpoints used by the Notes tab (no changes needed):
- `GET /api/people` — person picker typeahead
- `GET /api/tasks` — task picker typeahead

---

## Brief Integration (`main.py`)

At brief generation time, `main.py` replays `data/notes.jsonl` and filters for notes where `brief: true`. Notes are bucketed by **calendar date** of creation relative to the brief run date:

```
brief_date = date the brief runs (today)

todays_notes    = notes where brief=True AND creation_date == brief_date - 1 day
yesterdays_notes = notes where brief=True AND creation_date == brief_date - 2 days
```

If at least one bucket is non-empty, a **Notes** section is injected into the brief with subsections:
- **Today's Notes** — notes created yesterday
- **Yesterday's Notes** — notes created two days ago

Notes older than 2 calendar days are excluded entirely, regardless of `brief` flag value.

If both buckets are empty, the Notes section is omitted from the brief.

**Each note in the brief includes:** body text, tags, and person/task link name if present.

**Re-surfacing:** If a note needs to appear in a future brief (e.g., a note from 6/1 needs to be in the 6/15 brief), the user re-flags it from the Registry UI. The `ts` field on the new `update` event is NOT used for bucketing — bucketing always uses the original `create` event timestamp.

---

## Files Changed

| File | Change |
|------|--------|
| `tools/registry_ui.html` | Add Notes tab, masonry grid, floating `+` button, capture/edit modals, tag management panel |
| `tools/server.py` | Add 8 new endpoints for notes and tag CRUD |
| `main.py` | Add Notes section to brief (Today's Notes / Yesterday's Notes) |
| `data/notes.jsonl` | New file (created on first note save) |
| `data/notes_tags.json` | New file (created with empty array on first run or manually seeded) |

---

## Follow-On Spec (Immediate Next)

Query surface migration: Telegram → Slack bot, plus `get_notes(person_id?)` tool in `processors/query_tools.py`, plus Pinecone ingest at note creation time. This is what makes linked notes surfaceable in queries like "give me a rundown on Mike from Apex before my call."
