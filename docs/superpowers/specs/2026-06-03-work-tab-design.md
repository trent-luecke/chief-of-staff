# Work Tab Design

**Date:** 2026-06-03  
**Status:** Approved  
**Replaces:** Projects tab in `tools/registry_ui.html`

---

## Overview

Replace the existing "Projects" tab with a "Work" tab — a single surface showing project groups with nested tasks and a standalone section for unlinked tasks. The Projects tab currently makes tasks without a `project_id` invisible and requires clicking into a project to see its tasks. The Work tab fixes both.

---

## Layout

Two sections, always rendered in this order:

1. **Projects** — collapsible groups, one per project, active projects only (archived hidden by default)
2. **Standalone** — tasks with `project_id: null`, at the bottom

Tab label changes from "Projects" → "Work". The view div id changes from `view-projects` → `view-work`. `switchTab` is updated accordingly.

---

## Projects Section

### Group Header

Always visible whether expanded or collapsed:

```
▶  OS Planning   [active]   3 tasks   ✎
```

- Click header row → expand/collapse task list
- Click pencil (✎) → open inline edit panel; tasks remain visible below the edit form
- Pencil icon highlighted amber when edit mode is active

### Expanded Task List

Tasks sorted within each group: **overdue first → upcoming by date → no due date by created_at**.

Each task row:
```
[Done]  Task title                    Jun 15   → Nicole
```

- `[Done]` button → `POST /api/tasks/:id/complete` → row fades out and removes
- Due date chip:
  - Amber = upcoming
  - Red = overdue (label shows "Overdue" not the date)
  - Nothing = no due date set
  - Click chip → inline date input (saves via `PATCH /api/tasks/:id`)
- Owner chip (purple): only rendered when `owner ≠ null`. Clicking opens a dropdown to reassign or clear. Ghost `+ assign` chip appears on row hover for unowned tasks.

### Add-Task Form (bottom of each project group)

```
[ Task title…         ] [ Due date ] [ Assign to ▾ ] [Add]
```

- "Assign to" dropdown populated from `GET /api/people`, defaults to "Me" (submits `owner: null`)
- Submits `POST /api/tasks` with `project_id` set to the group's project

### New Project

`+ New Project` button in the Projects section header. Expands a simple inline form: project name input + Create button. Members and status are set after creation via the edit panel.

---

## Edit Panel (Pencil)

Opens inline below the group header, above the task list. Amber border indicates edit mode.

Fields:
- **Name** — text input
- **Status** — select: `active` / `archived`
- **Members** — chip-based people-picker (see below)

Save → `PATCH /api/projects/:id` → edit panel collapses.  
Cancel → discards changes, collapses.

### Members People-Picker

Existing members shown as chips:
```
[Nicole  owner ×]  [Luke  contact ×]  [+ Add]
```

Two-step flow for adding a member:

1. Click `+ Add` → person dropdown opens (people from `/api/people`; already-added members greyed out; searchable by name)
2. Select person → role picker appears:
   - **owner** — accountable, drives it
   - **contact** — point of contact, keep informed  
   - **collaborator** — working on it
3. Select role → chip added to the list
4. Click Save to persist

Click `×` on a chip to remove that member.

---

## Standalone Section

Tasks with `project_id: null`. Same task row format (Done button, due date chip, owner chip).

Additional affordance: ghost `→ Link project` chip on row hover. Selecting a project from the dropdown patches `project_id` on the task and moves the row into that project's group.

Add-task form at bottom:
```
[ Task title…         ] [ Due date ] [ Assign to ▾ ] [Add]
```
Submits with `project_id: null`.

---

## Data Model Changes

### Tasks — new `owner` field

- Type: nullable string (person slug, e.g. `"nicole-foley"`)
- Display: first name only (looked up from people list)
- `lib/tasks.py`:
  - `add_task` gains `owner: Optional[str] = None` param
  - `_replay` includes `owner` in the task dict (defaults to `None`)
  - `edit_task` already handles arbitrary patches — no migration needed
- Existing tasks implicitly have `owner: null`; no backfill required
- Server: `POST /api/tasks` and `PATCH /api/tasks/:id` pass through `owner` from request body

### Projects — members field restructured

- Current storage: free-text string `"nicole-foley:owner, luke-martin:contact"`
- New storage: structured array `[{"id": "nicole-foley", "role": "owner"}, ...]`
- `lib/projects.py` updated to read/write the new format
- Migration: on first Save of an existing project via the edit panel, the structured format is written. No automatic bulk migration — old records coexist until edited.

---

## New Server Endpoint

```
GET /api/people
→ [{"id": "nicole-foley", "name": "Nicole Foley"}, ...]
```

Reads `data/people_registry.json` and returns all active people as `{id, name}`. Powers both the task "Assign to" dropdown and the project member picker.

---

## Files Changed

| File | Change |
|------|--------|
| `tools/registry_ui.html` | Rename tab + view div; replace `renderProjectsView` with `renderWorkView`; add all new CSS and JS for groups, edit panel, people-picker, owner chip, link-to-project |
| `tools/server.py` | Add `GET /api/people` endpoint |
| `lib/tasks.py` | Add `owner` param to `add_task`; include `owner` in `_replay` |
| `lib/projects.py` | Update members read/write to structured array format |

---

## Out of Scope

- Archived project visibility toggle (not in this build)
- Filtering tasks by owner across the whole tab
- Due date reminders or notifications
- Retiring the Slack canvas board (it becomes redundant naturally; no explicit removal)
