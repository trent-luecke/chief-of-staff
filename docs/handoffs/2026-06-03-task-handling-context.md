# Task Handling — Current State Handoff

**Date:** 2026-06-03  
**Purpose:** Context for a new session to understand where task handling stands and what needs to change before adding a Tasks tab to the entity UI.

---

## What the task ledger looks like now

Tasks live in `data/tasks.jsonl` — an append-only JSONL event log. Three event types:

```json
{"event": "create", "task_id": "t-abc123", "title": "Follow up with Acme", "source": "avoma", "created_at": "2026-06-03", "due_date": null, "metadata": {"avoma_uuid": "...", "thread_ts": "..."}, "project_id": "acme-outreach", "collaborators": []}
{"event": "complete", "task_id": "t-abc123", "completed_at": "2026-06-04"}
{"event": "edit", "task_id": "t-abc123", "patch": {"project_id": "new-project"}}
```

`lib/tasks.py` is the single ledger. Public API: `add_task`, `complete_task`, `complete_task_by_id`, `edit_task`, `get_open_tasks`, `get_recent_completions`. Replay reconstructs current state on each read. Migration from the old `tasks.json` whole-file format is automatic on first read.

---

## Current task entry points

### 1. Telegram (primary, general-purpose)
- `ask.py` → `processors/query_tools.py` → Claude tool-use loop
- Tools: `add_task` (adds to ledger, then `_sync_canvas`), `complete_task` (marks done, then `_sync_canvas`), `list_tasks`
- After every task mutation, `_sync_canvas` rewrites the Slack canvas
- This is the main way Trent creates and manages tasks today

### 2. Avoma Phase 2 (Slack, Avoma-specific)
- Avoma meeting notification lands in Slack → reply triggers `processors/avoma_phase2.py`
- "add 1, 2" or "add all" → `add_task` with `source="avoma"` and metadata (avoma_uuid, thread_ts, call_title, call_date) → `_sync_canvas`
- This path already lives in Slack

### 3. Entity UI (new, project-attached only)
- `tools/server.py` Flask server at `http://localhost:8787`
- `POST /api/tasks` → `add_task` with `source="ui"`
- Currently only surfaced inside a project detail view — no standalone task creation
- Does **not** sync canvas (canvas sync only happens via `_sync_canvas` in query_tools/avoma_phase2)

---

## The Slack canvas

`lib/slack_canvas.py` → `sync_task_canvas(user_token, canvas_id, open_tasks, recent_completions)`

- Rewrites a canvas in Trent's Slack self-DM on every task mutation via Telegram or Avoma
- Canvas ID and channel ID are stored in `config.json` under `slack_canvas`
- It's a full rewrite every time (not incremental)
- Canvas is currently the **only persistent visual task board** — nothing else shows all tasks in one place

`_sync_canvas` is called from:
- `processors/query_tools.py` — after `add_task` or `complete_task` via Telegram
- `processors/avoma_phase2.py` — after "add N" task selection from an Avoma thread

---

## What's NOT built yet (the gap)

1. **No Slack-native general task management** — creating/completing tasks from a Slack DM or channel (outside of Avoma threads) doesn't exist. You can only do that via Telegram today.

2. **No flat "all tasks" view in the entity UI** — the UI only shows tasks inside a project detail panel. Standalone tasks (no `project_id`) are invisible in the UI.

3. **Entity UI doesn't sync the canvas** — tasks added via the UI won't appear on the canvas until the next Telegram or Avoma interaction triggers `_sync_canvas`.

---

## The intended direction

Move task creation/management from Telegram to Slack as the primary interface. Specific goals (not yet scoped in detail):

- Be able to add/complete tasks from a Slack DM or dedicated channel, not just from Avoma threads
- The entity UI becomes the primary task board (replacing the canvas as the visual projection surface)
- Canvas sync may be retired or kept as a secondary projection once the entity UI Tasks tab exists

### Why to finalize the Slack move BEFORE adding the Tasks tab

The Tasks tab in the entity UI would show all tasks, including standalone ones. But if task creation is still Telegram-primary, the UX is split: some tasks flow from Slack/UI, others from Telegram, and the canvas may or may not reflect the full picture depending on which path was used. Better to settle the Slack entry point first, then build the unified view on top of a clean model.

---

## Key files

| File | Role |
|------|------|
| `lib/tasks.py` | Task ledger — JSONL event log, all public task functions |
| `lib/slack_canvas.py` | Canvas rewrite — `sync_task_canvas(token, canvas_id, open_tasks, recent_completions)` |
| `processors/query_tools.py` | Telegram tool handlers — `_tool_add_task`, `_tool_complete_task`, `_tool_list_tasks`, `_sync_canvas` |
| `processors/avoma_phase2.py` | Avoma Slack thread handler — "add N" task selection + canvas sync |
| `ask.py` | Telegram query handler entry point |
| `tools/server.py` | Flask server — `/api/tasks` CRUD, no canvas sync |
| `tools/registry_ui.html` | Entity UI — projects tab with per-project task panels |
| `config.json` | `slack_canvas.canvas_id` and `slack_canvas.channel_id` |

---

## Things to decide in the new session

1. **What Slack surface for general task management?** Options:
   - A dedicated channel (e.g. `#tasks`) where messages to the bot create/complete tasks
   - The existing Slack DM where Avoma threads live (extend the existing watcher)
   - A Slack shortcut or slash command

2. **Does canvas sync stay or go?** Once the entity UI has a Tasks tab, the canvas becomes redundant. But if the entity UI is local-only (requires running `tools/server.py`), the canvas may still be useful as an always-on view.

3. **Should the entity UI canvas sync be added?** If the canvas stays, the `POST /api/tasks` endpoint in the Flask server should also call `_sync_canvas`. Right now it doesn't.
