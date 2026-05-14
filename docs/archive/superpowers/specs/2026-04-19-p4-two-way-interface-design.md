# P4 — Two-Way Interface Design

**Date:** 2026-04-19  
**Status:** Approved, pending implementation

---

## Problem

The chief-of-staff system is output-only. You receive a brief and read it. There is no way to ask a follow-up question ("what's open on Apex?"), capture a quick action ("remind me to call Marcus"), or give feedback on the brief delivery ("cut the gym scout section").

---

## Channels

| Channel | Purpose |
|---|---|
| Telegram | Ad hoc queries and action captures |
| Email reply | Brief feedback only (action signals + delivery tuning) |

This is a deliberate split. Telegram is for querying and capturing. Email replies are for reacting to and tuning the brief.

---

## Architecture

```
Trent sends Telegram message
  ↓
Cloudflare Worker (cloudflare/telegram-bridge.js, ~20 lines)
  • validates X-Telegram-Bot-Api-Secret-Token header
  • fires GitHub Actions workflow_dispatch on ask.yml
    inputs: query (string), chat_id (string)
  ↓
.github/workflows/ask.yml
  ↓
ask.py → processors/query.py → lib/telegram.py
                             → data/captures.md (if captures)

─────────────────────────────────────────────

Trent replies to morning brief email
  ↓
.github/workflows/reply-check.yml (cron: */15 13-22 * * 1-5)
  ↓
check_replies.py → processors/feedback.py
  • action_signal  → data/captures.md
  • delivery_note  → data/brief_feedback.md
  • unclear        → email asks for clarification
  ↓
acknowledgment email back to Trent
```

---

## New Files

### `cloudflare/telegram-bridge.js`

Cloudflare Worker. Validates the Telegram webhook secret token, extracts `chat_id` and `text`, fires `workflow_dispatch` on `ask.yml` using a GitHub PAT.

### `ask.py`

Entry point for query runs. Loads config, validates `chat_id` matches `TELEGRAM_ALLOWED_CHAT_ID`, calls `processors/query.py`, sends Telegram reply via `lib/telegram.py`, writes captures to `data/captures.md`.

### `check_replies.py`

Entry point for email reply polling. Loads config, reads `data/state/brief_message_id.json` to locate today's brief thread. If the file doesn't exist (first run or brief hasn't sent yet), exits cleanly with no error. Fetches Gmail replies to that thread, calls `processors/feedback.py`, sends acknowledgment email.

### `processors/query.py`

Two-pass query handler.

**Pass 1 — intent classification:** Claude receives the query + schema of available local data. Returns:
```json
{
  "needs_live_gmail": true,
  "needs_live_calendar": false,
  "gmail_search_query": "from:apex OR to:apex after:2026/04/12",
  "calendar_date_range": null
}
```

**Pass 2 — answer generation:** Assembles context from local data (always) + live API results (if flagged by Pass 1), then makes a single Claude call.

Local data always loaded:
- `data/pipeline_cache.json`
- `data/people/*.md` (all contact files)
- `data/memory/*.md` via existing `memory_retriever` (1500-token budget)
- `data/issues.json`
- `data/captures.md` (last 72 hours)

Live data fetched only when needed:
- Gmail: calls `fetch_threads_needing_attention(query=<generated_query>)` with a custom query string — existing function already supports arbitrary Gmail search queries
- Calendar: calls `fetch_today_events(target_date=<date>)` for each date in the requested range — existing function already supports arbitrary dates

Structured output:
```json
{
  "answer": "string — sent to Telegram",
  "captures": [
    {"type": "todo|idea|note|flag", "target": "person or lead name or null", "content": "string"}
  ]
}
```

Expected latency: ~30s for local-only queries, ~45s when live APIs are needed.

### `processors/feedback.py`

Receives email reply body + today's brief subject for context. Claude classifies into one of three buckets:

- `action_signal` — "ignore that email", "elevate Apex" → written to `data/captures.md` as a `flag` type
- `delivery_note` — "executive summary too long", "cut gym scout section" → appended to `data/brief_feedback.md` with timestamp
- `unclear` → sends email asking for clarification

### `lib/telegram.py`

Thin wrapper. Single function: `send_message(bot_token, chat_id, text)`.

---

## Modified Files

### `outputs/sender.py`

- After sending the brief, store `message_id` in `data/state/brief_message_id.json`
- Add footer to brief email HTML: "Reply to this email to give feedback on this brief."

### `processors/brief.py`

Inject two new context blocks into the brief prompt:

- `data/captures.md` (last 72 hours) — recent action captures from Telegram queries
- `data/brief_feedback.md` — accumulated delivery tuning notes (capped at 800 tokens)

---

## New Data Files

### `data/captures.md`

Append-only. Format:
```
## 2026-04-19 14:32 — [todo] Call back Marcus re: contract renewal
## 2026-04-19 15:10 — [flag] Apex — elevate in tomorrow's brief
```

### `data/brief_feedback.md`

Append-only tuning notes. Format:
```
## 2026-04-19 — Cut gym scout section unless there are 3+ leads. Too much noise.
## 2026-04-20 — Executive summary should lead with the single most important thing, not a list.
```

Injected into the brief prompt going forward, capped at 800 tokens.

### `data/state/brief_message_id.json`

Thread anchor for reply detection. Written by `outputs/sender.py` after each send.
```json
{"message_id": "18f3a...", "date": "2026-04-19"}
```

---

## New GitHub Actions Workflows

### `.github/workflows/ask.yml`

Triggered by `workflow_dispatch` with inputs:
- `query` (string, required)
- `chat_id` (string, required)

Runs `python ask.py`, commits `data/` changes back to repo.

Env secrets: all existing secrets + `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`.

### `.github/workflows/reply-check.yml`

Cron: `*/15 13-22 * * 1-5` (every 15 min, Mon–Fri, 8am–5pm CDT). Change to `*/15 14-23 * * 1-5` in November for CST (UTC-6). Weekend feedback is not processed until Monday — acceptable given feedback is non-urgent delivery tuning.

Runs `python check_replies.py`, commits `data/` changes back to repo.

~750 Actions minutes/month — within free tier alongside the daily brief.

---

## Secrets

### GitHub Actions secrets (new)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`

### Cloudflare Worker secrets (new)
- `TELEGRAM_SECRET` — webhook validation token (set via `setWebhook` when registering the bot)
- `GITHUB_PAT` — personal access token with `actions:write` scope
- `GITHUB_REPO` — `trent-luecke/chief-of-staff`

---

## Security

- Cloudflare Worker rejects any request missing the correct `X-Telegram-Bot-Api-Secret-Token`
- `ask.py` silently drops messages from any `chat_id` other than `TELEGRAM_ALLOWED_CHAT_ID`
- `check_replies.py` only processes replies from `trent@teambuildr.com`
- If the query job fails, sends a Telegram message: "Something went wrong — check Actions logs."
- All errors in query/feedback processors are non-fatal to avoid breaking `data/` commits

---

## Out of Scope

- Writing back to external systems (Notion, Gmail drafts) — action captures land in `data/` only
- Telegram conversations / multi-turn context — each message is stateless
- Slack as an inbound channel
- Live Slack search in query processor (Slack data from brief run is sufficient)
