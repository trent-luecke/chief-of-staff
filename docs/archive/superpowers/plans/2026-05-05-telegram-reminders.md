# Telegram Timed Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add timed reminder support to the JARVIS Telegram bot — user says "remind me at 3PM" or "in 2 hours to email Ted" and receives a Telegram message at the designated time.

**Architecture:** A `processors/reminders.py` core module handles storing and firing reminders. A new `reminder_check.py` script runs every 15 minutes via a dedicated GitHub Actions workflow, reading `data/reminders.json` from R2 and sending due reminders via Telegram. JARVIS gains a `set_reminder` tool and receives the current time in its context so it can resolve natural-language time expressions and enforce 15-minute alignment before calling the tool.

**Tech Stack:** Python 3.11, `zoneinfo` (stdlib) + `tzdata` (PyPI) for timezone handling, GitHub Actions cron, existing `lib/storage.py` and `lib/telegram.py` abstractions, Anthropic tool-use loop.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `processors/reminders.py` | `set_reminder` + `fire_due_reminders` — all reminder logic |
| Create | `reminder_check.py` | Entry point called by Actions — loads config/storage, calls `fire_due_reminders` |
| Create | `.github/workflows/reminders.yml` | Cron every 15 min, all hours, all days |
| Create | `tests/test_reminders.py` | Unit tests for `processors/reminders.py` |
| Modify | `requirements.txt` | Add `tzdata` (needed by `zoneinfo` on Linux) |
| Modify | `config.json` | Add `"timezone": "America/Chicago"` |
| Modify | `processors/query_tools.py` | Add `set_reminder` schema + executor; fix pre-existing schema test |
| Modify | `processors/query.py` | Inject current time into context; add reminder instructions to system prompt |
| Modify | `tests/test_query_tools.py` | Add `set_reminder` tool tests; fix pre-existing coverage test |
| Modify | `tests/test_query.py` | Add test for current-time injection |

---

## Task 1: Config Baseline

**Files:**
- Modify: `requirements.txt`
- Modify: `config.json`

- [ ] **Step 1: Add `tzdata` to requirements**

Open `requirements.txt` and append:
```
tzdata>=2024.1
```

- [ ] **Step 2: Add `timezone` to config**

Open `config.json`. After the `"email"` line (near the top), add:
```json
"timezone": "America/Chicago",
```

- [ ] **Step 3: Verify tzdata installs cleanly**

```bash
.venv/bin/pip install -r requirements.txt
```
Expected: `Successfully installed tzdata-...` or `Requirement already satisfied`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt config.json
git commit -m "feat: add timezone config + tzdata dependency for reminders"
```

---

## Task 2: `processors/reminders.py` — `set_reminder`

**Files:**
- Create: `processors/reminders.py`
- Create: `tests/test_reminders.py`

- [ ] **Step 1: Write the failing tests for `set_reminder`**

Create `tests/test_reminders.py`:

```python
import json
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from lib.storage import LocalStorage
from processors.reminders import set_reminder


def _storage():
    tmp = tempfile.mkdtemp()
    return LocalStorage(tmp)


_CONFIG = {"timezone": "America/Chicago"}

# A known UTC datetime on a 15-min boundary, well in the future
_FUTURE_15 = "2099-01-01T21:00:00Z"
# Same time but NOT on a boundary
_FUTURE_OFF = "2099-01-01T21:07:00Z"
# Clearly in the past
_PAST = "2020-01-01T00:00:00Z"


def test_set_reminder_valid_stores_entry():
    s = _storage()
    result = set_reminder(s, "cook dinner", _FUTURE_15, _CONFIG)
    assert "cook dinner" in result
    assert "reminder set" in result.lower() or "9:00" in result
    reminders = s.read_json("reminders.json")
    assert len(reminders) == 1
    assert reminders[0]["message"] == "cook dinner"
    assert reminders[0]["fired"] is False
    assert reminders[0]["fire_at"] == "2099-01-01T21:00:00Z"


def test_set_reminder_rejects_non_aligned_minute():
    s = _storage()
    result = set_reminder(s, "cook dinner", _FUTURE_OFF, _CONFIG)
    assert "boundary" in result.lower() or ":07" in result
    assert s.read_json("reminders.json") is None  # nothing written


def test_set_reminder_rejects_past_time():
    s = _storage()
    result = set_reminder(s, "cook dinner", _PAST, _CONFIG)
    assert "past" in result.lower()
    assert s.read_json("reminders.json") is None


def test_set_reminder_rejects_unparseable_time():
    s = _storage()
    result = set_reminder(s, "cook dinner", "not-a-date", _CONFIG)
    assert "parse" in result.lower() or "couldn't" in result.lower()
    assert s.read_json("reminders.json") is None


def test_set_reminder_multiple_entries_appended():
    s = _storage()
    set_reminder(s, "first task", _FUTURE_15, _CONFIG)
    set_reminder(s, "second task", "2099-01-01T21:15:00Z", _CONFIG)
    reminders = s.read_json("reminders.json")
    assert len(reminders) == 2
    assert reminders[1]["message"] == "second task"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
.venv/bin/python -m pytest tests/test_reminders.py -v 2>&1 | head -20
```
Expected: `ImportError` or `ModuleNotFoundError` — `processors/reminders.py` doesn't exist yet.

- [ ] **Step 3: Implement `set_reminder` in `processors/reminders.py`**

Create `processors/reminders.py`:

```python
"""Reminder queue: set and fire timed Telegram reminders."""

import json
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


_REMINDERS_KEY = "reminders.json"
_HISTORY_KEY = "reminder_history.jsonl"


def _format_local_time(dt: datetime, tz_name: str) -> str:
    """Format a UTC datetime as a human-readable local time string."""
    try:
        local = dt.astimezone(ZoneInfo(tz_name))
        hour = int(local.strftime("%I"))
        return f"{hour}:{local.strftime('%M %p %Z')}"
    except Exception:
        return dt.strftime("%H:%MZ")


def set_reminder(storage, message: str, fire_at_iso: str, config: dict = None) -> str:
    """Validate and persist a reminder. Returns a user-facing confirmation or error string."""
    config = config or {}
    tz_name = config.get("timezone", "America/Chicago")

    # Parse fire_at
    try:
        fire_at = datetime.fromisoformat(fire_at_iso.replace("Z", "+00:00"))
        if fire_at.tzinfo is None:
            fire_at = fire_at.replace(tzinfo=timezone.utc)
        fire_at = fire_at.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return f"Couldn't parse '{fire_at_iso}' as a datetime — please try again."

    # Reject past times
    now = datetime.now(timezone.utc)
    if fire_at <= now:
        return "That time is already in the past — please set a future time."

    # Validate 15-minute alignment
    if fire_at.minute % 15 != 0 or fire_at.second != 0:
        return (
            f"Fire time must be on a 15-minute boundary (:00, :15, :30, :45). "
            f"Got :{fire_at.minute:02d} — pick :{ (fire_at.minute // 15) * 15:02d} "
            f"or :{min((fire_at.minute // 15 + 1) * 15, 59):02d}."
        )

    display_time = _format_local_time(fire_at, tz_name)

    entry = {
        "id": str(uuid.uuid4()),
        "message": message,
        "fire_at": fire_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fired": False,
    }
    reminders = storage.read_json(_REMINDERS_KEY, default=[])
    reminders.append(entry)
    storage.write_json(_REMINDERS_KEY, reminders)

    return f"Reminder set for {display_time}: {message}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_reminders.py -v 2>&1 | tail -15
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/reminders.py tests/test_reminders.py
git commit -m "feat: add reminders module with set_reminder"
```

---

## Task 3: `processors/reminders.py` — `fire_due_reminders`

**Files:**
- Modify: `processors/reminders.py` (add `fire_due_reminders`)
- Modify: `tests/test_reminders.py` (add `fire_due_reminders` tests)

- [ ] **Step 1: Write failing tests for `fire_due_reminders`**

Append to `tests/test_reminders.py`:

```python
from processors.reminders import fire_due_reminders


def _make_entry(message: str, fire_at: datetime, fired: bool = False) -> dict:
    return {
        "id": "test-id",
        "message": message,
        "fire_at": fire_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_at": "2026-05-05T18:00:00Z",
        "fired": fired,
    }


def test_fire_due_reminders_sends_due_reminder():
    s = _storage()
    fire_at = datetime(2026, 5, 5, 21, 0, 0, tzinfo=timezone.utc)  # in the past
    s.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    mock_send.assert_called_once()
    text = mock_send.call_args[0][2]
    assert "email Ted" in text
    assert "⏰" in text

    updated = s.read_json("reminders.json")
    assert updated[0]["fired"] is True


def test_fire_due_reminders_skips_future_reminder():
    s = _storage()
    fire_at = datetime(2099, 1, 1, 21, 0, 0, tzinfo=timezone.utc)
    s.write_json("reminders.json", [_make_entry("future task", fire_at)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    mock_send.assert_not_called()
    assert s.read_json("reminders.json")[0]["fired"] is False


def test_fire_due_reminders_skips_already_fired():
    s = _storage()
    fire_at = datetime(2026, 5, 5, 21, 0, 0, tzinfo=timezone.utc)
    s.write_json("reminders.json", [_make_entry("email Ted", fire_at, fired=True)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    mock_send.assert_not_called()


def test_fire_due_reminders_adds_late_note_when_delayed():
    s = _storage()
    fire_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    fire_at = fire_at.replace(second=0, microsecond=0)
    s.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    text = mock_send.call_args[0][2]
    assert "delayed run" in text


def test_fire_due_reminders_no_late_note_when_on_time():
    s = _storage()
    fire_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    fire_at = fire_at.replace(second=0, microsecond=0)
    s.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    text = mock_send.call_args[0][2]
    assert "delayed run" not in text


def test_fire_due_reminders_appends_to_history():
    s = _storage()
    fire_at = datetime(2026, 5, 5, 21, 0, 0, tzinfo=timezone.utc)
    s.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message"):
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    raw = s.read("reminder_history.jsonl")
    assert raw is not None
    entry = json.loads(raw.strip())
    assert entry["message"] == "email Ted"
    assert "fired_at" in entry


def test_fire_due_reminders_prunes_old_fired_entries():
    s = _storage()
    old_fire_at = datetime.now(timezone.utc) - timedelta(days=8)
    old_fire_at = old_fire_at.replace(second=0, microsecond=0)
    s.write_json("reminders.json", [_make_entry("old task", old_fire_at, fired=True)])

    with patch("processors.reminders.send_message"):
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    assert s.read_json("reminders.json") == []


def test_fire_due_reminders_keeps_recent_fired_entries():
    s = _storage()
    recent_fire_at = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_fire_at = recent_fire_at.replace(second=0, microsecond=0)
    s.write_json("reminders.json", [_make_entry("recent task", recent_fire_at, fired=True)])

    with patch("processors.reminders.send_message"):
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    assert len(s.read_json("reminders.json")) == 1


def test_fire_due_reminders_retries_on_send_failure():
    s = _storage()
    fire_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    fire_at = fire_at.replace(second=0, microsecond=0)
    s.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message", side_effect=Exception("network error")):
        fire_due_reminders(s, "tok", "chat", "America/Chicago")

    # Entry stays in queue (fired=False) for next retry
    updated = s.read_json("reminders.json")
    assert len(updated) == 1
    assert updated[0]["fired"] is False


def test_fire_due_reminders_drops_expired_unsent_reminder():
    s = _storage()
    # fire_at was 25 hours ago (past max_age_hours=24)
    fire_at = datetime.now(timezone.utc) - timedelta(hours=25)
    fire_at = fire_at.replace(second=0, microsecond=0)
    s.write_json("reminders.json", [_make_entry("stale task", fire_at)])

    with patch("processors.reminders.send_message", side_effect=Exception("fail")):
        fire_due_reminders(s, "tok", "chat", "America/Chicago", max_age_hours=24)

    # Expired reminder is dropped
    assert s.read_json("reminders.json") == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_reminders.py -v 2>&1 | tail -15
```
Expected: `ImportError` — `fire_due_reminders` not yet defined.

- [ ] **Step 3: Implement `fire_due_reminders`**

Append to `processors/reminders.py` (after the existing `set_reminder` function):

```python
from lib.telegram import send_message


def fire_due_reminders(
    storage,
    bot_token: str,
    chat_id: str,
    timezone_name: str = "America/Chicago",
    max_age_hours: int = 24,
) -> None:
    """Check for due reminders, send them, update state."""
    now = datetime.now(timezone.utc)
    reminders = storage.read_json(_REMINDERS_KEY, default=[])
    updated = []

    for entry in reminders:
        try:
            fire_at = datetime.fromisoformat(entry["fire_at"].replace("Z", "+00:00"))
            fire_at = fire_at.replace(tzinfo=timezone.utc) if fire_at.tzinfo is None else fire_at
        except (ValueError, KeyError):
            updated.append(entry)
            continue

        # Already fired — keep if recent, prune if > 7 days old
        if entry.get("fired"):
            if (now - fire_at).days < 7:
                updated.append(entry)
            continue

        # Not yet due
        if fire_at > now:
            updated.append(entry)
            continue

        # Due — build message text
        delay = now - fire_at
        message = entry.get("message", "")

        scheduled_str = _format_local_time(fire_at, timezone_name)
        fired_str = _format_local_time(now, timezone_name)

        if delay.total_seconds() > 20 * 60:
            text = (
                f"⏰ Reminder: {message}\n"
                f"(scheduled for {scheduled_str} — fired at {fired_str} due to a delayed run)"
            )
        else:
            text = f"⏰ Reminder: {message}"

        try:
            send_message(bot_token, chat_id, text)
            entry["fired"] = True
            fired_entry = {**entry, "fired_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
            storage.append_line(_HISTORY_KEY, json.dumps(fired_entry))
            updated.append(entry)
        except Exception as e:
            print(f"WARNING: Failed to send reminder '{message}': {e}")
            if delay.total_seconds() > max_age_hours * 3600:
                print(f"WARNING: Reminder '{message}' expired after {max_age_hours}h — dropping.")
            else:
                updated.append(entry)  # keep for retry

    storage.write_json(_REMINDERS_KEY, updated)
```

Also add the import for `send_message` at the top of the file. Replace the imports block so it reads:

```python
import json
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from lib.telegram import send_message
```

- [ ] **Step 4: Run all reminders tests**

```bash
.venv/bin/python -m pytest tests/test_reminders.py -v 2>&1 | tail -20
```
Expected: all tests pass (0 failures).

- [ ] **Step 5: Commit**

```bash
git add processors/reminders.py tests/test_reminders.py
git commit -m "feat: add fire_due_reminders with history logging and late-fire detection"
```

---

## Task 4: `reminder_check.py` Entry Point

**Files:**
- Create: `reminder_check.py`

- [ ] **Step 1: Create `reminder_check.py`**

```python
#!/usr/bin/env python3
"""Check for due reminders and send them via Telegram. Called by reminders.yml."""

import json
import os
from dotenv import load_dotenv

load_dotenv()

from processors.reminders import fire_due_reminders


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def main() -> None:
    config = load_config()
    from lib.storage import build_storage
    storage = build_storage(config)

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

    if not bot_token or not chat_id:
        print("WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_CHAT_ID not set — skipping.")
        return

    timezone_name = config.get("timezone", "America/Chicago")
    max_age_hours = config.get("reminder_max_age_hours", 24)

    fire_due_reminders(storage, bot_token, chat_id, timezone_name, max_age_hours)
    print("✅ Reminder check complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the script parses correctly**

```bash
.venv/bin/python -c "import reminder_check; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add reminder_check.py
git commit -m "feat: add reminder_check.py entry point"
```

---

## Task 5: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/reminders.yml`

- [ ] **Step 1: Create `.github/workflows/reminders.yml`**

```yaml
name: Reminder Check

on:
  schedule:
    - cron: "*/15 * * * *"   # every 15 minutes, all hours, all days
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
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

      - name: Check reminders
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ALLOWED_CHAT_ID: ${{ secrets.TELEGRAM_ALLOWED_CHAT_ID }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
        run: python reminder_check.py
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/reminders.yml
git commit -m "feat: add reminders.yml cron workflow (every 15 min)"
```

---

## Task 6: `set_reminder` Tool in `query_tools.py`

**Files:**
- Modify: `processors/query_tools.py`
- Modify: `tests/test_query_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_query_tools.py`:

```python
def test_set_reminder_tool_valid_future_time():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        config["timezone"] = "America/Chicago"
        storage = LocalStorage(tmp)
        result = execute_tool(
            "set_reminder",
            {"message": "cook dinner", "fire_at": "2099-01-01T21:00:00Z"},
            config,
            storage=storage,
        )
        assert "cook dinner" in result
        # Entry persisted
        reminders = storage.read_json("reminders.json")
        assert reminders is not None and len(reminders) == 1


def test_set_reminder_tool_rejects_non_aligned_time():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "set_reminder",
            {"message": "cook dinner", "fire_at": "2099-01-01T21:07:00Z"},
            config,
            storage=storage,
        )
        assert "boundary" in result.lower() or ":07" in result
        assert storage.read_json("reminders.json") is None


def test_set_reminder_in_tool_schemas():
    from processors.query_tools import TOOL_SCHEMAS
    names = {s["name"] for s in TOOL_SCHEMAS}
    assert "set_reminder" in names
```

Also find `test_tool_schemas_cover_all_expected_tools` in `tests/test_query_tools.py` and replace its `expected` set to include `set_reminder`, `create_person_profile`, and `get_person_profile` (the two missing tools that cause the pre-existing failure):

```python
def test_tool_schemas_cover_all_expected_tools():
    names = {s["name"] for s in TOOL_SCHEMAS}
    expected = {
        "add_capture", "complete_task", "add_people_note",
        "create_person_profile", "get_person_profile",
        "update_project_next_action", "create_project", "resolve_issue",
        "update_config", "add_to_backlog", "search_gmail",
        "get_calendar_events", "get_pipeline_lead", "create_email_draft",
        "set_reminder",
    }
    assert names == expected
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_query_tools.py::test_set_reminder_tool_valid_future_time tests/test_query_tools.py::test_set_reminder_tool_rejects_non_aligned_time tests/test_query_tools.py::test_set_reminder_in_tool_schemas -v 2>&1 | tail -10
```
Expected: all 3 fail.

- [ ] **Step 3: Add `set_reminder` schema to `TOOL_SCHEMAS` in `processors/query_tools.py`**

In `processors/query_tools.py`, append to the `TOOL_SCHEMAS` list (before the closing `]`):

```python
    {
        "name": "set_reminder",
        "description": (
            "Set a timed reminder that fires via Telegram. The reminder system checks every "
            "15 minutes (:00, :15, :30, :45), so fire_at must land on a 15-minute boundary. "
            "Before calling this tool, check if the target time is on a boundary — if not, "
            "do NOT call this tool; ask the user which surrounding mark they prefer. "
            "Only offer boundaries that are in the future."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The reminder text to send to the user",
                },
                "fire_at": {
                    "type": "string",
                    "description": (
                        "UTC ISO 8601 datetime on a 15-minute boundary "
                        "(e.g. 2026-05-05T21:00:00Z)"
                    ),
                },
            },
            "required": ["message", "fire_at"],
        },
    },
```

- [ ] **Step 4: Add `set_reminder` executor to `execute_tool` in `processors/query_tools.py`**

In the `execute_tool` function, find the final `else` branch (`return f"Unknown tool: '{name}'."`) and insert before it:

```python
        elif name == "set_reminder":
            from processors.reminders import set_reminder
            return set_reminder(storage, input_["message"], input_["fire_at"], config)
```

- [ ] **Step 5: Run all query_tools tests**

```bash
.venv/bin/python -m pytest tests/test_query_tools.py -v 2>&1 | tail -15
```
Expected: all tests pass (0 failures, including the previously failing `test_tool_schemas_cover_all_expected_tools`).

- [ ] **Step 6: Commit**

```bash
git add processors/query_tools.py tests/test_query_tools.py
git commit -m "feat: add set_reminder tool to JARVIS tool loop"
```

---

## Task 7: Current Time Injection + System Prompt Update in `query.py`

**Files:**
- Modify: `processors/query.py`
- Modify: `tests/test_query.py`

- [ ] **Step 1: Write failing test for time injection**

Append to `tests/test_query.py`:

```python
def test_load_local_context_includes_current_time():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        config["timezone"] = "America/Chicago"
        storage = LocalStorage(tmp)
        context = _load_local_context(config, storage)
        assert "Current time:" in context
        assert "America/Chicago" in context
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_query.py::test_load_local_context_includes_current_time -v 2>&1 | tail -10
```
Expected: FAIL — "Current time:" not in context.

- [ ] **Step 3: Add current time injection to `_load_local_context` in `processors/query.py`**

In `_load_local_context`, find the final `return "\n\n".join(parts)` line. Insert before it:

```python
    tz_name = config.get("timezone", "America/Chicago")
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        now_local = _dt.now(ZoneInfo(tz_name))
        parts.append(
            f"Current time: {now_local.strftime('%A %Y-%m-%d %H:%M %Z')} ({tz_name})"
        )
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_query.py::test_load_local_context_includes_current_time -v 2>&1 | tail -10
```
Expected: PASS.

- [ ] **Step 5: Add reminder instructions to `_SYSTEM_PROMPT` in `processors/query.py`**

Find `_SYSTEM_PROMPT` in `processors/query.py`. It ends with `Context:\n{local_context}"""`. Insert a new paragraph before that final `Context:` block:

```python
_SYSTEM_PROMPT = """You are JARVIS, Trent's AI Chief of Staff. You handle things quietly and competently — no fuss, no performance.

Your tone is dry, precise, and occasionally wry. You use "sir" naturally but not robotically. You don't volunteer enthusiasm and you don't pad responses. If something is worth noting that wasn't asked, you note it once and move on. If the question has a better framing, you'll offer it. You're warm underneath the formality, but competence is how you show it — not warmth-signaling.

You have tools to look up live data and to write to the system's files. Use them when the query requires it. When you take a write action, confirm briefly what you did. For config changes, state explicitly what you changed and what it was before. Answer in plain text, 500 characters or fewer unless the query needs more detail.

When setting a reminder, compute the target fire time using the current time shown in Context. Check if the minute falls on a 15-minute boundary (:00, :15, :30, :45). If it does, call set_reminder with the correct UTC ISO 8601 fire_at. If it does not, do NOT call the tool — reply asking the user which of the two surrounding marks they prefer (e.g. "That lands at 10:20. Should I set it for 10:15 or 10:30, sir?"). Only offer boundaries that are in the future: if the lower mark has already passed, offer only the upper one. The user's next reply triggers a new run where you call set_reminder with the confirmed time.

Context:
{local_context}"""
```

- [ ] **Step 6: Run full test suite to verify no regressions**

```bash
.venv/bin/python -m pytest tests/test_query.py tests/test_query_tools.py tests/test_reminders.py -v 2>&1 | tail -15
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add processors/query.py tests/test_query.py
git commit -m "feat: inject current time into JARVIS context, add reminder alignment instructions"
```

---

## Final Verification

- [ ] **Run the full test suite**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -10
```
Expected: same pass/fail count as before this feature (only the pre-existing failures, if any, remain). The new `test_reminders.py` tests all pass.

- [ ] **Verify all 7 files exist**

```bash
ls processors/reminders.py reminder_check.py .github/workflows/reminders.yml tests/test_reminders.py
```
Expected: all 4 files listed without error.
