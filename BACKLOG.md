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

## P3 — Cross-Day Memory

**The system resets each morning.** It knows today's calendar, today's inbox, today's issues — but accumulates nothing. The same problem surfacing every Monday for three weeks is treated as new each time.

**What's needed:**
- A persistent observations log that survives between runs
- A synthesis layer that converts raw observations into durable memories (with decay)
- Brief generator queries accumulated memory before composing sections

**Inspired by:** Donovan Li's three-layer memory architecture (observations → synthesized memories → retrieval with decay).

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

## Core Principle (from research)

> **Context beats prompt engineering.** The system is prompting Claude well — the gap is in what it knows.

Items 1 (people) and 3 (memory) are infrastructure that improves every brief. Everything else is features layered on top.
