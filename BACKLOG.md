# Chief of Staff — Backlog

Prioritized by leverage on brief quality. Items 1–2 are infrastructure; the rest are features.

---

## ✅ P1 — People Intelligence (complete)

**Shipped 2026-04-18.** `data/people/` store with per-contact markdown files. Each file has a human-written section (role, relationship, notes — never touched by code) and a machine-written `## Activity` section updated on every run. Calendar events, Gmail threads, and Slack DMs are matched to contact files by email. One Claude call per run assesses touchpoint significance (persistent) vs routine (rolling 5) and auto-creates profiles for notable Slack DM contacts. People context is injected as ambient background into the brief prompt to surface missed deliverables and relationship context.

**PR:** https://github.com/trent-luecke/chief-of-staff/pull/1

---

## ✅ P2 — Lead and Trial Pipeline Data Source (complete)

**Shipped 2026-04-19.** Notion pipeline DB seeded into `data/pipeline_cache.json` via MCP. Watcher extended to classify all inbound email — pipeline lead contacts write to `data/pipeline_email_activity.json`, flare-ups route to `issues.json`. Manual sync on request: ask Claude Code to re-sync pipeline cache from Notion MCP. Cache staleness warning fires in the brief after 7 days.

**Known gap — outbound email not tracked.** The watcher only captures inbound email (`last_sender` match). Outreach you send to leads requires a separate `from:me to:{email}` Gmail query. Not built yet — add when P4 (two-way interface) is tackled, as the infrastructure overlaps.

---

## ✅ P0 — Cloud Hosting (complete)

**Shipped 2026-04-19.** System moved from macOS launchd to GitHub Actions. Runs unconditionally at 7am CDT (cron `0 12 * * *`) without the local machine. Auth migrated from `gws` CLI subprocess calls to `google-api-python-client` with OAuth2 refresh token stored as `GOOGLE_OAUTH_JSON` GitHub Secret (service account was blocked by Workspace admin access). Personal Gmail removed — not accessible without domain-wide delegation; covered by quick capture or P4. `data/` committed back to repo after each run for state persistence.

**Known gap — brief content volume.** The brief delivers too much information in its current form. Needs a content refinement pass to tighten signal-to-noise: reduce section length, increase prioritization, cut low-value fields. Tackle before or alongside P3.

**GitHub Secrets required:** `GOOGLE_OAUTH_JSON`, `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`

---

## ✅ P3 — Cross-Day Memory (complete)

**Shipped 2026-04-19.** Three-layer memory: `memory_observer` appends structured signals to `data/memory/observations.jsonl` each run; `memory_synthesizer` calls Claude after send to write/update `data/memory/*.md` files with YAML frontmatter and 90-day TTL; `memory_retriever` injects up to 1500 tokens of active memory into the brief prompt before generation. Cold-start banner shown for first 3 runs. Memory errors are non-fatal. PR #3.

**Known gaps:**
- `test_watcher.py` references stale API (`detect_flareups_from_gmail`, `is_business_hours`) — test is broken, watcher itself is fine. Delete or fix before next watcher change.

---

## P4 — Two-Way Interface

**The system is output-only.** You receive a brief; you read it. There's no way to ask a question like "what's open on the Apex account?" and get an answer.

**What's needed:**
- An inbound channel — Signal bot, SMS, or simple CLI
- Intent parsing: route natural language queries to the right collector/processor
- Response generation for ad hoc lookups

**Inspired by:** Donovan Li's Signal bot for natural language requests.

---

## P5 — Weekly Synthesis

**Daily briefs are operational. Weekly synthesis is strategic.** A Friday or Sunday evening synthesis — what closed, what carried over, what patterns emerged — is what separates a briefing tool from a chief of staff that helps you operate at a higher level.

**What's needed:**
- A `weekly_synthesis` processor that aggregates the week's briefs and signals
- Scheduled trigger: Friday EOD or Sunday evening
- Output: narrative summary focused on patterns and carry-forwards, not a list of events

---

## P6 — Dashboard (Deferred)

**Not blocking daily use.** The system generates a local HTML file but it's basic. A proper dashboard would make all outputs accessible without reading an email.

**What's needed:**
- A structured HTML/CSS template for the daily brief with clear sections
- Navigation between current brief, people profiles, and pipeline status
- Possibly: a local server for in-browser interaction (stretch)

---

## P7 — Push Drafts to Gmail (Deferred)

**Drafts are generated but only appear inline in the brief email.** They're saved to `data/drafts/` as local JSON files, gitignored, and gone after each run. You can't act on them directly.

**What's needed:**
- Call `users.drafts.create` via the Gmail API after each draft is generated (the OAuth credentials are already in place)
- Drafts appear in your Gmail drafts inbox, ready to review and send
- Small change — `save_draft()` in `processors/drafts.py` would get a second path that calls the Gmail service alongside the local file write

---

## P8 — Claude Tool Use (Deferred)

**Currently Claude has no internet access.** All data is pre-fetched by Python and passed as context. Adding tool use would let Claude decide what to fetch on demand, rather than always getting everything upfront.

**What's needed:**
- Define tools in `client.messages.create()` calls (e.g. `search_gmail`, `get_calendar_events`, `search_web`)
- Add a tool execution loop in each processor: Claude responds → Python executes the tool call → result fed back to Claude → repeat until Claude produces a final text response
- Most valuable in `processors/query.py` (Telegram queries), where Claude could fetch only what's relevant to the question rather than receiving all data blindly
- Lower value in `processors/brief.py` — pre-fetching everything upfront is already the right pattern for a daily brief

**Key constraint:** GitHub Actions runs are synchronous and single-use per Telegram message, but multi-turn tool loops work fine within a single run.

---

## Core Principle (from research)

> **Context beats prompt engineering.** The system is prompting Claude well — the gap is in what it knows.

Items 1 (people) and 3 (memory) are infrastructure that improves every brief. Everything else is features layered on top.
