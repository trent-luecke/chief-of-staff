# Task Horizon + Routines — Design

**Date:** 2026-07-04
**Status:** Approved design, pending implementation plan

## Problem

1. Tasks that don't need attention until a later date sit on the task list, creating clutter and anxiety. There is no way to defer a task's *visibility* (due dates change urgency, not presence).
2. Recurring situations (e.g. going out of office) require the same batch of tasks every time, recreated by hand. Some batches should be *suggested automatically* when a situation is detected (with manual confirmation); others are run ad hoc.

## Feature 1: Horizon

A `horizon` date on a task hides it from active views until that date arrives.

### Data model (`lib/tasks.py`, `data/tasks.jsonl`)

- New optional field `horizon: "YYYY-MM-DD" | null` on task `create` events, alongside `due_date`. Carried through `_replay()`; editable via the normal `edit` patch (NOT a protected field). Existing tasks default to `null` — no migration.
- **Definition:** a task is *behind horizon* when `horizon` is set and `horizon > today`. On the horizon date itself the task is fully visible.
- New helper in `lib/tasks.py`: `is_behind_horizon(task, today)` — the single shared definition used by every consumer. The API (`GET /api/tasks`) continues to return behind-horizon tasks; hiding is a **presentation concern per surface**, never a storage-level filter.

### Registry UI (`tools/registry_ui.html`, `tools/server.py`)

- **Create form:** horizon date field next to due date, reusing the existing calendar picker (`showDatePicker()`).
- **Task rows:** horizon chip (like the due-date chip) to set/change/clear inline. Behind-horizon rows show "until <date>".
- **Standalone list:** behind-horizon tasks drop into a collapsed **"Later (N)"** section at the bottom, expandable, sorted by horizon ascending (soonest-returning first).
- **Projects:** behind-horizon tasks leave the project's visible task list, replaced by an expandable **"N on horizon"** chip on the project header row.
- **Guard:** setting a horizon later than the task's due date (either direction of edit) triggers a warning requiring the user to adjust one. Never save a state where a task surfaces already overdue.

### Slack `/task` (`scripts/slack_add_task.py`)

- A `horizon:<date phrase>` token parsed with the same `dateparser` used for due dates, matching the existing `due:<date>` token convention: `/task renew SSL cert horizon:sept 1`. Works in either order with `due:`. Confirmation message echoes it ("on horizon until Sep 1"). Same due-date guard applies. The bare word "horizon" in a title (without the `:`) is left alone.

### Morning brief (`pipeline.py` / collectors)

- Any task context the brief sees excludes behind-horizon tasks.
- New **"surfaced today"** brief item: tasks whose horizon arrived since the previous day's run (window: `previous_run_date < horizon <= today`), so the system announces what it was holding.

### Telegram

- **No changes.** Telegram is read-mostly and not a capture surface; `list_tasks` keeps current behavior.

## Feature 2: Routines

A routine is a named batch of task templates instantiated on demand. Minimal steps (titles only) for now; the structure leaves room for per-step due-date offsets/owners later without migration.

### Data model (`data/routines.json`, new `lib/routines.py`)

New tracked file (add to `.gitignore` allow-list and registry storage layer, same pattern as `projects_registry.json`):

```json
{
  "routines": [
    {
      "id": "ooo-prep",
      "name": "Out of Office Prep",
      "steps": [
        {"title": "Cancel/reschedule meetings in OOO window"},
        {"title": "Set Gmail out-of-office responder"}
      ],
      "trigger": {"type": "calendar_ooo", "lead_days": 7},
      "created": "2026-07-04",
      "runs": [
        {"date": "2026-08-03", "trigger_key": "gcal:<event_id>", "source": "slack"}
      ]
    }
  ]
}
```

- `trigger` is optional; absent = ad-hoc-only routine.
- `runs` records every instantiation; `trigger_key` is null for ad-hoc runs.

### Running a routine

- `POST /api/routines/<id>/run` (and the Slack path below) appends one ordinary `create` event per step to `tasks.jsonl` — `source: "routine"`, `metadata.routine: "<id>"`, `metadata.routine_run: "<YYYY-MM-DD>"` — and appends a `runs` entry. Created tasks are regular tasks afterward: completable, editable, horizon-able individually.
- **UI grouping:** standalone tasks sharing a `metadata.routine_run` render as a labeled group ("Out of Office Prep — Jul 4").
- **Duplicate-run guard:** if the routine ran within the last 7 days, confirm before running again (still allowed).

### Managing routines (Registry UI)

- **Routines** card on the Work tab: list with Run / Edit / Delete per routine. Create/edit form: name + ordered list of step titles (add/remove/reorder). Trigger config is edited as part of the form (type + lead days), defaulting to none.
- Endpoints: `GET/POST /api/routines`, `PATCH/DELETE /api/routines/<id>`, `POST /api/routines/<id>/run`.

### Triggered routines (calendar OOO)

- **Detection:** during daily brief generation, scan Google Calendar for out-of-office windows in `[today, today + lead_days]`. Match events with `eventType == "outOfOffice"` on the primary calendar, with a title-regex fallback (e.g. `\bOOO\b|out of office`, case-insensitive) for OOO created as regular events.
- **Suggestion:** if a window is found and the routine has no run whose `trigger_key` matches that calendar event, the brief includes a suggestion block: *"OOO detected Aug 10–14 — activate 'Out of Office Prep': type `/routine ooo prep` in Slack."* Re-appears daily until activated or the window starts, then goes quiet.
- **No separate suggestion-state file:** the brief recomputes eligibility each morning from calendar + `runs`. Idempotent; survives missed runs.
- Each calendar event is its own window — back-to-back trips each get their own suggestion cycle.
- **Recurring OOO instances are skipped** (events with `recurringEventId`): a weekly recurring OOO block would otherwise re-suggest every morning forever. Trade-off: an annually-recurring trip is never suggested — create trips as one-off events. (Added 2026-07-04 from a live-data finding.)

### `/routine` Slack command

- Reuses the `/task` infrastructure: Cloudflare worker route → `repository_dispatch` → GitHub Actions workflow (`routine_run.yml`) → `scripts/slack_run_routine.py` → append events to `origin/main` → Slack confirmation message.
- `/routine` with no args: lists routines with step counts.
- `/routine <name>`: fuzzy-matches the routine name, runs it, confirms with the created task list. Ambiguous match → asks via Slack (same pattern as owner resolution in `/task`).
- When run for a currently-suggested trigger window, the run records that window's `trigger_key` (match the nearest upcoming detected window at run time) so the brief suggestion stops.

### Future enhancement (explicitly out of scope now)

- One-click activation link in the brief email (signed token → Cloudflare worker confirm page → dispatch). Deferred until the trigger system proves itself.
- Per-step relative due dates ("day before departure"), step owners, project assignment, scheduled auto-runs.

## Error handling

- Server offline / push failure: inherits existing MainStorage behavior — HTTP 503/502 + UI banner, no phantom writes.
- Trigger detection failure (calendar API error): brief generation continues without the suggestion block (non-fatal, consistent with other collectors).
- `/routine` with unknown name: Slack reply lists available routines.

## Testing

- `lib/tasks.py`: unit tests for `is_behind_horizon` (null, past, today, future) and replay preserving/patching `horizon`.
- Slack parser: `horizon <date>` suffix parsing, including "horizon" mid-title not being consumed, and combined due-date + horizon phrases.
- Routines: run endpoint appends N correct create events + runs entry; duplicate-run guard; trigger detection window math (`lead_days`, event matching, trigger_key dedup); `/routine` fuzzy match.
- Brief: "surfaced today" window logic (previous-run boundary, first-run case).
- Manual verification: launch Registry UI locally, walk both features in the browser before merge.

## Phasing

1. **Phase 1 — Horizon** (own PR): lib field + helper, UI, Slack `/task` parsing, brief exclusion + "surfaced today".
2. **Phase 2 — Routines core** (own PR): `routines.json` + `lib/routines.py`, server endpoints, UI card + run grouping.
3. **Phase 3 — Triggers + `/routine`** (own PR): OOO detection in brief, suggestion block, Slack command + worker route + workflow.
