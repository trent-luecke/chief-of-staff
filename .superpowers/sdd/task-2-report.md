## Task 2 Report: Relocate reminders to Slack

### What was implemented

Migrated `fire_due_reminders` off Telegram onto `lib.notify.notify_user` (Slack DM). Four files changed:

1. **`processors/reminders.py`** — Replaced `from lib.telegram import send_message` with `from lib.notify import notify_user`. Changed signature from `(storage, bot_token, chat_id, timezone_name, max_age_hours)` to `(storage, config: dict, timezone_name, max_age_hours)`. Changed the send call from `send_message(bot_token, chat_id, text)` to `notify_user(text, config)`. Updated module docstring.

2. **`reminder_check.py`** — Replaced the `main()` body: removed `os` import, removed Telegram env var reads and the early-exit guard, now passes `config` directly to `fire_due_reminders`. Updated module docstring to say "via Slack DM".

3. **`tests/test_reminders.py`** — Updated all 10 `fire_due_reminders` call sites: patch target changed from `processors.reminders.send_message` to `processors.reminders.notify_user`; call args changed from `(storage, "tok", "chat", "America/Chicago")` to `(storage, {"notifications": {"slack_user_id": "U1"}}, "America/Chicago")`; text assertions updated from `call_args[0][2]` (3rd positional) to `call_args[0][0]` (1st positional, since `notify_user(text, config)` puts text first).

4. **`.github/workflows/reminders.yml`** — Removed `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_ID` from the env block; added `SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}`.

### TDD Evidence

**RED (before implementation):**
```
python3 -m pytest tests/test_reminders.py -q
10 failed, 7 passed in 0.49s
AttributeError: <module 'processors.reminders'> does not have the attribute 'notify_user'
```

**GREEN (after implementation):**
```
python3 -m pytest tests/test_reminders.py -q
17 passed in 0.06s
```

**Full suite:**
```
python3 -m pytest -q
780 passed, 3 skipped, 21 warnings in 5.03s
```

### Files Changed

- `/Users/trentluecke/dev/Claude-Projects/chief-of-staff/processors/reminders.py`
- `/Users/trentluecke/dev/Claude-Projects/chief-of-staff/reminder_check.py`
- `/Users/trentluecke/dev/Claude-Projects/chief-of-staff/tests/test_reminders.py`
- `/Users/trentluecke/dev/Claude-Projects/chief-of-staff/.github/workflows/reminders.yml`

### Self-Review Findings

- `lib/telegram.py` was not touched — only the import in `reminders.py` changed. Other consumers of `lib.telegram` (e.g., `ask.py`, `nudger.py`) are unaffected.
- `notify_user` is non-fatal by contract: it logs a warning and returns `False` on failure. The `except Exception` block in `fire_due_reminders` still handles the retry/expiry logic. However, because `notify_user` never raises, the `except` branch is now effectively unreachable in normal operation — `notify_user` swallows failures internally rather than propagating them. This means a Slack delivery failure will silently mark the reminder as fired (because `notify_user` returns `False` but doesn't raise, so `entry["fired"] = True` is always set and the reminder won't retry). This is a pre-existing design tension introduced by `notify_user`'s non-fatal contract from Task 1.
- The `os` import in `reminder_check.py` was cleaned up since it's no longer needed.

### Concerns

One concern: `notify_user` is non-fatal (never raises), but the retry logic in `fire_due_reminders` depends on an exception being raised to detect failure. With the current code, a failed Slack send will still mark the reminder as fired and it won't retry. Options: (a) check `notify_user`'s return value and raise if `False`, (b) accept that Slack failures silently discard reminders (matches original Telegram behavior in production), or (c) redesign the retry logic. Not blocking for this task — tests pass and behavior is consistent.

---

## Follow-up Fix: Bool-driven send branch (2026-06-22)

### What was changed

The concern above was addressed. The `try/except` send block in `fire_due_reminders` was unreachable because `notify_user` is contractually non-raising. A failed Slack delivery would mark the reminder fired and lose it.

**`processors/reminders.py`** — Replaced the `try: notify_user(...) ... except Exception:` structure with a bool-driven branch:

```python
sent = notify_user(text, config)
if sent:
    entry["fired"] = True
    entry["fired_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    storage.append_line(_HISTORY_KEY, json.dumps(entry))
    updated.append(entry)
else:
    # Delivery failed — keep for retry on the next run unless it's too old.
    print(f"WARNING: reminder delivery failed for '{message}' — will retry.")
    if delay.total_seconds() > max_age_hours * 3600:
        print(f"WARNING: Reminder '{message}' expired after {max_age_hours}h — dropping.")
    else:
        entry["fired"] = False
        updated.append(entry)
```

**`tests/test_reminders.py`** — Two failure tests updated to inject failure via `return_value=False` instead of `side_effect=Exception(...)`:

- `test_fire_due_reminders_retries_on_send_failure`
- `test_fire_due_reminders_drops_expired_unsent_reminder`

Both tests continue to assert the same retry/expiry outcomes — only the failure-injection mechanism changed.

### Test Run

```
python3 -m pytest tests/test_reminders.py -q
17 passed in 0.06s
```

Full suite:

```
python3 -m pytest -q
780 passed, 3 skipped, 21 warnings in 5.86s
```
