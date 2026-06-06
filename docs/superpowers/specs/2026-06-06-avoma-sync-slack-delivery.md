# Avoma Sync: Replace Telegram Delivery with Slack DM

**Date:** 2026-06-06
**Branch:** feat/avoma-sync-slack-delivery

## Goal

Redirect the nightly Avoma sync digest from Telegram to a Slack DM. Remove Telegram entirely from this flow. Surface failures via GitHub Actions job failure (→ GitHub email notification).

## Scope

Three files change:

1. `lib/slack_post.py` — add `post_message()`
2. `scripts/avoma_sync.py` — swap delivery, remove Telegram
3. `.github/workflows/avoma_sync.yml` — swap secrets

No changes to pipeline cache logic, Avoma collectors, or the separate `avoma_slack_processor` flow.

## Design

### 1. `lib/slack_post.py`

Add a top-level message function alongside the existing `post_to_thread`:

```python
def post_message(bot_token: str, channel_id: str, text: str) -> str:
    """Post a top-level message to a Slack channel or DM. Returns message ts. Raises SlackApiError on failure."""
    client = WebClient(token=bot_token)
    resp = client.chat_postMessage(channel=channel_id, text=text)
    return resp.data["ts"]
```

Raises on failure — does not swallow errors. The caller decides whether to exit.

### 2. `scripts/avoma_sync.py`

**Config:** Add `avoma.slack_dm_channel_id: "D04EQ4BBW2H"` to `config.json`. The script reads this field (falling back to the literal if absent). This makes the destination visible in config rather than buried in code.

**Message builder:** Rename `build_telegram_message()` → `build_slack_message()`. Drop the 4000-char truncation guard (Slack's limit is 40k). Content and mrkdwn formatting remain the same — Slack renders `*bold*` and `•` bullets identically.

**Delivery block:**

```python
# was: send_message(telegram_token, telegram_chat, telegram_text)
try:
    post_message(slack_token, slack_channel, slack_text)
    print("   Slack DM sent.")
except Exception as exc:
    print(f"ERROR: Slack send failed: {exc}", file=sys.stderr)
    sys.exit(1)
```

`sys.exit(1)` makes the Actions job fail → GitHub sends email notification.

**Env vars removed:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`

**Env var added:** `SLACK_BOT_TOKEN` (already a repo secret, used by other workflows)

**Import removed:** `from lib.telegram import send_message`

**Import added:** `from lib.slack_post import post_message`

### 3. `.github/workflows/avoma_sync.yml`

Replace in the `env:` block under "Run Avoma sync":

```yaml
# Remove:
TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
TELEGRAM_ALLOWED_CHAT_ID: ${{ secrets.TELEGRAM_ALLOWED_CHAT_ID }}

# Add:
SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
```

### 4. `config.json`

Add one field under `avoma`:

```json
"avoma": {
  ...
  "slack_dm_channel_id": "D04EQ4BBW2H"
}
```

## Failure Behavior

- If `post_message()` raises (Slack API error, network failure, bad token), the error is printed to stderr and `sys.exit(1)` is called.
- GitHub Actions marks the job as failed.
- GitHub sends an email to the repo owner (standard Actions behavior for job failures).
- Pipeline cache patching is unaffected — it runs before the send and its result stands.

## What Does Not Change

- Pipeline cache patching logic (`_patch_cache_last_contacted`)
- Avoma fetch / classification logic
- Message content and structure
- `avoma_slack_processor` / Phase 1 / Phase 2 flow (entirely separate)
- `data/` commit step in the workflow

## Out of Scope

- Slack block kit formatting (can be done separately)
- Removing the Telegram bot/library from the project entirely (other flows may use it)
