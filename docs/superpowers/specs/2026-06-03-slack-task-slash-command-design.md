# Slack Task Slash Command — Design Spec

**Date:** 2026-06-03
**Status:** Approved

---

## Overview

Move general task creation from Telegram to Slack via a `/task` slash command. Task management (complete, edit, link to project, due date) moves to the Registry UI. The Telegram tool-use loop is no longer the primary task entry point.

---

## User Experience

- **Add a task:** `/task Follow up with Acme` — works anywhere in Slack
- **Add with due date:** `/task Follow up with Acme due:friday`
- **Confirmation (ephemeral):** `Task added: Follow up with Acme` or `Task added: Follow up with Acme — due Friday`
- **Management:** complete, edit due dates, link to projects — all in Registry UI, which auto-pushes to git after each mutation

---

## Architecture

```
/task slash command
  → Cloudflare Worker (new /slack/task route)
    → immediate 200 + "Adding task..." acknowledgment
    → ctx.waitUntil → GitHub Actions task_add.yml
      → scripts/slack_add_task.py
        → add_task(storage, title, source="slack", due_date=...)
        → git commit + push data/tasks.jsonl
        → POST confirmation to response_url
```

Registry UI mutations (complete, edit, link):
```
tools/server.py mutating endpoint
  → write to tasks.jsonl
  → subprocess: git add data/tasks.jsonl && git commit && git push
  → return API response
```

---

## Components

### 1. Cloudflare Worker — new `/slack/task` route

**File:** `cloudflare/telegram-bridge.js`

Add a second path handler alongside the existing Telegram handler. Route on request path:
- `POST /` → existing Telegram handler (unchanged)
- `POST /slack/task` → new `handleSlackTask(request, env, ctx)`

`handleSlackTask`:
1. Reads raw request body (needed for Slack signature verification)
2. Verifies Slack signature: HMAC-SHA256 over `v0:<timestamp>:<raw_body>` using `SLACK_SIGNING_SECRET`, compared against `X-Slack-Signature` header. Reject with 401 if invalid or timestamp is >5 minutes old.
3. Parses URL-encoded body: extracts `text` (everything after `/task`) and `response_url`
4. Returns `{"response_type": "ephemeral", "text": "Adding task..."}` immediately
5. Fires `task_add.yml` workflow dispatch via `ctx.waitUntil()`, passing `title` (text before `due:` token) and `response_url` as inputs. If a `due:<value>` token is present, also passes `due_date_raw`.

New env var: `SLACK_SIGNING_SECRET`

### 2. GitHub Actions workflow — `task_add.yml`

**File:** `.github/workflows/task_add.yml`

Trigger: `workflow_dispatch` only. Inputs:
- `title` — task title string
- `response_url` — Slack response URL for posting confirmation
- `due_date_raw` — optional raw due date string (e.g. "friday", "next tuesday")

Steps:
1. Checkout repo
2. Setup Python, install deps
3. Run `scripts/slack_add_task.py`
4. `git add data/tasks.jsonl && git commit -m "chore: add task from slack [skip ci]" && git push`

### 3. Script — `scripts/slack_add_task.py`

Thin script, called by `task_add.yml`:
1. Reads `TASK_TITLE`, `RESPONSE_URL`, `DUE_DATE_RAW` from env
2. If `DUE_DATE_RAW` is set, parses to ISO date using `dateparser`. If parsing fails, proceeds without due date (silent — the task still gets created).
3. Calls `add_task(storage, title=title, source="slack", due_date=due_date)`
4. POSTs ephemeral confirmation to `response_url`:
   - No due date: `"Task added: <title>"`
   - With due date: `"Task added: <title> — due <parsed_date>"`

### 4. Registry UI — auto git push after mutations

**File:** `tools/server.py`

After each mutating endpoint (`complete_task`, `edit_task`, link-to-project), add a subprocess call:
```
git add data/tasks.jsonl && git commit -m "chore: task update from ui [skip ci]" && git push
```
Runs synchronously before the API response returns. On failure, returns HTTP 500 with the git error message — visible rather than silent.

### 5. Fix stale `ask.yml` reference

**File:** `.github/workflows/ask.yml`

The git commit step currently references `data/tasks.json` (pre-migration format). Update to `data/tasks.jsonl`.

---

## Slack App Configuration (one-time, manual)

1. api.slack.com/apps → your app → **Slash Commands** → Create New Command
2. Command: `/task`
3. Request URL: `https://chief-of-staff-bot.trent-4a1.workers.dev/slack/task`
4. Usage hint: `<title> [due:<date>]`
5. Reinstall app to workspace
6. Add `SLACK_SIGNING_SECRET` to Cloudflare Worker env vars (found under app settings → Basic Information → Signing Secret)

---

## What Is Not Changing

- **Canvas:** Not synced from the slash command. Continues to update via Telegram and Avoma interactions as today. To be retired when the Registry UI Tasks tab is built.
- **Avoma task creation:** Unchanged. `avoma_phase2.py` continues to call `add_task()` and `_sync_canvas` as before.
- **Telegram task tools:** Not removed. Still functional as a fallback. Removal is a separate decision.

---

## Edge Cases

- **Concurrent push conflict:** If an Avoma task-add and a `/task` command trigger simultaneous GitHub Actions runs that both try to push, one push will fail. The failed run will surface the error in Actions logs. Acceptable given rarity; no retry logic needed.
- **Empty `/task` command:** If `text` is empty or whitespace, the Worker returns `{"response_type": "ephemeral", "text": "Usage: /task <title> [due:<date>]"}` without dispatching.
- **Due date parse failure:** `dateparser` can't parse the value — task is created without a due date. Confirmation message omits the due date line. No error surfaced to the user.
