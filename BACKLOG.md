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

**Known gap — outbound email not tracked.** The watcher only captures inbound email (`last_sender` match). Outreach you send to leads requires a separate `from:me to:{email}` Gmail query. Not built yet.

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

**Known gaps:**
- `reply-check.yml` runs Mon–Fri 8am–5pm CDT only — replies outside those hours are processed next business day
- Outbound email not tracked (see P2 known gap)

---

## ✅ P5 — Weekly Synthesis (complete)

**Shipped 2026-04-20.** Sunday 12pm CDT synthesis via `weekly.yml` GitHub Actions workflow. `processors/weekly_synthesizer.py` loads 7-day observations, state deltas, open issues, and captures — calls Claude for a narrative summary with patterns, carry-forwards, and a meta observation. Output emailed to trent@teambuildr.com and saved to `data/weekly/YYYY-MM-DD.md`. Trigger: `weekly.yml` cron `0 17 * * 0` + `workflow_dispatch`.

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

## P8 — Project Intelligence (Deferred)

**Captures accumulate but patterns go unnoticed.** No mechanism exists to suggest project structure from recurring themes in todos and captures, or to create new projects via Telegram.

**What's needed:**
- Natural language project creation via Telegram: "new project: X" writes a structured entry to `data/projects.md`
- Periodic pattern detection (daily brief or separate job): Claude scans captures for recurring themes and surfaces suggestions like "you have 5 todos around Apex onboarding — want me to create a project?"
- Design decision: suggestions delivered inline in the brief, or proactively via Telegram so you can respond immediately

**Depends on:** Task completion (shipped in P4).

---

## P9 — Claude Tool Use (Deferred)

**Currently Claude has no internet access.** All data is pre-fetched by Python and passed as context. Adding tool use would let Claude decide what to fetch on demand, rather than always getting everything upfront.

**What's needed:**
- Define tools in `client.messages.create()` calls (e.g. `search_gmail`, `get_calendar_events`, `search_web`)
- Add a tool execution loop in each processor: Claude responds → Python executes the tool call → result fed back to Claude → repeat until Claude produces a final text response
- Most valuable in `processors/query.py` (Telegram queries), where Claude could fetch only what's relevant to the question rather than receiving all data blindly
- Lower value in `processors/brief.py` — pre-fetching everything upfront is already the right pattern for a daily brief

**Key constraint:** GitHub Actions runs are synchronous and single-use per Telegram message, but multi-turn tool loops work fine within a single run.

---

## P10 — Outbound Email Tracking (from P2 known gap)

**Currently the watcher only tracks inbound email from pipeline leads.** If you send a follow-up to a prospect, the next brief has no record of it — the lead still shows as "no contact" until they reply.

**What's needed:**
- A second Gmail pass per watcher run: `from:me to:{email}` for each active lead in the pipeline index
- Record sent emails in `data/pipeline_email_activity.json` the same way inbound contact is recorded today
- Small addition to `watcher.py` — runs after the existing inbound scan, queries Sent mail only

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

## P13 — Graduated Memory Decay

**Currently memory uses a binary 90-day TTL.** A synthesized memory from 89 days ago carries the same weight as one from yesterday. The research documents graduated decay rates that prevent stale memories from persisting alongside fresh ones.

**What's needed:**
- Three decay tiers in the memory synthesizer: recently accessed (extend TTL on read), normal (default 90 days), abandoned (flag for earlier expiry if no reads in 60+ days)
- Pin flag already exists in the frontmatter schema — immune memories are already supported
- Mostly a change to `processors/memory_synthesizer.py`: track `last_accessed` in frontmatter, adjust `expires` on synthesis based on activity

**When to do it:** Only matters at 6+ months of memory accumulation. Not urgent today.

---

## Core Principle (from research)

> **Context beats prompt engineering.** The system is prompting Claude well — the gap is in what it knows.

**Priority order (2026-04-20 assessment):**
1. ✅ Q1 Memory budget — shipped
2. ✅ Q2 Signal-to-noise — shipped
3. P5 Weekly synthesis — separates briefing tool from strategic CoS
4. P7 Push drafts to Gmail — small change, high daily value
5. P10 Outbound email tracking — closes P2 gap, completes pipeline coverage
6. P11 Meeting transcript integration — highest capability gap
7. P12 Observability — risk mitigation, cheap to add
8. P13 Graduated memory decay — only relevant at 6+ months of data
