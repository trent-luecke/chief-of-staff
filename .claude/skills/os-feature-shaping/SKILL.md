---
name: os-feature-shaping
description: >
  Turns Claude into a product/GTM thinking partner for TeamBuildr OS decisions. Modeled on Ramp's internal
  product shaping skill, adapted to read chief-of-staff's real data layer (pipeline cache, Avoma transcripts,
  market-intel scraper, Notion). Use this skill when Trent says "help me think through [feature/initiative]",
  "should we build X", "I want to spec out Y", "help me make the case for Z", or pastes a rough idea and wants
  to pressure-test it before pitching to Teofe, Luke, or the broader team. Works in three phases: frame the
  problem (push back on weak reasoning), research (parallel agents scan Avoma transcripts, Notion pipeline,
  and competitor signals), shape the spec (produce a tight 2-minute-read decision document).
---

# OS Feature Shaping

This skill turns Claude into a rigorous thinking partner for TeamBuildr OS product and GTM decisions. It runs in three phases. Don't rush to Phase 3 — the value is in the friction from Phases 1 and 2.

> **Adapted for chief-of-staff.** Phase 2 below points at the actual data sources in this repo and the connected MCP servers. Do not search for sources by guesswork — use the concrete paths and tools named in each source block.

---

## Phase 1 — Frame the problem

Before any research or spec writing, push back on the idea with the seven questions below. Ask them one at a time in conversation — don't dump them all at once.

**The seven questions:**

1. **What's the job to be done?** What specific situation is the gym owner or admin in when they need this? What are they trying to get done, and what are they doing today instead?

2. **Who exactly is this for?** CrossFit box owner? PT studio? Sports performance facility? The ICP matters — a feature right for a 200-member CrossFit gym may be wrong for a 30-client PT studio. TeamBuildr's core strength is strength & conditioning / sports performance; be honest about whether the idea pulls toward an ICP we actually win in.

3. **Why now?** What's changed — in the market, in our pipeline data, in customer behavior, in competitive pressure — that makes this the right time to build or prioritize this?

4. **What's the evidence?** Which Avoma calls surfaced this? How many reps mentioned it independently? Is this one loud prospect or a pattern across the pipeline?

5. **What does success look like in 90 days?** Not vague outcomes — specific signals. Conversion rate, churn reduction, trial starts, deal velocity, feature adoption rate.

6. **What's the cost of not doing this?** Are deals being lost? Are customers churning over this? Is a competitor closing the gap? What's the actual downside of waiting?

7. **If we build this, what does it unlock?** Does it open a new ICP segment? Does it remove the top objection from demos? Does it change the OS/Strength product split story?

**Pushback rules:**
- If the answer to any question is vague, push back once with a clarifying question before moving on.
- If "why now" has no clear answer, flag it explicitly: *"This might be a good idea but it's not clear why it's a now idea. That will come up when you pitch this."*
- If success metrics are unmeasurable, say so and help sharpen them.
- Don't move to Phase 2 until you can summarize the problem in two sentences that would make sense to someone who doesn't work at TeamBuildr.

---

## Phase 2 — Research

Once the framing is solid, run the four source scans below **in parallel** — dispatch a separate subagent per source in a single message (`Explore` for file/repo reads, `general-purpose` when a source needs MCP calls). Don't wait for one to finish before starting the next.

Each source block names exactly where its data lives in this repo. Use those paths — do not improvise a search.

**Source 1 — Avoma call data**
The live transcript ingest runs in a *separate* repo: `trent-luecke/Avoma-Ingest-Chris` (green nightly). Per-call Claude analysis (features requested / gaps / objections / signals, from Phase P11) is the richest signal for this skill.
- Query analyzed meeting notes through the **Notion MCP** (`notion-query-meeting-notes`, then `notion-search` / `notion-fetch` for specifics).
- Sales reps to attribute mentions to are in `config.json` → `avoma.sales_rep_emails` (ryan, lmartin, chris, jeff, quinn, trent @teambuildr.com).
- Look for: how many *unique* prospects raised this unprompted; the exact language customers used (their words, not our product vocabulary); which rep heard it most and whether it clusters in a gym type or deal size; whether it landed as a deal-blocker or a nice-to-have.
- Caution: any Avoma workflow you find in the `os-metric-sync` or this monorepo is an orphaned dead copy — ignore it, the real source is `Avoma-Ingest-Chris`.

**Source 2 — Notion pipeline tracker**
Local cache: `data/pipeline_cache.json` — a dict with `fetched_at` and `leads[]`; each lead has `name, contact, email, status, priority, last_contacted, estimated_value, source, stale`.
- **Check freshness first.** If `fetched_at` is more than `pipeline.cache_stale_warn_days` (7) days old, say so and offer to re-sync via the `sync-pipeline-cache` skill before trusting it.
- Late-stage statuses are defined in `config.json` → `pipeline.late_stage_statuses` (`"In-Trial / Post Demo"`, `"No Trial / Post Demo"`).
- Scan for: deals On-Hold / Closed Lost associated with this gap; late-stage deals where the feature was mentioned and would accelerate close; account-owner patterns (is one rep disproportionately affected?).
- For anything not in the cache, query the live tracker through the **Notion MCP** (`notion-search` / `notion-query-data-sources`).

**Source 3 — Competitor signals**
The market-intel scraper lives in this repo at `market-intel/`.
- Authoritative competitor list: `market-intel/config/competitors.json` (PushPress, Mindbody, and others — use this list, not a generic one). Scraped writeups: `market-intel/data/competitors/*.md`; trends in `market-intel/data/trends/`, feature signals in `market-intel/data/features/`, and the running log `market-intel/data/intel-log.csv`.
- Read those first. Only reach for live web search (Firecrawl / WebSearch) to fill a specific gap the scraped data doesn't cover — e.g. a recent changelog entry or a Reddit/Facebook/G2/Capterra thread on the pain.
- Look for: whether any competitor markets this as a differentiator; recent product announcements in the feature area; how gym owners describe the pain in their own words.

**Source 4 — TeamBuildr OS internal knowledge**
- Search internal docs via the **Notion MCP** (`notion-search`) for prior scoping or rejection of this idea and the reason.
- Check repo-local human-curated context: `data/projects.md` (active projects) and `data/memory/decisions.md` (durable decisions — may already record a call on this).
- Determine whether partial functionality already exists that could be *extended* vs. built from scratch, and surface any technical constraint Teofe or the dev team has previously flagged.

**Research output format:**
Each source produces a short markdown summary (3–5 bullets max). After all four are done, synthesize into a single "Evidence Brief" — a paragraph that either strengthens or weakens the case, with the most compelling data point called out explicitly. If a source came back thin or stale (e.g. pipeline cache out of date, no Avoma matches), say so plainly rather than padding.

---

## Phase 3 — Shape the spec

Using the framing from Phase 1 and the evidence from Phase 2, produce a decision document. This is not a PRD — it's a 2-minute read that gives Teofe, Luke, or the leadership team everything they need to make a call.

**Document structure:**

---

### [Feature/Initiative Name]
*[One-sentence description of what this is]*

**The situation**
[2–3 sentences: what's happening in the market or pipeline that created this need. Use customer language from Avoma where possible.]

**The ask**
[1–2 sentences: what we're proposing to build or do, at a level of abstraction that doesn't require technical knowledge to evaluate.]

**Why this, why now**
[Bullet list, 3–5 items. Each item is a specific data point — a call count, a lost deal, a competitor move, a customer quote. No vague claims.]

**Design principles**
[2–3 guardrails for how this should be built or executed. E.g., "Must work for a solo gym owner with no staff" or "Should not require an Avoma-style setup — the owner does this themselves."]

**What good looks like in 90 days**
[2–3 specific, measurable signals. Not aspirational — testable.]

**What we're not doing**
[1–3 explicit out-of-scope items. This prevents scope creep and shows the pitch has been stress-tested.]

**Open questions**
[2–4 unresolved items that the reader should weigh in on. Frame each as a question, not a concern.]

---

**Tone guidance for the spec:**
- Write like you're pitching to a smart skeptic, not a cheerleader
- Use specific numbers and customer quotes where available; label estimates as estimates
- Don't oversell — if the evidence is thin, say so and explain why you think it's still worth pursuing
- Offer to save the finished spec where Trent works: drop it in `data/projects.md`, draft it into Notion via the MCP, or hand it back as paste-ready markdown.

---

## Usage notes

- This skill works best when Trent pastes a rough idea or a few bullet points. It doesn't need a polished input — the skill does the shaping.
- Phase 1 should feel like a tough conversation, not a checklist. Push back on weak reasoning even if the idea sounds good.
- Phase 2 research depth scales to the size of the decision. A small UI improvement needs one quick pass over the pipeline cache and competitor files. A new pricing tier or ICP expansion warrants the full four-source parallel scan plus live web search.
- The final spec should be shareable as-is — paste it into Notion, email it to Luke, or use it as the basis for a Loom walkthrough.
- If Trent wants to skip Phase 1 and go straight to a spec, flag it once: *"I can do that, but we'll end up with a weaker document. Want to spend 5 minutes on framing first?"*
