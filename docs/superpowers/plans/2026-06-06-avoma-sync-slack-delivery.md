# Avoma Sync: Replace Telegram with Slack DM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the nightly Avoma sync digest to a Slack DM instead of Telegram, failing the Actions job (and triggering GitHub email notification) if the send fails.

**Architecture:** Add a top-level `post_message()` to `lib/slack_post.py`, update `scripts/avoma_sync.py` to use it and remove all Telegram references, add the destination channel to `config.json`, and swap secrets in the workflow.

**Tech Stack:** `slack_sdk.WebClient`, Python 3.11, GitHub Actions, pytest + `unittest.mock`

---

## File Map

| Action | File |
|--------|------|
| Modify | `lib/slack_post.py` |
| Create | `tests/test_slack_post.py` (extend existing) |
| Modify | `scripts/avoma_sync.py` |
| Create | `tests/test_avoma_sync.py` |
| Modify | `config.json` |
| Modify | `.github/workflows/avoma_sync.yml` |

---

### Task 1: Add `post_message()` to `lib/slack_post.py`

**Files:**
- Modify: `lib/slack_post.py`
- Modify: `tests/test_slack_post.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_slack_post.py`:

```python
def test_post_message_returns_ts():
    from lib.slack_post import post_message
    with patch("lib.slack_post.WebClient", return_value=_make_post_client("ts.001")):
        result = post_message("tok", "D04EQ4BBW2H", "hello")
    assert result == "ts.001"


def test_post_message_raises_on_slack_error():
    from lib.slack_post import post_message
    client = MagicMock()
    client.chat_postMessage.side_effect = SlackApiError("fail", {"error": "not_in_channel"})
    with patch("lib.slack_post.WebClient", return_value=client):
        with pytest.raises(SlackApiError):
            post_message("tok", "D04EQ4BBW2H", "hello")


def test_post_message_calls_correct_channel():
    from lib.slack_post import post_message
    with patch("lib.slack_post.WebClient", return_value=_make_post_client()) as mock_wc:
        post_message("tok", "D04EQ4BBW2H", "test message")
    mock_wc.return_value.chat_postMessage.assert_called_once_with(
        channel="D04EQ4BBW2H", text="test message"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_slack_post.py::test_post_message_returns_ts tests/test_slack_post.py::test_post_message_raises_on_slack_error tests/test_slack_post.py::test_post_message_calls_correct_channel -v
```

Expected: FAIL with `ImportError: cannot import name 'post_message'`

- [ ] **Step 3: Add `post_message()` to `lib/slack_post.py`**

Add after the existing `post_to_thread` function:

```python
def post_message(bot_token: str, channel_id: str, text: str) -> str:
    """Post a top-level message to a Slack channel or DM. Returns message ts. Raises SlackApiError on failure."""
    client = WebClient(token=bot_token)
    resp = client.chat_postMessage(channel=channel_id, text=text)
    return resp.data["ts"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_slack_post.py::test_post_message_returns_ts tests/test_slack_post.py::test_post_message_raises_on_slack_error tests/test_slack_post.py::test_post_message_calls_correct_channel -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Run full slack_post test suite to check for regressions**

```bash
pytest tests/test_slack_post.py -v
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add lib/slack_post.py tests/test_slack_post.py
git commit -m "feat: add post_message() to lib/slack_post for top-level DM delivery"
```

---

### Task 2: Add `avoma.slack_dm_channel_id` to `config.json`

**Files:**
- Modify: `config.json`

- [ ] **Step 1: Add the field**

In `config.json`, find the `"avoma"` object and add `"slack_dm_channel_id"`:

```json
"avoma": {
  "enabled": true,
  "lookback_hours": 96,
  "filter_internal": true,
  "slack_channel_id": "C07D8MNDKK3",
  "slack_dm_channel_id": "D04EQ4BBW2H",
  "slack_trigger_lookback_hours": 168,
  "sales_rep_emails": [
    "ryan@teambuildr.com",
    "lmartin@teambuildr.com",
    "chris@teambuildr.com",
    "jeff@teambuildr.com",
    "quinn@teambuildr.com",
    "trent@teambuildr.com"
  ]
}
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python3 -c "import json; json.load(open('config.json')); print('valid')"
```

Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add config.json
git commit -m "config: add avoma.slack_dm_channel_id for nightly sync delivery"
```

---

### Task 3: Rewrite delivery in `scripts/avoma_sync.py`

**Files:**
- Modify: `scripts/avoma_sync.py`
- Create: `tests/test_avoma_sync.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_avoma_sync.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


# ── build_slack_message ───────────────────────────────────────────────────────

def test_build_slack_message_no_calls():
    from scripts.avoma_sync import build_slack_message
    result = build_slack_message([], [], "2026-06-06")
    assert result == "📞 Avoma Sync — 2026-06-06\n\nNo new OS calls in the last 24 hours."


def test_build_slack_message_pipeline_update():
    from scripts.avoma_sync import build_slack_message
    updates = [{
        "lead_name": "Acme Corp",
        "call_type": "demo",
        "call_date": "2026-06-06",
        "inferred_status": "In-Trial / Post Demo",
        "summary": "Strong interest.",
        "is_new_lead": False,
        "account_owner": None,
        "buying_signals": [],
        "objections": [],
    }]
    result = build_slack_message(updates, [], "2026-06-06")
    assert "Acme Corp" in result
    assert "In-Trial / Post Demo" in result
    assert "*Pipeline Updates*" in result


def test_build_slack_message_new_lead_shows_warning():
    from scripts.avoma_sync import build_slack_message
    updates = [{
        "lead_name": "New Gym",
        "call_type": "demo",
        "call_date": "2026-06-06",
        "inferred_status": "No Trial / Post Demo",
        "summary": "First call.",
        "is_new_lead": True,
        "account_owner": "Ryan",
        "buying_signals": [],
        "objections": [],
    }]
    result = build_slack_message(updates, [], "2026-06-06")
    assert "Not in pipeline" in result
    assert "Ryan" in result


def test_build_slack_message_onboarding_update():
    from scripts.avoma_sync import build_slack_message
    updates = [{
        "customer_name": "Iron Will",
        "call_date": "2026-06-06",
        "onboarding_completed": ["Phase 1", "App setup"],
        "onboarding_next_steps": ["Load athletes"],
        "status_update": "In progress",
        "summary": "Good session.",
    }]
    result = build_slack_message([], updates, "2026-06-06")
    assert "Iron Will" in result
    assert "*Onboarding Updates*" in result
    assert "Phase 1" in result


def test_build_slack_message_no_char_limit():
    """Slack limit is 40k — no truncation guard needed unlike Telegram."""
    from scripts.avoma_sync import build_slack_message
    long_summary = "x" * 5000
    updates = [{
        "lead_name": "Big Corp",
        "call_type": "follow_up",
        "call_date": "2026-06-06",
        "inferred_status": "On-Hold",
        "summary": long_summary,
        "is_new_lead": False,
        "account_owner": None,
        "buying_signals": [],
        "objections": [],
    }]
    result = build_slack_message(updates, [], "2026-06-06")
    assert long_summary in result  # not truncated


# ── delivery error path ───────────────────────────────────────────────────────

def test_delivery_exits_1_on_slack_error():
    """The delivery block in main() calls sys.exit(1) when post_message raises."""
    import sys
    from slack_sdk.errors import SlackApiError

    # Reproduce the delivery block in isolation
    def run_delivery(post_fn):
        try:
            post_fn("tok", "D04EQ4BBW2H", "hello")
            print("   Slack DM sent.")
        except Exception as exc:
            print(f"ERROR: Slack send failed: {exc}", file=sys.stderr)
            sys.exit(1)

    with pytest.raises(SystemExit) as exc_info:
        run_delivery(MagicMock(side_effect=SlackApiError("fail", {"error": "not_in_channel"})))
    assert exc_info.value.code == 1


def test_delivery_does_not_exit_on_success():
    """The delivery block does NOT call sys.exit when post_message succeeds."""
    import sys

    def run_delivery(post_fn):
        try:
            post_fn("tok", "D04EQ4BBW2H", "hello")
            print("   Slack DM sent.")
        except Exception as exc:
            print(f"ERROR: Slack send failed: {exc}", file=sys.stderr)
            sys.exit(1)

    # Should not raise
    run_delivery(MagicMock(return_value="ts.001"))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_avoma_sync.py -v
```

Expected: FAIL — `build_slack_message` does not exist yet

- [ ] **Step 3: Rewrite `scripts/avoma_sync.py`**

Make these changes to `scripts/avoma_sync.py`:

**a) Replace the `build_telegram_message` function with `build_slack_message`:**

Remove:
```python
def build_telegram_message(
    pipeline_updates: list[dict],
    onboarding_updates: list[dict],
    today: str,
) -> str:
    if not pipeline_updates and not onboarding_updates:
        return f"📞 Avoma Sync — {today}\n\nNo new OS calls in the last 24 hours."

    parts = [f"📞 Avoma Sync — {today}"]

    if pipeline_updates:
        parts.append("\n*Pipeline Updates*")
        for u in pipeline_updates:
            ct = u["call_type"].replace("_", " ").title()
            line = f"• {u['lead_name']} ({ct})\n  Status → {u['inferred_status']}\n  {u['summary']}"
            if u.get("is_new_lead"):
                line += f"\n  ⚠️ Not in pipeline — create new record (owner: {u['account_owner']})"
            parts.append(line)

    if onboarding_updates:
        parts.append("\n*Onboarding Updates*")
        for u in onboarding_updates:
            completed = ", ".join(u["onboarding_completed"]) if u["onboarding_completed"] else "none noted"
            line = (
                f"• {u['customer_name']}\n"
                f"  Completed: {completed}\n"
                f"  {u['summary']}"
            )
            parts.append(line)

    msg = "\n".join(parts)
    # Telegram hard limit is 4096 chars; truncate gracefully
    if len(msg) > 4000:
        msg = msg[:3990] + "\n…(truncated)"
    return msg
```

Add:
```python
def build_slack_message(
    pipeline_updates: list[dict],
    onboarding_updates: list[dict],
    today: str,
) -> str:
    if not pipeline_updates and not onboarding_updates:
        return f"📞 Avoma Sync — {today}\n\nNo new OS calls in the last 24 hours."

    parts = [f"📞 Avoma Sync — {today}"]

    if pipeline_updates:
        parts.append("\n*Pipeline Updates*")
        for u in pipeline_updates:
            ct = u["call_type"].replace("_", " ").title()
            line = f"• {u['lead_name']} ({ct})\n  Status → {u['inferred_status']}\n  {u['summary']}"
            if u.get("is_new_lead"):
                line += f"\n  ⚠️ Not in pipeline — create new record (owner: {u['account_owner']})"
            parts.append(line)

    if onboarding_updates:
        parts.append("\n*Onboarding Updates*")
        for u in onboarding_updates:
            completed = ", ".join(u["onboarding_completed"]) if u["onboarding_completed"] else "none noted"
            line = (
                f"• {u['customer_name']}\n"
                f"  Completed: {completed}\n"
                f"  {u['summary']}"
            )
            parts.append(line)

    return "\n".join(parts)
```

**b) Replace the `main()` function's env var block:**

Remove:
```python
    avoma_key = os.environ.get("AVOMA_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

    for name, val in [
        ("AVOMA_API_KEY", avoma_key),
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("TELEGRAM_BOT_TOKEN", telegram_token),
        ("TELEGRAM_ALLOWED_CHAT_ID", telegram_chat),
    ]:
        if not val:
            print(f"ERROR: {name} not set — avoma_sync cannot run.", file=sys.stderr)
            return
```

Add:
```python
    avoma_key = os.environ.get("AVOMA_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")

    for name, val in [
        ("AVOMA_API_KEY", avoma_key),
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("SLACK_BOT_TOKEN", slack_token),
    ]:
        if not val:
            print(f"ERROR: {name} not set — avoma_sync cannot run.", file=sys.stderr)
            return
```

**c) Read `slack_dm_channel_id` from config (place this after `avoma_cfg = config.get("avoma", {})`)**:

Add:
```python
    slack_channel = avoma_cfg.get("slack_dm_channel_id", "")
    if not slack_channel:
        print("ERROR: avoma.slack_dm_channel_id not set in config.json — avoma_sync cannot run.", file=sys.stderr)
        return
```

**d) Replace the imports inside `main()` and the delivery block:**

Remove:
```python
    from collectors.avoma import fetch_recent_meetings
    from lib.telegram import send_message
```

Add:
```python
    from collectors.avoma import fetch_recent_meetings
    from lib.slack_post import post_message
```

Remove the delivery block:
```python
    # Build and send Telegram message
    telegram_text = build_telegram_message(pipeline_updates, onboarding_updates, today)
    try:
        send_message(telegram_token, telegram_chat, telegram_text)
        print("   Telegram message sent.")
    except Exception as exc:
        print(f"WARNING: Telegram send failed: {exc}", file=sys.stderr)
```

Add:
```python
    # Build and send Slack DM
    slack_text = build_slack_message(pipeline_updates, onboarding_updates, today)
    try:
        post_message(slack_token, slack_channel, slack_text)
        print("   Slack DM sent.")
    except Exception as exc:
        print(f"ERROR: Slack send failed: {exc}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_avoma_sync.py -v
```

Expected: PASS (all tests)

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest tests/ -v --ignore=tests/test_memory_retriever_integration.py --ignore=tests/test_vector_ingest_integration.py -x -q
```

Expected: no new failures

- [ ] **Step 6: Commit**

```bash
git add scripts/avoma_sync.py tests/test_avoma_sync.py
git commit -m "feat: route avoma sync digest to Slack DM; remove Telegram; exit(1) on failure"
```

---

### Task 4: Update GitHub Actions workflow

**Files:**
- Modify: `.github/workflows/avoma_sync.yml`

- [ ] **Step 1: Swap secrets in the workflow env block**

In `.github/workflows/avoma_sync.yml`, find the `env:` block under the "Run Avoma sync" step:

Remove:
```yaml
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ALLOWED_CHAT_ID: ${{ secrets.TELEGRAM_ALLOWED_CHAT_ID }}
```

Add:
```yaml
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
```

The full step should look like:

```yaml
      - name: Run Avoma sync
        env:
          AVOMA_API_KEY: ${{ secrets.AVOMA_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
        run: python scripts/avoma_sync.py
```

- [ ] **Step 2: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/avoma_sync.yml')); print('valid')"
```

Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/avoma_sync.yml
git commit -m "ci: swap Telegram secrets for SLACK_BOT_TOKEN in avoma_sync workflow"
```

---

## Verification

After all tasks complete, do a final check that no Telegram references remain in the avoma_sync flow:

```bash
grep -n "telegram\|TELEGRAM" scripts/avoma_sync.py .github/workflows/avoma_sync.yml
```

Expected: no output.

Run the full test suite one more time:

```bash
pytest tests/ -v --ignore=tests/test_memory_retriever_integration.py --ignore=tests/test_vector_ingest_integration.py -q
```

Expected: all tests pass, no new failures.
