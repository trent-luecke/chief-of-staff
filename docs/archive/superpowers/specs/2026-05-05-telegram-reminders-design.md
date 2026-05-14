# Telegram Timed Reminders — Design Spec

**Date:** 2026-05-05
**Status:** Approved, pending implementation

---

## Overview

Enable JARVIS to set timed reminders via Telegram. The user says "remind me to start cooking dinner at 3PM" or "remind me in 2 hours to email Ted" and receives a Telegram message at the designated time. Reminders support both absolute and relative times. Fire granularity is 15 minutes (GitHub Actions cron limit).

---

## Architecture

Seven components, all following existing patterns in the codebase.

### 1. `config.json` — timezone field

Add a top-level `timezone` field:

```json
"timezone": "America/Chicago"
```

Default: `"America/Chicago"`. This is the reference timezone for all user-facing time display and for JARVIS when computing fire times. Fire times are stored internally as UTC.

### 2. `data/reminders.json` — reminder queue

Stored in R2 (or LocalStorage in dev). Array of reminder objects:

```json
[
  {
    "id": "uuid4-string",
    "message": "start cooking dinner",
    "fire_at": "2026-05-05T21:00:00Z",
    "created_at": "2026-05-05T18:23:00Z",
    "fired": false
  }
]
```

- `fire_at` is always UTC ISO 8601
- `fired` is set to `true` after the message is sent
- Entries fired more than 7 days ago are pruned on each check run

### 3. `data/reminder_history.jsonl` — history log

Each fired reminder is appended here as a single JSON line before being pruned from `reminders.json`. This log is the data foundation for Phase 2 pattern detection.

```json
{"id": "...", "message": "start cooking dinner", "fire_at": "2026-05-05T21:00:00Z", "fired_at": "2026-05-05T21:00:12Z", "created_at": "..."}
```

### 4. `processors/reminders.py` — core module

**`set_reminder(storage, message: str, fire_at_iso: str) -> str`**
- Parses `fire_at_iso` as UTC datetime; raises `ValueError` with a user-facing message if unparseable
- Rejects `fire_at` in the past — returns error string to JARVIS
- Validates `fire_at.minute % 15 == 0 and fire_at.second == 0` — rejects with error string if not aligned (hard backstop; JARVIS should catch this before calling)
- Appends entry to `data/reminders.json`
- Returns confirmation string: `"Reminder set for 3:00 PM CDT: start cooking dinner."`

**`fire_due_reminders(storage, bot_token: str, chat_id: str, timezone: str) -> None`**
- Loads `data/reminders.json`
- For each entry where `fire_at ≤ now UTC` and `fired == false`:
  - Computes `delay = now - fire_at`
  - If `delay > 20 minutes`: sends message with late-fire note:
    ```
    ⏰ Reminder: start cooking dinner
    (scheduled for 3:00 PM — fired at 3:15 PM due to a delayed run)
    ```
  - Otherwise sends cleanly:
    ```
    ⏰ Reminder: start cooking dinner
    ```
  - Marks entry `fired: true`
  - Appends a copy to `data/reminder_history.jsonl`
- Removes entries where `fired == true` and `fire_at` is more than 7 days ago
- Saves updated `reminders.json`

**Telegram send failure:** if `send_message` raises, the entry is left `fired: false` and the error is logged. The next run retries. After 24 hours past `fire_at` (configurable via `config.json` as `reminder_max_age_hours`, default `24`), the entry is pruned and a warning is logged — no silent drops.

### 5. `processors/query_tools.py` — `set_reminder` tool

Added to `TOOL_SCHEMAS`:

```python
{
    "name": "set_reminder",
    "description": "Set a timed reminder that will be sent via Telegram at the specified time. fire_at must be a UTC ISO 8601 string aligned to a 15-minute boundary (:00, :15, :30, :45). Before calling this tool, verify the time lands on a boundary — if it doesn't, ask the user which of the two surrounding 15-minute marks they prefer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The reminder text to send"},
            "fire_at": {"type": "string", "description": "UTC ISO 8601 datetime, must be on a 15-minute boundary (e.g. 2026-05-05T21:00:00Z)"},
        },
        "required": ["message", "fire_at"],
    },
}
```

Added to `execute_tool` dispatch:

```python
elif name == "set_reminder":
    from processors.reminders import set_reminder
    return set_reminder(storage, input_["message"], input_["fire_at"])
```

### 6. `processors/query.py` — current time injection

`_load_local_context` appends the current time in the configured timezone:

```python
tz_name = config.get("timezone", "America/Chicago")
from zoneinfo import ZoneInfo
now_local = datetime.now(ZoneInfo(tz_name))
parts.append(f"Current time: {now_local.strftime('%A %Y-%m-%d %H:%M %Z')} ({tz_name})")
```

`zoneinfo` is stdlib (Python 3.9+) but requires the `tzdata` package on Linux (GitHub Actions runners). Add `tzdata` to `requirements.txt`.

A paragraph added to `_SYSTEM_PROMPT`:

> When a user asks to set a reminder, compute the target fire time in the configured timezone. Check if the minute falls on a 15-minute boundary (:00, :15, :30, :45). If it does, call `set_reminder` with the correct UTC `fire_at`. If it does not, do NOT call the tool — instead reply asking the user which of the two surrounding marks they prefer (e.g. "That lands at 10:20. Should I set it for 10:15 or 10:30, sir?"). Only offer boundaries that are in the future — if the lower boundary has already passed, offer only the upper one (e.g. at 8:23 "in 7 minutes" lands at 8:30 — offer only 8:30, not 8:15). The user's next reply will trigger a new run where you complete the booking.

### 7. `reminder_check.py` — check script

```python
# Load config + storage
# Call fire_due_reminders(storage, bot_token, chat_id, timezone)
# Done — no Google auth, no Claude call
```

Same shape as `nudger.py`. Short and self-contained.

### 8. `.github/workflows/reminders.yml` — cron workflow

```yaml
on:
  schedule:
    - cron: "*/15 * * * *"   # every 15 minutes, all hours, all days
  workflow_dispatch:
```

Secrets required: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. No Google OAuth needed.

---

## Error Handling Summary

| Scenario | Behavior |
|---|---|
| `fire_at` not on 15-min boundary | Tool rejects with error string; JARVIS should have caught this first |
| `fire_at` in the past | Tool rejects with error string |
| Unparseable `fire_at` | Tool catches, returns error string to JARVIS |
| Missed fire window (delayed run) | Still fires; message includes "(scheduled for X — fired at Y due to a delayed run)" if delay > 20 min |
| Duplicate run overlap | `fired: true` flag prevents re-send |
| Telegram send failure | Entry left `fired: false`, retried next run; pruned after 24h with warning log |

---

## Phase 2 — Pattern Detection (out of scope, future)

The `data/reminder_history.jsonl` log written in Phase 1 enables:

- **Pattern detection** — extend `pattern_detector.py` or the weekly synthesis to scan reminder history for recurring messages or time-of-day/day-of-week clusters (e.g. "cooking dinner" set 4 weekdays in a row at the same time)
- **Standing reminders** — new `recurring` flag on the reminder data model; the check script generates the next occurrence after firing
- **Proactive suggestions** — weekly brief or JARVIS surfaces "You've set this reminder 4 times this week — want to make it a standing reminder?" with dedup tracking to avoid repeat suggestions
- **Systemic suggestions** — Claude analyzes the reminder text and suggests calendar blocks or workflow changes that would eliminate the need for the reminder entirely
