# Prune + relocate Telegram push notifications to Slack DM

**Date:** 2026-06-22
**Status:** Approved design, pending implementation plan

## Problem

The chief-of-staff system fires several one-way push notifications to Telegram.
Two of them — post-meeting nudges and pre-meeting briefs — have become noise:

- **Post-meeting nudges** ("drop your notes") are redundant. Post-meeting capture
  now happens through the Avoma processing pipeline that posts into Slack.
- **Pre-meeting briefs for external meetings** aren't wanted; Trent preps those
  deliberately. The dept-head / recurring-internal briefs are still valuable.

Separately, Trent lives in Slack, not Telegram. The push notifications worth
keeping should move there. Slack outbound is already proven in this codebase
(`lib/slack_post.py`, `lib/alerts.py`).

The goal: **prune the dead notifications, then relocate the survivors to a Slack DM**,
so Telegram goes quiet for one-way pushes. The two-way JARVIS bot (`ask.py`) stays
on Telegram — migrating that is a separate, much larger project (Cloudflare Worker)
and is explicitly out of scope.

## Scope

| Notification | Source | Action |
|---|---|---|
| Post-meeting nudges | `nudger.py:103–129` | **Kill** |
| `reply_collector.py` + `data/pending_nudges.json` | orphaned | **Delete** (no workflow invokes it) |
| Pre-meeting brief — **external** | `processors/meeting_prep.py` | **Kill** |
| Pre-meeting brief — dept-heads / recurring-internal | `nudger.py:97` | **Relocate → Slack DM** |
| Weekly synthesis digest + trends | `weekly_synthesis.py:179,188` | **Relocate → Slack DM** |
| Reminders | `processors/reminders.py:121` | **Relocate → Slack DM** |
| Observation-resolution pings | `scripts/resolve_observations.py:436` | **Relocate → Slack DM** |
| JARVIS bot replies | `ask.py` (~20 calls) | **Untouched** (stays on Telegram) |
| Wanderer findings | `scripts/wanderer.py:458` | **Untouched** (stays on Telegram) |
| Avoma per-call push | `scripts/avoma_per_call.py:466` | **Untouched** (likely orphaned dup; not in scope) |

## Architecture: one notify seam

New module **`lib/notify.py`**:

```python
def notify_user(text: str, config: dict) -> bool:
    """One-way push to the operator's Slack DM. Returns True if delivered.

    Non-fatal by contract: never raises. Logs a warning and returns False if the
    Slack bot token or recipient user id is missing, or if the Slack call fails.
    """
```

Behavior:
- Reuses `lib/slack_post.open_dm` + `post_message`.
- Reads bot token from env `SLACK_BOT_TOKEN`.
- Reads recipient from `config["notifications"]["slack_user_id"]`, falling back to
  the existing `config["ops_alerts"]["slack_user_id"]` (`U04ECG6KEA3`).
- **Sends whenever the token is present** — it is the real delivery channel now,
  so it is NOT gated to `GITHUB_ACTIONS` (unlike `lib/alerts.send_ops_alert`, which
  is an alerting helper deliberately silenced during local runs). This mirrors the
  current unconditional behavior of `lib.telegram.send_message`.
- Non-fatal: a Slack failure logs to stderr and returns `False`, never crashing the
  brief/nudge/weekly run.

Every relocated call site swaps:

```python
send_message(bot_token, chat_id, text)   # before
notify_user(text, config)                # after
```

`lib/telegram.py` stays in place — the JARVIS bot (`ask.py`) and Wanderer still use it.

## Call-site changes

### `nudger.py`
- Delete the post-meeting nudge block (~lines 103–129).
- Delete now-unused helpers: `load_pending_nudges`, `save_pending_nudges`,
  `is_work_meeting`, and the `PERSONAL_KEYWORDS` / `MEETING_KEYWORDS` sets.
- Keep the pre-meeting prep block; swap its `send_message` (line 97) → `notify_user`,
  and change the guard from `bot_token and chat_id` to "Slack token present"
  (token in env + user id resolvable). The `api_key` guard for prep generation stays.
- Keep the filename `nudger.py` to avoid rippling into `nudge.yml`. The file becomes
  a thin "send pre-meeting preps" runner.

### `processors/meeting_prep.py` — kill external prep
- `classify_meeting()` currently returns `"external"`, `"dept_heads"`,
  `"recurring_internal"`, or `None`. Make it return `None` for the external case so
  the whole external path is never taken (no Claude call, no send).
- Trace `build_prep_message()` and remove any external-only branches that become
  dead. The classify-level guard is the real switch; downstream cleanup is tidiness.

### `weekly_synthesis.py` (lines 179, 188)
- Swap both `send_message` calls → `notify_user(text, config)`. Drop the Telegram
  token plumbing local to those sends.

### `processors/reminders.py` (line 121)
- Swap `send_message` → `notify_user(text, config)`. Drop Telegram token plumbing.

### `scripts/resolve_observations.py` (line 436)
- Swap `send_message` → `notify_user(text, config)`. Drop Telegram token plumbing.

## Workflows & config

### `config.json`
Add:
```json
"notifications": { "slack_user_id": "U04ECG6KEA3" }
```

### Workflow env
All four workflows currently **lack** `SLACK_BOT_TOKEN`. Add
`SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}` to the env block of:
- `.github/workflows/nudge.yml` (pre-meeting preps)
- `.github/workflows/weekly.yml` (weekly synthesis + trends)
- `.github/workflows/reminders.yml` (reminders)
- `.github/workflows/person_resolution.yml` (observation-resolution pings)

Trim now-unused Telegram secrets from `nudge.yml` (it no longer sends to Telegram at
all once post-meeting nudges are gone and prep moves to Slack). Other workflows may
keep their Telegram secrets if other code paths in them still need Telegram.

> **Note:** `SLACK_BOT_TOKEN` must be a configured GitHub Actions secret. It already
> backs `lib/alerts` / Avoma processing, so the secret exists; we are only widening
> which workflows receive it.

## Deletions
- `reply_collector.py` — no workflow invokes it; it checks Gmail for nudge-email
  replies, a path that no longer exists once nudges are gone.
- `data/pending_nudges.json` and the `pending_nudges_file` / `pending_nudges.json`
  references in `config.json` and `nudger.py`.

## Tests
- **New** `tests/test_notify.py`: sends on success; no-op + returns `False` when token
  or user id missing; never raises when the Slack call errors.
- **Update** `tests/test_reminders.py`: patch `processors.reminders.notify_user`
  instead of `processors.reminders.send_message`.
- **Update** `tests/test_resolve_notifications.py`: patch `notify_user`.
- **Update** `nudger` prep tests: patch `notify_user`; **delete** post-meeting-nudge
  test coverage and any `pending_nudges` assertions.
- `tests/test_telegram.py` stays unchanged (Telegram still used by the bot/Wanderer).

## Out of scope
- Migrating the two-way JARVIS bot (`ask.py` / Cloudflare Worker) off Telegram.
- Wanderer and Avoma-per-call Telegram pushes (left as-is).
- Investigating whether `scripts/avoma_per_call.py` is a dead duplicate.

## Success criteria
- No post-meeting nudge is ever sent.
- No external pre-meeting brief is ever sent.
- Dept-head / recurring-internal preps, weekly digest + trends, reminders, and
  observation-resolution pings all arrive as a Slack DM to `U04ECG6KEA3`.
- A Slack delivery failure never crashes the run that triggered it.
- The JARVIS Telegram bot continues to work unchanged.
- `reply_collector.py` and `pending_nudges.json` no longer exist.
