# Fitness Scout — Weekly Competitor Teardown Agent

**Date:** 2026-08-06
**Scope:** New module `chief-of-staff/scout/` (modeled on `chief-of-staff/market-intel/`)
**Author:** Trent Luecke (shaped via brainstorming with Claude)

## Problem

Trent is being served a steady stream of Meta ads for emerging/upstart gym-management and online-fitness-coaching platforms (e.g. xoda.com, coachway.io, recess.tv, quickcoach.fit, supercoach.me, gymdesk.com). He enjoys studying them because the small, agile players occasionally ship a genuinely novel take on a feature — and he wants to keep a pulse on this tier (NOT the MindBody/PushPress incumbents). Today this discovery is entirely manual and ad-hoc: it lives in his personal ad feed and his own curiosity, and nothing captures or synthesizes it.

## Goal

A **fully autonomous** research agent that emails Trent every **Friday 7am CDT** with **two deep teardowns** of emerging fitness-business/gym-management/online-coaching platforms. The primary job of the email is **feature idea-mining** — surfacing novel feature takes he can bring to the TeamBuildr OS roadmap — delivered as full, balanced platform profiles with the standout wedge as the headline and each notable feature tagged for its relevance to OS.

Discovery is off Trent's plate by default; he can optionally seed platforms he stumbles across.

### Success criteria

- A reliable Friday email lands every week, even on a bad discovery week (backlog decoupling).
- The same platform is never sent twice (unless it has shipped something materially new).
- Every OS-relevance takeaway is **grounded in a confirmed OS profile**, never invented by the model.
- Trent reads it rather than deletes it — because the novelty is the headline and the OS angle is real, not padded.

## Non-Goals

- **Not** covering the incumbents (MindBody, PushPress, Zen Planner, Trainerize, TrueCoach, Glofox, Wodify, Mariana Tek, ABC Fitness, etc.) — explicitly excluded.
- **Not** competitive/sales-enablement framing or a market-radar newsletter — the job is feature idea-mining. (These were considered and de-scoped during brainstorming.)
- **Not** touching `main.py`, the daily brief, the Telegram bot, or any existing CoS pipeline. Fully isolated module.
- **Not** a real-time or on-demand tool — it is a scheduled weekly digest (with a `--dry-run` / manual-run escape hatch).
- The agent does **not** generate OS strategy. It only looks features up against the confirmed grounding profile and tags them.

## What This Reuses (not rebuilding)

- CoS email delivery plumbing (the same Gmail/SMTP sender `market-intel/` and the brief use — confirm exact module during planning).
- CoS Anthropic client wrapper + observability logging to `data/logs/run_log.jsonl` (Phase 12 pattern — confirm exact helper during planning).
- GitHub Actions cloud cron infra + commit-back-to-repo persistence pattern.
- The `seen_urls`/de-dup registry pattern from both `market-intel/` and `Gym_Scout/`.
- The self-contained module layout of `market-intel/` (own `data/`, `config/`, output dir, `.env`, tests).

## Why here, not Gym_Scout or a new repo

`Gym_Scout/` runs **locally via launchd** (`com.trent.gymscout.plist`) — it only runs when Trent's Mac is on, which is the wrong foundation for a reliable scheduled email. `market-intel/` is the correct precedent: a self-contained research module **inside** CoS running on cloud Actions infra, already producing a scheduled email digest. Housing Fitness Scout in CoS also means its output lands where Trent's idea-vetting tools live (os-feature-shaping skill, Notion pipeline, Avoma, market-intel), so the intel is queryable in future research sessions.

---

## The OS Grounding Profile (agent's core context)

This is the single most important artifact. It is stored as `scout/os_grounding.md`, hand-curated (not machine-written), and injected verbatim into the analysis prompt for every teardown. The model may ONLY assign OS-relevance tags by looking features up against this profile; when a feature does not map cleanly it must tag `❓ Your call` rather than guess.

### Strengths (crown jewel first)
1. **Programming depth** — periodized, %-based strength & conditioning; genuine sport-performance training fit. Best-in-class vs. CrossFit-native tools.
2. **One member app** — booking + scheduling + billing + workout tracking in a single member-facing app (OS + Strength combo).
3. **Transparent single price** — $200/mo published, no tiers, no feature-gating.
4. **0% payment processing cut** — Stripe-native; revenue is subscription only.
5. **Facility ops** (scheduling, check-in, membership management) — solid vs. incumbents but not leading. **OS has NO access control.**

### Gaps
1. **Reporting — the headline gap.** No at-risk/churn report (absent-member or churn-signal surfacing), no granular revenue (revenue per membership/package, net-new MRR), no per-class/service attendance economics (to decide what schedule items to add/drop), no location-separated revenue.
2. **Multi-location** support generally (reporting aggregates across the whole account, not per location).
3. **Integrations / automation** — Zapier shipped but dead on arrival (3 of 91 accounts, 6 zaps). The OS Workflow Builder pitch is the in-progress answer.
4. **Native AI** — a gap, but **actively being built/explored** (Workflow Builder's Claude layer). Competitor AI features tag as "gap — in progress," never a blind-spot alarm.
5. **Lead management + native marketing** (email/campaigns/CRM) — **deliberately out of scope**; positioned as focus + integration.
6. **SSO** — exists, but a paid add-on built for larger accounts. **Member-booked appointments** — ~10 days from launch as of 2026-08-06 (treat as shipping imminently).

### Market fit
- **ICP:** strength & conditioning facilities, sport-performance gyms, hybrid clinic-gyms. Serves — but is **not optimized for** — yoga/spa/general-wellness.
- **Loses to** "sophisticated" operators: multi-location businesses, highly structured marketing funnels needing native CRM/marketing integration, or buyers who simply want lots of bells & whistles.
- **Guardrail (from positioning memory):** OS + Strength are two subscriptions / two invoices sharing one member app. Never attack a competitor for being "two products / two invoices / an integration between them" — that's a glass house.

### Reaction taxonomy
Every notable competitor feature gets exactly one tag:

| Tag | Meaning |
|-----|---------|
| ✅ **We do this** | OS already has it — name the OS equivalent |
| 🎯 **Real gap** | OS lacks it AND it hits real ICP pain |
| 🚫 **Out of scope** | OS deliberately chose not to — note the reason |
| ➖ **Adjacent / not-optimized** | For a segment OS serves but isn't built for (e.g. yoga/spa) or doesn't serve at all (e.g. medspa SOAP notes) |
| ✨ **Genuinely novel** | Nobody in the space does this — pure inspiration |
| ❓ **Your call** | Doesn't map cleanly to the profile — flag, don't guess |

**Two hard rules baked into the prompt:**
- **Lean by default.** A missing feature is `🎯 Real gap` *only* if it hits real ICP pain (e.g. the reporting gaps). Bells-and-whistles OS deliberately skipped → `🚫 Out of scope`, not `🎯`. This keeps the email signal-dense and respects OS's deliberate focus.
- **AI is in progress.** Competitor AI features → `🎯` tagged "in progress," never framed as a blind spot.

This profile is expected to drift; it is version-controlled and hand-edited as OS ships (e.g. when member-booked appointments launches, move it from gap to strength).

---

## Category fingerprint (what "one of these platforms" looks like)

Used by the discovery layer to recognize an in-scope platform and by the analysis prompt as reference. Derived from profiling six exemplars during brainstorming:

1. **"All-in-one" consolidation** is the universal pitch (replace-your-stack framing).
2. **Anti-incumbent pricing** as the common differentiator — free tier, flat-unlimited, or inverted economics (e.g. free software funded by payment processing).
3. **AI packaged as a named SKU or the whole pitch**, not a checkbox feature.
4. **Exactly one "weird wedge"** per platform — the novelty is almost never in the core CRM but in one adjacent bet (localization, vertical depth, business model).
5. **"0% cut / keep your money"** payment positioning.
6. **All-features-included, scale-by-size-not-feature** pricing.
7. **Founder-operator origin story** as the trust signal.
8. **Two buckets:** (A) brick-and-mortar gym/studio ops, (B) online coaching. Both in scope. Occasionally straddled.

---

## Architecture

### Module layout
```
scout/
  scout.py              # orchestrator + CLI (--dry-run, --seed <url>, --discover-only, --covered)
  discovery.py          # hybrid discovery -> candidate backlog
  teardown.py           # per-platform scrape + Claude analysis (grounded)
  emailer.py            # assemble + send Friday email (wraps CoS sender)
  os_grounding.md       # hand-curated OS profile (the agent's context) — TRACKED in git
  config/
    scout_config.json   # search seeds, exclude-list, thresholds, recipient
  data/                 # machine-written state — committed back each run
    candidates.jsonl    # the backlog (one record per discovered platform)
    covered.jsonl       # platforms already sent (de-dup registry)
    briefs/             # sent-email archive (like market-intel/briefs/)
  tests/
```

### Data model — `candidates.jsonl` (the backlog)
One JSON object per line:
```json
{
  "domain": "coachway.io",
  "name": "Coachway",
  "url": "https://coachway.io/",
  "bucket": "B",
  "source": "producthunt|websearch|reddit|meta_ad_library|seed",
  "discovered_at": "2026-08-06",
  "novelty_score": 0.0,          // cheap Claude score at discovery
  "icp_relevance": 0.0,
  "covered": false,
  "covered_at": null,
  "content_hash": null,          // hash of homepage+features text at last coverage
  "seed": false                  // true if Trent hand-added -> jumps the queue
}
```

`covered.jsonl` mirrors covered records (append-only audit + fast "have we sent this?" lookup). De-dup is by `domain`.

### Discovery layer (`discovery.py`) — hybrid, backlog-feeding

Runs as part of the weekly job (and can be run standalone via `--discover-only`). Its only job is to keep `candidates.jsonl` stocked; it never blocks the email.

1. **Reliable primary sources (always run):**
   - Web search over rotating seed queries from config (e.g. "new gym management software 2025", "alternative to Trainerize", "AI personal trainer platform startup", "indie gym software built by a gym owner").
   - ProductHunt (fitness/SaaS) and Reddit/IndieHackers mentions.
   - Uses the firecrawl search/scrape tooling available in the environment (confirm the callable path — firecrawl skill/API — during planning).
2. **Best-effort booster — Meta Ad Library:**
   - Scrape the public Ad Library web UI (headless browser) for fitness-software advertisers on rotating keywords.
   - **Rationale + honest risk:** Meta's official Ad Library *API* only supports broad keyword search for political/social-issue ads — general commercial advertisers are not reliably queryable via API, so the web-UI scrape is the practical path. It is fragile (heavy React DOM, rate-limiting/blocking, ToS gray area). It is therefore a **booster, not a dependency**: wrapped in try/except with a timeout; any failure logs a warning and is skipped. The email is never blocked by Meta.
   - This is the source that catches the "vibe-coded, ad-spending, doesn't-rank-on-Google" long tail Trent actually discovers today.
3. **De-dup + filter:** drop anything already in `candidates.jsonl`/`covered.jsonl`, drop anything on the incumbent exclude-list, drop obvious non-fits.
4. **Cheap scoring:** one small Claude call per new candidate scores `novelty_score` and `icp_relevance` against the category fingerprint + grounding profile. Cheap model, structured output.
5. Append new scored candidates to the backlog.

### Seeding (manual override valve)
`python scout.py --seed <url>` adds a candidate with `seed: true` (scored like any other but flagged to jump the selection queue). This is **purely additive** — the autonomous discovery is the engine; seeding is optional. If Trent never seeds, the agent still ships two teardowns/week from its own discovery.

### Selection (each Friday)
Pick the **2 best uncovered candidates**:
- Seeded (`seed: true`, uncovered) candidates first, oldest-seeded first.
- Then by a blended rank of `novelty_score` + `icp_relevance`.
- Guarantees a full email even on a zero-discovery week, as long as the backlog isn't empty. (If the backlog ever has <2 uncovered candidates, the email sends with whatever is available and notes it — see Edge Cases.)

### Teardown / analysis (`teardown.py`) — grounded
For each selected candidate:
1. **Scrape** homepage + features/product + pricing + about pages (multi-page).
2. **Compute `content_hash`** of the key text. If the platform was covered before and the hash is unchanged, skip it and pick the next candidate (avoids re-sending an unchanged platform). If changed, cover it as an update and diff what's new.
3. **Claude analysis call** with a prompt containing: the scraped content + the full `os_grounding.md` + the reaction taxonomy + the two hard rules. Structured output = the full balanced profile:
   - One-line description
   - Bucket (A/B/both) + target segment
   - **Standout wedge** (the headline — what's novel/unusual)
   - Core feature set
   - Pricing
   - Traction claims (flagged as self-reported)
   - Maturity signal (polished-funded vs. vibe-coded solo)
   - **OS-tagged takeaways** — the notable features, each with a taxonomy tag drawn ONLY from the grounding profile
4. Log tokens/cost to `run_log.jsonl`.

### Email (`emailer.py`)
- One email, two teardowns. Standout wedge leads each; OS-tagged takeaways as a clearly delimited section per platform.
- Archive the rendered brief to `data/briefs/` (like `market-intel/briefs/`).
- Send via the CoS email sender.

### Scheduling & persistence
- New GitHub Actions workflow `.github/workflows/scout.yml`, `schedule:` cron for Friday 7am CDT (with the standard UTC offset handling the other CoS crons use), plus `workflow_dispatch:` for manual runs.
- At end of run, commit `scout/data/` (candidates, covered, briefs) back to the repo so state persists across cloud runs. Add these paths to `.gitignore`'s un-ignore allow-list as needed (machine-written state, but must persist — mirror the CoS data commit-back pattern). `scout/os_grounding.md` and `scout/config/` are normal tracked files.

### CLI
- `python scout.py` — full weekly run (discover → select → teardown → email → persist).
- `python scout.py --dry-run` — everything except send; prints the email.
- `python scout.py --discover-only` — refill backlog, no email.
- `python scout.py --seed <url>` — add a seed candidate.
- `python scout.py --covered` — list what's been sent.

---

## Edge cases

- **Backlog < 2 uncovered candidates:** send with 1 (or, if 0, send a short "no new platforms surfaced this week — discovery sources were [X]; seed one with `--seed`" note rather than nothing). Never silently skip a Friday.
- **Meta Ad Library blocked/broken:** log warning, continue on primary sources. Never fatal.
- **Scrape of a selected candidate fails:** drop it, pick the next-best candidate; log it.
- **A candidate turns out to be an incumbent/mis-tagged:** exclude-list check at selection time as a second gate.
- **Ingest/analysis errors:** non-fatal per-candidate; a single bad platform never kills the email (market-intel resilience pattern).

## Open questions for planning (not blockers)

1. Exact CoS callables to reuse for (a) email send, (b) Anthropic client + cost logging — confirm module paths in `lib/` during planning.
2. Firecrawl access path inside a headless Actions run (skill vs. direct API + key as a GitHub Secret).
3. Meta Ad Library scrape: which headless tool is available/reliable in Actions (playwright vs. firecrawl interact), and whether a login/session is required. Prototype early; if wholly unworkable in cloud, it degrades to "primary sources only" with zero design change.
4. Cron UTC offset for 7am CDT — match whatever the existing CoS workflows use (DST handling).

## Rollout

1. Scaffold module + `os_grounding.md` + config.
2. Build teardown pipeline first (highest value; testable against the six already-profiled exemplars as fixtures).
3. Build reliable primary discovery + backlog + selection.
4. Add Meta Ad Library booster (isolated, best-effort).
5. Wire email + archive.
6. Add Actions workflow + commit-back persistence.
7. Dry-run end-to-end locally, then a manual `workflow_dispatch` cloud run, before enabling the Friday cron.
