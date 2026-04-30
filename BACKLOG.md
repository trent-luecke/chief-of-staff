# Chief of Staff — Backlog

Prioritized by leverage on brief quality. Items 1–2 are infrastructure; the rest are features.

---

## ✅ Q1 — Memory Token Budget (complete)

**Shipped 2026-04-20.** Reduced memory retrieval budget from 1500 → 550 tokens in `config.json` and `processors/memory_retriever.py`. Research finding (Doney Li): empirically derived sweet spot is 550 tokens — below 400 loses context, above 700 shows diminishing returns. At 1500 the system was injecting stale noise above the point where more context helps.

---

## ✅ Q2 — Brief Signal-to-Noise (complete)

**Shipped 2026-04-20.** Three changes to `processors/brief.py`:
1. Removed "expansive" from the system prompt (was directly contradicting "no filler")
2. Empty sections are no longer passed to Claude — sections with no data are omitted entirely rather than sending `(none)` noise for every field
3. Removed the "Open Loop Summary" section (resolved/still-open counts) — pure metadata, not actionable
4. Active Projects capped at 7 — no value in surfacing all projects every day
5. Tomorrow Preview suppressed when no events

**Why it matters:** The research finding is "context beats prompt engineering" — meaning the data layer is what improves brief quality, not prompt tweaks. But that only holds if the context is signal, not noise. Cutting empty-section noise reduces token waste and reduces the chance Claude hedges on sections with nothing to say.

---

## ✅ P1 — People Intelligence (complete)

**Shipped 2026-04-18.** `data/people/` store with per-contact markdown files. Each file has a human-written section (role, relationship, notes — never touched by code) and a machine-written `## Activity` section updated on every run. Calendar events, Gmail threads, and Slack DMs are matched to contact files by email. One Claude call per run assesses touchpoint significance (persistent) vs routine (rolling 5) and auto-creates profiles for notable Slack DM contacts. People context is injected as ambient background into the brief prompt to surface missed deliverables and relationship context.

**PR:** https://github.com/trent-luecke/chief-of-staff/pull/1

---

## ✅ P2 — Lead and Trial Pipeline Data Source (complete)

**Shipped 2026-04-19.** Notion pipeline DB seeded into `data/pipeline_cache.json` via MCP. Watcher extended to classify all inbound email — pipeline lead contacts write to `data/pipeline_email_activity.json`, flare-ups route to `issues.json`. Manual sync on request: ask Claude Code to re-sync pipeline cache from Notion MCP. Cache staleness warning fires in the brief after 7 days.

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

## ✅ P4 — Two-Way Interface (complete)

**Shipped 2026-04-20.** Full Telegram bot interface operational. Cloudflare Worker validates webhook and dispatches to GitHub Actions (`ask.yml`). `processors/query.py` classifies intent, optionally fetches live Gmail/Calendar, and generates answers with JARVIS personality (dry, precise, occasional "sir"). Email replies to the morning brief are parsed and acted on via `reply-check.yml`. Task completion shipped: send "done with X" to remove items from `data/captures.md` or mark project next-actions complete in `data/projects.md`.

**Known gap:** `reply-check.yml` runs Mon–Fri 8am–5pm CDT only — replies outside those hours are processed next business day.

---

## ✅ P5 — Weekly Synthesis (complete)

**Shipped 2026-04-20.** Sunday 12pm CDT synthesis via `weekly.yml` GitHub Actions workflow. `processors/weekly_synthesizer.py` loads 7-day observations, state deltas, open issues, and captures — calls Claude for a narrative summary with patterns, carry-forwards, and a meta observation. Output emailed to trent@teambuildr.com and saved to `data/weekly/YYYY-MM-DD.md`. Trigger: `weekly.yml` cron `0 17 * * 0` + `workflow_dispatch`.

---

## P6 — Dashboard (Deferred)

**Not blocking daily use.** The system generates a local HTML file but it's basic. A proper dashboard would make all outputs accessible without reading an email.

**What's needed:**
- A structured HTML/CSS template for the daily brief with clear sections
- Navigation between current brief, people profiles, and pipeline status
- Possibly: a local server for in-browser interaction (stretch)

---

## ✅ P7 — Push Drafts to Gmail (absorbed by P9)

**Absorbed 2026-04-22.** The `create_email_draft` tool in P9 pushes drafts to Gmail via `users.drafts.create` on demand from Telegram. No longer needs a separate implementation path.

---

## ✅ P8 — Project Intelligence (absorbed by P9)

**Absorbed 2026-04-22.** The `create_project` tool in P9 handles natural language project creation via Telegram. Pattern detection suggestions remain a future possibility but are not blocking.

---

## ✅ P9 — Tool Use & Action Execution (complete)

**Shipped 2026-04-22.** Replaced `processors/query.py`'s intent classifier + two-pass fetch with a native Anthropic tool use loop. Claude now decides what to fetch and what to execute based on the query. 12 tools shipped across read (search_gmail, get_calendar_events, get_pipeline_lead) and write (add_capture, complete_task, create_email_draft, add_people_note, update_project_next_action, create_project, resolve_issue, update_config, add_to_backlog). Tool executors in `processors/query_tools.py`. `ask.py` simplified — no more JSON parsing or capture post-processing. Absorbs P7 (create_email_draft pushes Gmail draft) and P8 (create_project via natural language).

**Known gap:** Notion write access deferred — updating pipeline lead fields (status, last_contacted, notes) from Telegram requires a Notion API key with workspace admin access, which is not currently available.

---

## ✅ P10 — Outbound Email Tracking (complete)

**Shipped 2026-04-22.** Third Gmail pass added to `watcher.py`: queries `in:sent newer_than:{lookback_hours}h`, matches `last_recipient` against the lead index, and records with `direction="outbound"` in `pipeline_email_activity.json`. `EmailThread` now carries `last_recipient` (populated from the `To` header via `metadataHeaders`). Activity records now include a `direction` field (`"inbound"` or `"outbound"`) so the brief can distinguish who reached out last.

**Also fixed:** `watcher.py` had a latent `profile=` kwarg being passed to `fetch_threads_needing_attention()` — a remnant from the `gws` CLI era that caused a `TypeError` at the call site, silently breaking the Gmail scan on every watcher run since the API migration. All three call sites cleaned up.

---

## P11 — Meeting Transcript Integration

**The biggest capability gap.** The system knows meetings happened (calendar) but has zero signal for what came out of them — no action items, no decisions, no follow-ups.

**What's needed:**
- Choose a transcript provider: Fireflies, Granola, or Fathom all offer webhooks or email delivery of meeting summaries
- Ingest the transcript/summary into `data/memory/observations.jsonl` as a structured observation after each meeting
- The memory synthesizer already picks these up — the gap is purely the ingestion path

**Research note:** This is the gap every reference build flags as unsolved. The meeting itself is easy to detect; what came out of it requires either a transcript service or manual capture (current state via Telegram). A transcript webhook is the high-leverage path.

---

## ✅ P12 — Observability (complete)

**Shipped 2026-04-20.** Per-call Claude API usage logged to `data/logs/run_log.jsonl` as JSONL. Each entry captures timestamp, run_type, caller, model, input_tokens, output_tokens, and estimated_cost_usd. All 8 Claude call sites instrumented via `lib/llm_logger.log_usage()`. All 4 entry points flush via try/finally on exit. Weekly synthesis reads the 7-day window and prepends a cost summary line to the synthesis prompt. Langfuse skipped — local log is sufficient.

---

## ✅ P13 — Graduated Memory Decay (complete)

**Shipped 2026-04-23.** Abandonment-based TTL shortening in `memory_synthesizer.py`. Files with no new observations for 60+ days have their expiry shortened to today + 14 days. Pinned memories are immune. Also fixed a bug where synthesis was hardcoding `pinned=False` and `suppress=False` on every write. Config params: `abandon_threshold_days` (default 60), `abandon_ttl_days` (default 14). Will produce visible effects from ~mid-June onward.

---

## ✅ P14 — Vector Memory Layer — Phase 1 (complete)

**Shipped 2026-04-30.** Pinecone serverless index (`chief-of-staff`) with two namespaces: `observations` and `memories`. `processors/vector_ingest.py` embeds new observations and updated memory files after each daily run using Voyage AI (`voyage-3-lite`, 512 dims). Non-fatal — Pinecone errors don't block the brief. Backfill script in `scripts/backfill_vectors.py` populated the index with all historical data. State tracked in `data/vector_ingest_state.json`.

---

## ✅ P14 Phase 2 — Semantic Retrieval (complete)

**Shipped 2026-04-30.** `memory_retriever.py` now queries Pinecone instead of loading `.md` files by recency. Query built from today's calendar events, email subjects, active pipeline lead names, and open issue titles. Output split into `### Context` (synthesized memories, 60% of token budget) and `### Recent Signals` (raw observations, 40%). Pinned memories bypass ranking and always appear first. Expired memories filtered post-query in Python. Falls back to file-based retrieval on any Pinecone error (`retrieval_mode="auto"`). `retrieval_mode` config field controls behavior.

**Next:** Phase 3 — semantic Telegram queries (replace `_load_local_context` memory dump in `query.py` with vector retrieval using the user's query text as the embedding).

---

## 📥 Inbox

- 2026-04-22: Notion write access via API — update pipeline lead fields (status, last_contacted, notes) from Telegram. Blocked on Notion API key (requires workspace admin access).
- 2026-04-23: Idempotency guard added to `main.py` — if `brief_message_id.json` exists with today's date, skip send. Fixes duplicate morning brief caused by launchd + GitHub Actions both firing at 7am CDT.

---

## Core Principle (from research)

> **Context beats prompt engineering.** The system is prompting Claude well — the gap is in what it knows.

**Status as of 2026-04-30:** Q1, Q2, P0–P5, P7–P10, P12–P14 (Phase 1–2) all shipped. Open items:

1. P11 Meeting transcript integration — highest capability gap remaining
2. P14 Phase 3 — Semantic Telegram queries
3. P14 Phase 4 — Proactive pattern detection
4. P6 Dashboard — deferred, not blocking daily use
5. Notion write access — blocked on API key (workspace admin required)
