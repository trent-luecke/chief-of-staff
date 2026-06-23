# Telegram → Slack Notification Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prune the dead Telegram push notifications and relocate the survivors to a Slack DM, leaving the two-way JARVIS Telegram bot untouched.

**Architecture:** Introduce a single `lib/notify.py` seam (`notify_user(text, config)`) that DMs the operator on Slack, reusing the proven `lib/slack_post` helpers. Each one-way push call site swaps `lib.telegram.send_message(...)` → `notify_user(text, config)`. Post-meeting nudges and external pre-meeting briefs are deleted outright; the orphaned `reply_collector.py` is removed; the observation-resolution ping moves to Slack as fire-and-forget, retiring its Telegram reply loop.

**Tech Stack:** Python 3.11, `slack_sdk`, `pytest`, GitHub Actions.

## Global Constraints

- `notify_user` is **non-fatal by contract** — it never raises; on missing token/user or a Slack error it logs a warning to stderr and returns `False`.
- Slack recipient resolves from `config["notifications"]["slack_user_id"]`, falling back to `config["ops_alerts"]["slack_user_id"]` (`U04ECG6KEA3`).
- Slack bot token comes from env `SLACK_BOT_TOKEN`.
- `lib/telegram.py` stays — the JARVIS bot (`ask.py`) and other untouched paths still use it. Do NOT delete it.
- Out of scope, do not touch: `ask.py` bot reply sends (except the resolution branch in Task 6), `scripts/wanderer.py`, `scripts/avoma_per_call.py`.
- Run the full suite with `python -m pytest -q` from the repo root.

---

### Task 1: `lib/notify.py` notify seam + config

**Files:**
- Create: `lib/notify.py`
- Modify: `config.json` (add `notifications` block)
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `lib.slack_post.open_dm(bot_token, user_id) -> str`, `lib.slack_post.post_message(bot_token, channel_id, text) -> str`.
- Produces: `notify_user(text: str, config: dict) -> bool` — every later task imports and calls this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notify.py`:

```python
from unittest.mock import patch
import lib.notify as notify


CONFIG = {"notifications": {"slack_user_id": "U_NOTIFY"}}


def test_notify_user_sends_to_dm(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.notify.open_dm", return_value="D123") as mock_open, \
         patch("lib.notify.post_message", return_value="1700.00") as mock_post:
        result = notify.notify_user("hello", CONFIG)
    assert result is True
    mock_open.assert_called_once_with("xoxb-test", "U_NOTIFY")
    mock_post.assert_called_once_with("xoxb-test", "D123", "hello")


def test_notify_user_falls_back_to_ops_alerts_user(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    cfg = {"ops_alerts": {"slack_user_id": "U_OPS"}}
    with patch("lib.notify.open_dm", return_value="D1") as mock_open, \
         patch("lib.notify.post_message", return_value="ts"):
        notify.notify_user("hi", cfg)
    mock_open.assert_called_once_with("xoxb-test", "U_OPS")


def test_notify_user_noops_without_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with patch("lib.notify.open_dm") as mock_open:
        result = notify.notify_user("hello", CONFIG)
    assert result is False
    mock_open.assert_not_called()


def test_notify_user_noops_without_user(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.notify.open_dm") as mock_open:
        result = notify.notify_user("hello", {})
    assert result is False
    mock_open.assert_not_called()


def test_notify_user_never_raises_on_slack_error(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.notify.open_dm", side_effect=Exception("slack down")):
        result = notify.notify_user("hello", CONFIG)
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notify.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.notify'`.

- [ ] **Step 3: Write `lib/notify.py`**

```python
"""User-facing push notifications — one-way Slack DM to the operator.

This is the delivery channel for pre-meeting preps, the weekly digest, reminders,
and observation-resolution pings (migrated off Telegram). Unlike lib/alerts (which
is gated to GitHub Actions and meant for ops failures), notify_user is the real
delivery path, so it sends whenever a Slack token is present — mirroring the old
lib.telegram.send_message behavior. Non-fatal by contract: never raises.
"""

import os
import sys

from lib.slack_post import open_dm, post_message


def _resolve_user_id(config: dict) -> str:
    notif = config.get("notifications", {})
    if notif.get("slack_user_id"):
        return notif["slack_user_id"]
    return config.get("ops_alerts", {}).get("slack_user_id", "")


def notify_user(text: str, config: dict) -> bool:
    """DM the operator a Slack notification. Returns True if a message was sent.

    Returns False (and logs a warning) if SLACK_BOT_TOKEN or the recipient user id
    is missing, or if the Slack call fails. Never raises.
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    user_id = _resolve_user_id(config)
    if not token or not user_id:
        print(
            "WARNING: notify_user skipped — SLACK_BOT_TOKEN or slack_user_id missing",
            file=sys.stderr,
        )
        return False
    try:
        channel = open_dm(token, user_id)
        post_message(token, channel, text)
        return True
    except Exception as e:
        print(f"WARNING: notify_user failed (non-fatal): {e}", file=sys.stderr)
        return False
```

- [ ] **Step 4: Add the config block**

In `config.json`, after the `ops_alerts` block (lines 24-27), add:

```json
  "notifications": {
    "slack_user_id": "U04ECG6KEA3"
  },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_notify.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add lib/notify.py tests/test_notify.py config.json
git commit -m "feat: add notify_user Slack DM seam for one-way notifications"
```

---

### Task 2: Relocate reminders to Slack

**Files:**
- Modify: `processors/reminders.py` (import + `fire_due_reminders` signature + line 121)
- Modify: `reminder_check.py` (drop Telegram tokens, pass config)
- Modify: `tests/test_reminders.py` (patch target + call signature)
- Modify: `.github/workflows/reminders.yml` (add `SLACK_BOT_TOKEN`)

**Interfaces:**
- Consumes: `lib.notify.notify_user(text, config) -> bool` (Task 1).
- Produces: `fire_due_reminders(storage, config: dict, timezone_name: str, max_age_hours: int = 24) -> None`.

- [ ] **Step 1: Update the tests first**

In `tests/test_reminders.py`, replace every `patch("processors.reminders.send_message"...)` with `patch("processors.reminders.notify_user"...)`, and every call `fire_due_reminders(storage, "tok", "chat", "America/Chicago"...)` with `fire_due_reminders(storage, {"notifications": {"slack_user_id": "U1"}}, "America/Chicago"...)`. There are call sites at lines 96-97, 110-111, 121-122, 132-133, 144-145, 155-156, 172-173, 183-184, 194-195, 207-208.

Example transformation (line 96-97):

```python
    with patch("processors.reminders.notify_user") as mock_send:
        fire_due_reminders(storage, {"notifications": {"slack_user_id": "U1"}}, "America/Chicago")
```

For the failure tests (189-195, 202-208), keep `side_effect=Exception(...)` on the `notify_user` patch.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_reminders.py -q`
Expected: FAIL — `AttributeError: <module 'processors.reminders'> does not have the attribute 'notify_user'` (and/or signature errors).

- [ ] **Step 3: Update `processors/reminders.py`**

Change the import at line 8:

```python
from lib.notify import notify_user
```

Change the `fire_due_reminders` signature (line 67-71) from `(storage, bot_token, chat_id, timezone_name, max_age_hours=24)` to:

```python
def fire_due_reminders(
    storage,
    config: dict,
    timezone_name: str,
    max_age_hours: int = 24,
) -> None:
```

Change the send at line 121 from `send_message(bot_token, chat_id, text)` to:

```python
            notify_user(text, config)
```

- [ ] **Step 4: Update `reminder_check.py`**

Replace the body of `main()` so it no longer requires Telegram tokens and passes `config`:

```python
def main() -> None:
    config = load_config()
    from lib.storage import build_storage
    storage = build_storage(config)

    timezone_name = config.get("timezone", "America/Chicago")
    max_age_hours = config.get("reminder_max_age_hours", 24)

    fire_due_reminders(storage, config, timezone_name, max_age_hours)
    print("✅ Reminder check complete.")
```

Update the module docstring line 2 to: `"""Check for due reminders and send them via Slack DM. Called by reminders.yml."""`

- [ ] **Step 5: Add `SLACK_BOT_TOKEN` to `reminders.yml`**

In `.github/workflows/reminders.yml`, in the env block for the run step, add:

```yaml
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_reminders.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add processors/reminders.py reminder_check.py tests/test_reminders.py .github/workflows/reminders.yml
git commit -m "feat: relocate reminders to Slack DM"
```

---

### Task 3: Relocate weekly synthesis digest + trends to Slack

**Files:**
- Modify: `weekly_synthesis.py` (import + lines 160-191)
- Modify: `.github/workflows/weekly.yml` (add `SLACK_BOT_TOKEN`)

**Interfaces:**
- Consumes: `lib.notify.notify_user(text, config) -> bool` (Task 1). `config` is already in scope inside `_main_inner(config, run_date, storage)`.

- [ ] **Step 1: Update the import**

In `weekly_synthesis.py`, change line 13 from `from lib.telegram import send_message` to:

```python
from lib.notify import notify_user
```

- [ ] **Step 2: Replace the retrieval-digest send (lines 160-182)**

Replace the `bot_token`/`chat_id` gating + `send_message` for the retrieval digest with a `notify_user` call. The new block:

```python
    try:
        vector_cfg = config.get("vector", {})
        digest = generate_digest(
            storage=storage,
            api_key=api_key,
            model=config["ai_model"],
            config_snapshot={
                "retrieval_mode": vector_cfg.get("retrieval_mode", "auto"),
                "top_k": vector_cfg.get("top_k", 20),
                "memory_budget_pct": vector_cfg.get("memory_budget_pct", 0.6),
                "observation_budget_pct": vector_cfg.get("observation_budget_pct", 0.4),
                "score_threshold": vector_cfg.get("score_threshold"),
            },
            run_date=run_date,
        )
        header = f"Brief Scores — week ending {run_date.isoformat()}\n\n"
        notify_user(header + digest, config)
        print("Retrieval digest sent via Slack.")
    except Exception as e:
        print(f"WARNING: retrieval digest failed: {e}", file=sys.stderr)
```

Note: the old `bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")` / `chat_id = ...` lines (160-161) and the `if bot_token and chat_id:` guard (162) are removed. If `bot_token`/`chat_id` are not used elsewhere in the function, delete those two assignments.

- [ ] **Step 3: Replace the trends send (lines 184-191)**

```python
    trends_text = _format_trends_telegram(anomaly_report, demo_report)
    if trends_text:
        try:
            header = f"📈 Trends & Demo Health — week ending {run_date.isoformat()}\n\n"
            notify_user(header + trends_text, config)
            print("Trends & demo health sent via Slack.")
        except Exception as e:
            print(f"WARNING: trends Slack send failed: {e}", file=sys.stderr)
```

(Leave `_format_trends_telegram`'s name as-is — renaming it is out of scope and would ripple into its definition/tests.)

- [ ] **Step 4: Add `SLACK_BOT_TOKEN` to `weekly.yml`**

In `.github/workflows/weekly.yml` env block (after line 33), add:

```yaml
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
```

- [ ] **Step 5: Verify the suite still passes**

Run: `python -m pytest tests/test_weekly_synthesizer.py -q`
Expected: PASS (these tests don't exercise the Telegram/Slack send path; confirm no import errors).

- [ ] **Step 6: Commit**

```bash
git add weekly_synthesis.py .github/workflows/weekly.yml
git commit -m "feat: relocate weekly digest + trends to Slack DM"
```

---

### Task 4: Kill post-meeting nudges + delete orphaned reply_collector

**Files:**
- Modify: `nudger.py` (remove nudge block + dead helpers)
- Delete: `reply_collector.py`
- Modify: `config.json` (remove `pending_nudges_file`)
- Modify: `.github/workflows/nudge.yml` (drop unused Telegram secrets — see Task 5 for the Slack token add)

**Interfaces:**
- Produces: a slimmed `nudger.py` whose `run()` only sends pre-meeting preps (prep send itself is migrated in Task 5).

- [ ] **Step 1: Remove the post-meeting nudge block from `nudger.py`**

Delete lines 103-129 (the `# ── Post-meeting nudge ──` block through the `pending.append(entry)`). Also delete:
- `load_pending_nudges` and `save_pending_nudges` (lines 51-56) and the `_NUDGES_KEY` constant (line 48).
- `is_work_meeting` (lines 32-40), `PERSONAL_KEYWORDS` (lines 15-21), `MEETING_KEYWORDS` (lines 23-29).
- In `run()`: the `pending = load_pending_nudges(storage)` and `already_nudged = ...` lines (67-68), and the trailing `save_pending_nudges(pending, storage)` (line 131).

After this, `run()` keeps only: config/storage/token setup, `today_events` fetch, and the pre-meeting prep loop. Update the module docstring (line 2) to: `"""Pre-meeting prep runner: sends pre-meeting briefs to Slack before work meetings."""`

- [ ] **Step 2: Delete the orphaned reply collector**

```bash
git rm reply_collector.py
```

(No workflow invokes it; confirm with `grep -rn "reply_collector" .github/` returning nothing.)

- [ ] **Step 3: Remove the pending-nudges config key**

In `config.json`, delete line 34: `"pending_nudges_file": "data/pending_nudges.json",`.

- [ ] **Step 4: Trim now-unused Telegram secrets from `nudge.yml`**

In `.github/workflows/nudge.yml`, remove the `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_ID` env lines from the run step (the nudger no longer sends to Telegram). Leave `ANTHROPIC_API_KEY`, `GOOGLE_OAUTH_JSON`, and R2 keys. (The `SLACK_BOT_TOKEN` add happens in Task 5, since prep relocation lands there — or add it here if doing tasks out of order.)

- [ ] **Step 5: Verify nudger imports cleanly and suite passes**

Run: `python -c "import nudger"` then `python -m pytest -q`
Expected: import succeeds (no `NameError` from removed helpers); suite passes. No tests reference `nudger`/`pending_nudges` (verified), so nothing should break.

- [ ] **Step 6: Commit**

```bash
git add nudger.py config.json .github/workflows/nudge.yml
git commit -m "feat: kill post-meeting nudges; delete orphaned reply_collector"
```

---

### Task 5: Kill external prep + relocate surviving preps to Slack

**Files:**
- Modify: `processors/meeting_prep.py` (classify external → None; remove dead external branch/constants)
- Modify: `nudger.py` (prep send → `notify_user`; loosen guard)
- Modify: `.github/workflows/nudge.yml` (add `SLACK_BOT_TOKEN`)
- Test: `tests/test_meeting_prep.py`

**Interfaces:**
- Consumes: `lib.notify.notify_user(text, config) -> bool` (Task 1).
- Produces: `classify_meeting(event, config)` returns only `"dept_heads"`, `"recurring_internal"`, or `None` (never `"external"`).

- [ ] **Step 1: Update the classify test first**

In `tests/test_meeting_prep.py`, find the test(s) asserting `classify_meeting(...) == "external"` and change the expectation to `is None`. (Search for `"external"` / `'external'`.) If a test is titled around external classification, rename its assertion to document that external preps are disabled, e.g.:

```python
def test_classify_external_meeting_is_disabled():
    event = _make_event("Demo with Acme", attendees=["jane@acme.com"])
    assert classify_meeting(event, CONFIG) is None
```

(Use the existing test's event-construction helper; keep its inputs, only flip the expected value to `None`.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_meeting_prep.py -q`
Expected: FAIL — classify still returns `"external"`.

- [ ] **Step 3: Disable external in `classify_meeting`**

In `processors/meeting_prep.py`, replace lines 38-44 (the `has_external_keyword` / `has_external_attendee` block and `return "external"`) with:

```python
    # External-meeting preps are disabled (Trent preps those deliberately).
    return None
```

Delete the now-unused `EXTERNAL_KEYWORDS` constant (line 14).

- [ ] **Step 4: Remove the dead external branch in `build_prep_message`**

In `build_prep_message` (lines 444-459), remove the `if meeting_type == "external":` branch (lines 452-455) since `meeting_type` can no longer be `"external"`. Resulting branch:

```python
    if meeting_type == "dept_heads":
        context = build_dept_heads_context(config)
    else:
        context = build_recurring_internal_context(event, config)
```

Also remove the `"external"` entries from `_SYSTEM_PROMPTS` (line 406-) and `_EMOJI` (line 438). Then verify nothing else references the external-only helpers and delete them if fully orphaned:

```bash
grep -rn "build_external_context\|fetch_threads_needing_attention\|EXTERNAL_KEYWORDS" --include="*.py" .
```

If `build_external_context` (line 221) and its Gmail helper (`fetch_threads_needing_attention` usage at line 11 / def ~191) are referenced only within now-deleted code, remove them and the unused `from collectors.gmail import fetch_threads_needing_attention` import. If any are still referenced elsewhere, leave them and note it in the commit message.

- [ ] **Step 5: Relocate the prep send in `nudger.py`**

Add the import near the top of `nudger.py`:

```python
from lib.notify import notify_user
```

In the prep block, change the guard at line 85 from `if prep_enabled and api_key and bot_token and chat_id:` to:

```python
        if prep_enabled and api_key:
```

and change the send at line 97 from `send_message(bot_token, chat_id, message)` to:

```python
                            notify_user(message, config)
```

If `bot_token`/`chat_id` are now unused in `nudger.py` (they should be, after Task 4 removed the nudge block), delete their assignments (lines 63-64) and the `from lib.telegram import send_message` import (line 12).

- [ ] **Step 6: Add `SLACK_BOT_TOKEN` to `nudge.yml`**

In `.github/workflows/nudge.yml` env block, add:

```yaml
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_meeting_prep.py tests/test_meeting_prep_demos.py tests/test_meeting_prep_integration.py -q && python -c "import nudger"`
Expected: PASS; `nudger` imports cleanly.

- [ ] **Step 8: Commit**

```bash
git add processors/meeting_prep.py nudger.py tests/test_meeting_prep.py .github/workflows/nudge.yml
git commit -m "feat: kill external pre-meeting prep; relocate surviving preps to Slack"
```

---

### Task 6: Relocate observation-resolution ping (fire-and-forget) + retire reply loop

**Files:**
- Modify: `scripts/resolve_observations.py` (send → `notify_user`; drop state-file write + message-id logic; load config)
- Modify: `ask.py` (remove the resolution-reply branch, lines 236-245)
- Delete: `processors/people_resolution_handler.py`
- Modify: `.github/workflows/person_resolution.yml` (add `SLACK_BOT_TOKEN`)

**Interfaces:**
- Consumes: `lib.notify.notify_user(text, config) -> bool` (Task 1).

- [ ] **Step 1: Relocate the send in `scripts/resolve_observations.py`**

In `main()` (around lines 426-445), replace the Telegram block. Remove:
- `bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")` / `chat_id = ...` and the missing-token early-return (lines 426-430).
- The `from lib.telegram import send_message` import (line 433) and the `sys.path.insert` line if only added for it.
- The `message_id = send_message(...)` call and the entire `if message_id:` block that writes `UNRESOLVED_STATE_FILE` (lines 436-446).

Replace with config-loaded fire-and-forget delivery:

```python
    notification_text = _build_notification(classified)

    import json as _json
    with open("config.json") as _f:
        _config = _json.load(_f)
    notify_user(notification_text, _config)
```

Add the import at the top of the file (with the other imports, not inside `main`):

```python
from lib.notify import notify_user
```

Remove the now-unused `UNRESOLVED_STATE_FILE` constant (line 27) if it has no other references (`grep -n "UNRESOLVED_STATE_FILE" scripts/resolve_observations.py`).

- [ ] **Step 2: Remove the dead resolution-reply branch in `ask.py`**

Delete lines 236-245 (the `# If this is a reply to a people-resolution notification...` block through its `return`):

```python
    # If this is a reply to a people-resolution notification, route to handler
    if reply_to_id:
        resolution_state = storage.read_json("people_unresolved_state.json")
        if resolution_state and str(resolution_state.get("telegram_message_id")) == reply_to_id:
            from processors.people_resolution_handler import handle_resolution_reply
            ack = handle_resolution_reply(query, storage)
            if bot_token:
                send_message(bot_token, chat_id, ack)
            print(f"  People resolution reply processed.")
            return
```

(Leave the nudge-reply matcher at `ask.py:30` and all other `send_message` calls — those are the live JARVIS bot.)

- [ ] **Step 3: Delete the orphaned handler**

```bash
git rm processors/people_resolution_handler.py
```

Confirm no remaining references:

```bash
grep -rn "people_resolution_handler\|handle_resolution_reply" --include="*.py" .
```

Expected: no matches (if any tests import it, delete those tests too and note it).

- [ ] **Step 4: Add `SLACK_BOT_TOKEN` to `person_resolution.yml`**

In `.github/workflows/person_resolution.yml` env block for the run step, add:

```yaml
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
```

- [ ] **Step 5: Verify imports and suite**

Run: `python -c "import ask; import scripts.resolve_observations" && python -m pytest tests/test_resolve_notifications.py -q && python -m pytest -q`
Expected: imports succeed; `test_resolve_notifications.py` passes (it only tests `_build_notification` text); full suite passes.

- [ ] **Step 6: Commit**

```bash
git add scripts/resolve_observations.py ask.py .github/workflows/person_resolution.yml
git commit -m "feat: relocate observation-resolution ping to Slack; retire Telegram reply loop"
```

---

### Task 7: Final verification

- [ ] **Step 1: Full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 2: Confirm no stray one-way Telegram sends remain in migrated paths**

Run:
```bash
grep -rn "send_message" --include="*.py" nudger.py weekly_synthesis.py processors/reminders.py reminder_check.py scripts/resolve_observations.py
```
Expected: no matches (all migrated). `ask.py`, `scripts/wanderer.py`, `scripts/avoma_per_call.py`, and `lib/telegram.py` still legitimately contain `send_message` — that's expected.

- [ ] **Step 3: Confirm deletions**

Run:
```bash
test ! -f reply_collector.py && test ! -f processors/people_resolution_handler.py && echo "deletions OK"
```
Expected: `deletions OK`.

- [ ] **Step 4: Sanity-check the workflows got the Slack token**

Run:
```bash
for f in nudge weekly reminders person_resolution; do
  printf "%-18s " "$f.yml:"; grep -q "SLACK_BOT_TOKEN" .github/workflows/$f.yml && echo "OK" || echo "MISSING"
done
```
Expected: all `OK`.

---

## Self-Review

**Spec coverage:**
- Post-meeting nudge kill → Task 4. ✓
- `reply_collector` + `pending_nudges.json` deletion → Task 4. ✓
- External prep kill → Task 5. ✓
- Dept-head/recurring-internal prep relocate → Task 5. ✓
- Weekly digest + trends relocate → Task 3. ✓
- Reminders relocate → Task 2. ✓
- Observation-resolution relocate (fire-and-forget, drop reply loop per updated decision) → Task 6. ✓
- `lib/notify.py` seam + config → Task 1. ✓
- Workflow `SLACK_BOT_TOKEN` adds (nudge, weekly, reminders, person_resolution) → Tasks 2, 3, 5, 6; verified Task 7. ✓
- JARVIS bot untouched → enforced via Global Constraints + Task 6 scoping. ✓

**Placeholder scan:** No TBD/TODO; all code steps include concrete code. Grep-and-confirm steps are deliberate verification, not deferred work.

**Type consistency:** `notify_user(text: str, config: dict) -> bool` is defined in Task 1 and called identically in Tasks 2, 3, 5, 6. `fire_due_reminders(storage, config, timezone_name, max_age_hours=24)` is defined and tested consistently in Task 2.

**Note on the observation-resolution decision:** The spec body lists it under "relocate." During plan-writing a Telegram reply loop was discovered; the user chose "relocate, drop the reply loop." Task 6 implements that updated decision (fire-and-forget + retire `ask.py` branch + delete handler), which supersedes the spec's simpler framing.
