---
name: funnel-audit
description: >
  Audits and shapes the TeamBuildr OS marketing funnel. Maintains a catalog of
  marketing assets tagged by funnel stage (TOFU/MOFU/BOFU), and runs four modes:
  seed the catalog from a strategy doc, audit a campaign concept for funnel-stage
  coverage, report content dispersion across stages, and generate grounded MOFU
  ideas. Use when Trent says "audit this campaign", "where are we thin in the
  funnel", "give me MOFU ideas", "log these assets", "seed the funnel catalog",
  or pastes a marketing strategy/campaign document and wants funnel analysis.
  Grounded in Avoma calls, the JTBD positioning snapshot, market-intel, and the
  pipeline cache. This is a content-classification and advisory tool, NOT a
  performance-measurement one — performance analysis is deferred until HubSpot
  can be connected.
---

# Funnel Audit

This skill maintains a catalog of TeamBuildr OS marketing assets and reasons
over it to shore up the middle of the funnel. TeamBuildr's funnel shape:
**TOFU = Awareness** (abundant), **MOFU = Consideration** (the structural gap —
the only stretch that should be content-carried but currently isn't), and
**BOFU = Evaluation + Decision** (mostly a salesperson + the platform, with some
sales-enablement content). Do not report toward a 33/33/33 balance — MOFU
thinness is the point.

## The catalog

The single source of truth is `data/funnel/content_catalog.json`, owned by the
deterministic helper `lib/funnel_catalog.py`. **Never hand-edit the JSON or
re-implement its logic** — call the helper. Read it in a Python session:

```python
from pathlib import Path
from lib import funnel_catalog as fc

catalog = fc.load_catalog()          # list[dict], [] if empty
# ... classify / mutate via fc.add_asset(asset, catalog, today="YYYY-MM-DD") ...
fc.save_catalog(catalog)             # persists to data/funnel/content_catalog.json
```

Vocabularies live in the helper: `fc.STAGES`, `fc.SUB_STAGES`,
`fc.STAGE_SUBSTAGE`, `fc.TYPES` (+ `fc.TYPE_STAGE_HINT`), `fc.ICPS`,
`fc.PRODUCTS`, `fc.STATUSES`, `fc.SOURCES`. Every asset written MUST pass
`fc.validate_asset` (=[] errors). Record shape:

```
id, title, type, stage, sub_stage, product(default "os"), theme,
icp[list], status, publish_date, url, source, campaign, added_at, notes
```

**Before writing any asset:** run `fc.stage_type_warning` (surface odd
stage/type combos to Trent, don't block), `fc.find_duplicates` (ask before
creating a near-duplicate), and `fc.similar_themes` (offer an existing theme so
"retention" / "member retention" don't fragment). Generated ideas are written
`status="planned"`, `source="campaign_audit"` (or `"manual"`) — never `"live"`.

**After any catalog write**, tell Trent to commit + push (origin/main is a live
datastore; rebase before push):

```bash
git add data/funnel/content_catalog.json && git commit -m "data(funnel): update content catalog"
git pull --rebase origin main && git push origin main
```

## Grounding sources (read automatically for Modes 2 and 4)

Every audit/ideation output MUST begin with a **"Sources pulled"** block: which
calls were scanned (with date range), which deals were referenced, and the
unique-prospect counts behind each claim. If a source can't be reached, say so
in that block — never silently omit it.

1. **Avoma transcripts — the MOFU goldmine.** Scan analyzed call data for
   recurring consideration-stage questions/objections and count how many
   *unique* prospects raised each. Route by shape (per project convention):
   enumeration/date/"all"/"count" → `query-avoma` skill (live REST); content /
   patterns / "what do prospects ask about X" → the `avoma-transcripts` MCP
   `search_transcripts`. Attribute mentions to reps in `config.json` →
   `avoma.sales_rep_emails`. A question 6 prospects asked unprompted is a MOFU
   brief writing itself.
2. **JTBD + positioning snapshot — the guardrail layer.**
   `docs/teambuildr-jtbd-product-knowledge-snapshot.md` tags claims
   `[PROVABLE] / [POSITIONING] / [INTERNAL] / [GUARDRAIL]`. Check every generated
   idea against it. If an idea leans on a non-`[PROVABLE]` claim or brushes a
   guardrail (attacking "two invoices / two products", framing CRM/marketing as
   a gap, claiming published price vs. PushPress/Wodify/Walla), **keep the idea
   but attach a visible `⚠ guardrail:` note** naming the rule and why — do NOT
   suppress it. Cite which `[PROVABLE]` claims back each brief.
3. **market-intel competitor data** — read `market-intel/data/competitors/*.md`,
   `market-intel/data/trends/`, `market-intel/data/features/` so comparison
   content is current and steers around themes competitors already own. Reach
   for live web search only to fill a specific gap.
4. **Pipeline cache** — `data/pipeline_cache.json`. **Check `fetched_at`
   freshness first**; if older than `config.json` → `pipeline.cache_stale_warn_days`
   (7) days, say so and offer the `sync-pipeline-cache` skill before trusting it.
   Late-stage statuses are in `pipeline.late_stage_statuses`. Prioritize MOFU/BOFU
   ideas for the ICP segment with deals actively stalling in consideration now.

## Mode routing

Detect the mode from what Trent provides:

### Mode 1 · Seed
Trigger: Trent pastes a YTD strategy / initiatives doc, or "seed the catalog".
1. Extract each asset/initiative from the doc.
2. Classify each into `stage / sub_stage / type / product / icp / theme`,
   `status` (usually `live` for existing assets), `source="seed"`, and
   `publish_date` if the doc gives one.
3. Present ALL proposed rows as a table for Trent to correct BEFORE writing.
   Run `stage_type_warning` + `similar_themes` per row and show the flags.
4. On approval, `add_asset` each into the loaded catalog, `save_catalog`, then
   give the commit/push reminder.

### Mode 2 · Campaign audit (core loop)
Trigger: Trent pastes a campaign concept/outline, or "audit this campaign".
Read grounding sources 1–4 first; open with the Sources-pulled block. Then:
1. Map each *intended* asset in the campaign to a funnel stage.
2. Cross-reference the existing catalog — covered vs. net-new (only `live`/`draft`
   count as covered; `planned` is intent, not coverage).
3. Flag coverage gaps against the campaign's own goal, emphasizing the **MOFU
   bridge**: does Awareness content hand off to a Consideration asset, or
   dead-end before the salesperson?
4. Generate specific gap-filling assets: title, format (`type`), stage, the
   prospect pain it answers (with unique-prospect count), supporting
   `[PROVABLE]` claims, and any `⚠ guardrail:` flag.
5. Offer to log the campaign's assets to the catalog (`status="planned"`,
   `source="campaign_audit"`, `campaign=<name>`), then the commit/push reminder.

### Mode 3 · Dispersion report
Trigger: "where are we thin", "show funnel dispersion", "what's our balance".
1. `d = fc.dispersion(fc.load_catalog())`.
2. If `d["total"]` is small (< ~10), state plainly the catalog is sparse and
   conclusions are weak until seeded — no false confidence.
3. Render the stage split and the secondary axes (`by_type`, `by_icp`,
   `by_theme`, `by_product`, `by_stage_status`). Frame narratively around the
   MOFU bridge, not equal buckets. Call out theme-continuity gaps (a theme loud
   at TOFU that vanishes by MOFU) using `by_theme` cross-referenced with stage.

### Mode 4 · MOFU ideation
Trigger: "give me MOFU ideas", "consideration-stage content".
Read grounding sources 1, 2, 4; open with the Sources-pulled block. Generate
Consideration-stage briefs anchored to (a) real gaps from the catalog and (b)
real prospect questions from Avoma, each with supporting `[PROVABLE]` claims and
any `⚠ guardrail:` flag. Offer to log accepted ideas (`status="planned"`).

## Out of scope (deferred)
- Performance / "what's lagging" — blocked on HubSpot; the catalog's `sub_stage`
  + `url` are built ready for it.
- Auto-population from HubSpot, passive nudges/dashboards, finished-copy drafting.
