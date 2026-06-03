# Registry UI Tasks Tab — Session Handoff

**Date:** 2026-06-03  
**Goal for next session:** Add a Tasks tab to the Registry UI that shows all open tasks and supports complete, edit due date, and link to project.

---

## What was built today: Slack task slash command

Task creation moved from Telegram to Slack via `/task <title> [due:<date>]`. The full flow:

1. `/task` anywhere in Slack → Cloudflare Worker (`cloudflare/telegram-bridge.js`, `/slack/task` route)
2. Worker verifies Slack HMAC signature, responds immediately with ephemeral "Adding task..."
3. Worker dispatches `task_add.yml` GitHub Actions workflow with `title`, `response_url`, `due_date_raw`
4. Workflow runs `scripts/slack_add_task.py` → `add_task(storage, title, source="slack", due_date=...)` → commits `data/tasks.jsonl` → pushes → posts Slack confirmation

Due date parsing: `dateparser` primary, `python-dateutil` fallback. `due:` must be at end of command and captures everything after it (`due:next tuesday` works).

---

## Current task management surfaces

| Surface | Can add | Can complete | Can edit | Can link project |
|---------|---------|--------------|----------|-----------------|
| Slack `/task` | ✅ | ❌ | ❌ | ❌ |
| Avoma Slack threads | ✅ (from call actions) | ❌ | ❌ | ❌ |
| Registry UI (current) | ✅ (per-project only) | ✅ | ✅ | ✅ |
| Telegram bot | ✅ | ✅ | ✅ | ❌ |

The Registry UI is the intended management surface. Right now tasks only appear inside project detail panels — there is no flat "all tasks" view.

---

## Task data model

Tasks live in `data/tasks.jsonl` — an append-only event log. Three event types:

```json
{"event": "create", "task_id": "t-a38238", "title": "lay our core principles planning for OS", "source": "slack", "created_at": "2026-06-03", "due_date": null, "metadata": {}, "project_id": null, "collaborators": []}
{"event": "complete", "task_id": "t-a38238", "completed_at": "2026-06-04"}
{"event": "edit", "task_id": "t-a38238", "patch": {"due_date": "2026-06-10", "project_id": "acme"}}
```

`lib/tasks.py` public API:
- `get_open_tasks(storage)` → list of task dicts
- `get_recent_completions(storage, days=7)` → list
- `add_task(storage, title, source, due_date, project_id, ...)` → dict
- `complete_task_by_id(storage, task_id)` → dict | None
- `edit_task(storage, task_id, patch)` → dict | None

---

## Registry UI server — current API endpoints

Flask server at `tools/server.py`, runs at `http://localhost:8787`.

Task endpoints (all backed by `lib/tasks.py` + auto git push after mutations):
- `GET /api/tasks` — all open tasks (optional `?project_id=` filter)
- `POST /api/tasks` — create task (returns `{"task": ..., "push": ...}`)
- `PATCH /api/tasks/<task_id>` — edit task (returns `{"task": ..., "push": ...}`)
- `POST /api/tasks/<task_id>/complete` — complete task (returns `{"task": ..., "push": ...}`)

Project endpoints:
- `GET /api/projects` — list projects
- `POST /api/projects` — create project
- `PATCH /api/projects/<project_id>` — update project

---

## Registry UI frontend

**File:** `tools/registry_ui.html` — single HTML file, vanilla JS, no build step.

Current tabs: **People** | **Projects**

The Projects tab shows project cards with a task panel per project (filtered by `project_id`). There is no standalone task view — tasks without a `project_id` are invisible in the UI today.

---

## What the Tasks tab needs to do

- Show all open tasks (not filtered by project) in a flat list
- Each row: title, due date (if set), project link (if set), complete button
- Inline edit: click due date to change it, click project to link/re-link
- Complete button → `POST /api/tasks/<id>/complete`
- Ideally sorted by: due date (nulls last), then created_at

The canvas (`lib/slack_canvas.py`) is the current always-on task board — it will become redundant once this tab exists. Don't retire it in this session; just build the tab and the canvas naturally takes a back seat.

---

## Key files

| File | Role |
|------|------|
| `tools/registry_ui.html` | UI — add Tasks tab here |
| `tools/server.py` | Flask API — endpoints already exist |
| `lib/tasks.py` | Task ledger — all read/write functions |
| `data/tasks.jsonl` | Live task data |
| `data/projects_registry.json` | Projects data (for linking tasks to projects) |
