# EOD Nudge + Global Telegram Thread Tracking

**Date:** 2026-05-15
**Status:** Approved

## Overview

Two coupled features:

1. **Global Telegram thread tracking** — any multi-turn Telegram conversation maintains full context across messages, not just the first reply. Every bot response is recorded so the user can reply to it and continue the conversation with full history.

2. **EOD check-in nudge** — a scheduled Telegram message sent Mon–Thu at 4PM CT and Friday at 2PM CT, containing the user's current open task list and prompting for a back-and-forth update. Updates are routed through the existing tool loop: task completions sync to the Slack canvas, people updates write to contact files, project moves update `data/projects.md`.

---

## Architecture

### Thread Store — `data/telegram_threads.json`

Single source of truth for all in-flight Telegram conversations.

```json
{
  "threads": {
    "12345": {
      "thread_type": "eod",
      "created_at": "2026-05-15T21:00:00Z",
      "context": {
        "open_tasks_snapshot": [
          { "id": "t1", "title": "Finish TeamBuildr proposal" },
          { "id": "t2", "title": "Follow up with Acme" }
        ]
      },
      "turns": [
        {
          "user": "I finished the proposal",
          "bot": "Got it — marked done and synced the canvas. Anything else?",
          "bot_message_id": 12346
        }
      ],
      "all_message_ids": [12345, 12346]
    }
  }
}
```

**Key:** root message ID (nudge message or first bot response for general threads).

**Lookup:** on every incoming reply, scan `all_message_ids` across all threads for `reply_to_id`. First match wins.

**Expiry:** threads older than 24 hours are ignored at lookup time. Stale threads (>48h) are pruned during each lookup pass to keep the file small.

**Thread types:**
- `eod` — created by the EOD nudge script; carries `open_tasks_snapshot` in context
- `general` — created when the bot responds to any message that isn't already part of a thread; no special context object

---

### `ask.py` Changes

**New function: `_resolve_thread_reply(reply_to_id, storage) → dict | None`**

Loads `telegram_threads.json`, scans all non-expired threads for `reply_to_id` in `all_message_ids`. Returns the matching thread dict or `None`.

**New function: `_append_thread_turn(thread_root_id, user_text, bot_text, bot_message_id, storage)`**

Appends a turn to an existing thread and adds `bot_message_id` to `all_message_ids`. If `thread_root_id` is `None`, creates a new `general` thread keyed by `bot_message_id`.

**`_main_inner` flow changes:**

1. Existing meeting nudge reply check runs first (unchanged — handles meeting-specific routing to meeting memory).
2. New: `_resolve_thread_reply(reply_to_id)` runs next. If a thread is found, build an enriched query (see Routing section) and pass to `answer_query_with_tools`.
3. All existing query paths (slash commands, general queries) proceed as today.
4. After every `send_message` call, capture the returned message ID and call `_append_thread_turn` — either extending the matched thread or creating a new `general` thread.

The existing `_resolve_nudge_reply` path is not removed — it runs before thread resolution and handles the specific case of a first-reply to a meeting nudge.

---

### Routing — EOD vs General Thread Context

**EOD thread enrichment:**

```
[EOD CHECK-IN SESSION — 2026-05-15]
Open tasks at session start:
- Finish TeamBuildr proposal
- Follow up with Acme

Prior conversation:
User: I finished the proposal
You: Got it — marked done and synced the canvas. What else?

Current message: <user text>

Process this EOD update. Use tools to: complete tasks (syncs canvas automatically),
add people notes for any contacts mentioned, update project next-actions as needed.
Continue the conversation naturally. When the user indicates they're done, confirm
everything captured and wrap up.
```

**General thread enrichment:**

```
[CONTINUING CONVERSATION]
Prior exchange:
User: <turn 1 user>
You: <turn 1 bot>
[... additional turns ...]

Current message: <user text>
```

No special tool routing instructions for general threads — Claude uses normal judgment.

---

### EOD Nudge Script — `eod_nudge.py`

New top-level script. Responsibilities:

1. Load storage and config
2. Fetch open tasks via `lib/tasks.get_open_tasks(storage)`
3. Format and send the nudge message via `lib/telegram.send_message`
4. Capture the returned message ID
5. Write a new `eod` thread entry to `data/telegram_threads.json`

**Nudge message format:**

```
EOD check-in. Here's what's still open:
• Finish TeamBuildr proposal
• Follow up with Acme

What did you get done today? Any pipeline moves or people updates?
Reply to this message to start.
```

If there are no open tasks, the message reads: "EOD check-in. No open tasks on the board — what did you get done today?"

---

### EOD Workflow — `.github/workflows/eod.yml`

```yaml
name: EOD Nudge

on:
  schedule:
    # Mon–Thu 4PM CDT (UTC-5). Change to "0 22 * * 1-4" in November for CST (UTC-6).
    - cron: "0 21 * * 1-4"
    # Friday 2PM CDT (UTC-5). Change to "0 20 * * 5" in November for CST.
    - cron: "0 19 * * 5"
  workflow_dispatch:

jobs:
  eod-nudge:
    runs-on: ubuntu-latest
    permissions:
      contents: write
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
      - name: Configure git
        run: |
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git config user.name "github-actions[bot]"
      - name: Send EOD nudge
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ALLOWED_CHAT_ID: ${{ secrets.TELEGRAM_ALLOWED_CHAT_ID }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
        run: python eod_nudge.py
      - name: Commit thread state
        run: |
          git add data/telegram_threads.json 2>/dev/null || true
          git diff --staged --quiet || git commit -m "chore: eod nudge thread init [skip ci]"
          git push origin main || true
```

All required secrets already exist in the repository.

---

## Data Flow — Full EOD Session Example

1. **4:00 PM CT** — `eod.yml` fires. `eod_nudge.py` sends Telegram message (ID: 500). Creates thread `500` in `telegram_threads.json` with type `eod`, open tasks snapshot, empty turns. Commits thread file.

2. **4:05 PM** — User replies to message 500: "I finished the proposal and moved Acme to demo scheduled." Cloudflare Worker passes `reply_to_id=500` to `ask.yml`.

3. **`ask.py` runs.** Meeting nudge check: no match. Thread check: reply_to_id 500 → thread 500 found. Builds enriched query with EOD context + task snapshot. Calls `answer_query_with_tools`. Claude calls `complete_task("proposal")` (canvas synced), then calls a pipeline update tool for Acme. Bot responds (ID: 501): "Done — proposal marked complete, Acme moved to demo scheduled, canvas synced. Anything else?" Appends turn to thread 500. `all_message_ids` is now [500, 501]. Commits.

4. **4:07 PM** — User replies to message 501: "Also talked to Ryan Green about the renewal — he's ready to sign." `reply_to_id=501` → thread 500 found. Full prior turn loaded. Claude calls `add_people_note("Ryan Green", "ready to sign on renewal — 2026-05-15")`. Bot responds (ID: 502): "Got it — note added to Ryan's file. Anything else?" Turn appended.

5. **4:08 PM** — User replies: "That's it." Claude wraps up with a summary of everything captured. Thread naturally expires after 24h.

---

## Files Changed / Created

| File | Change |
|------|--------|
| `eod_nudge.py` | New — sends nudge, initializes thread |
| `.github/workflows/eod.yml` | New — cron schedule |
| `ask.py` | Add `_resolve_thread_reply`, `_append_thread_turn`; capture `send_message` return values on all paths; thread-based enriched query for EOD and general |
| `data/telegram_threads.json` | New runtime artifact (gitignored or committed — see below) |

**Note on `telegram_threads.json` persistence:** This file needs to survive between GitHub Actions runs. It should either be committed back to the repo (like `data/tasks.json`) or stored in R2 (like other runtime state). Given that threads expire in 24h and the file is small, committing it is the simpler choice and consistent with how `pending_nudges.json` is handled.

---

## What This Does Not Change

- Meeting nudge reply routing (`_resolve_nudge_reply`) — untouched
- Slack canvas sync logic — unchanged, triggered as today by `complete_task` tool calls
- All 12 existing tools — no changes
- Cloudflare Worker — no changes needed; it already passes `reply_to_message_id`
