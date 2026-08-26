# Funnel Audit Skill — Design

**Date:** 2026-08-26
**Owner:** Trent Luecke (VP Sales, TeamBuildr)
**Status:** Approved for planning
**Origin:** RevOps conversation — TeamBuildr OS marketing funnel is heavy top-of-funnel, structurally thin in the middle (MOFU), with a large gap between TOFU content and BOFU (demo/trial/salesperson) interaction.

---

## Problem

TeamBuildr OS produces a lot of top-of-funnel (Awareness) content and has a bottom-of-funnel motion carried by a salesperson and the platform itself. The **middle of the funnel (Consideration / MOFU) is the structural gap** — the bridge that is supposed to be content-carried but currently is not. There is no tool to (a) generate MOFU ideas to shore up the short-term need, (b) see how content effort is dispersed across funnel stages, or (c) audit a proposed campaign for where it is covered vs. thin.

Two hard constraints shaped this design:

1. **Content is scattered** across HubSpot, Drive, and people's heads — there is no single source of truth, so the asset inventory cannot be auto-built today.
2. **Performance data lives in HubSpot**, which is not yet connectable. Therefore "audit performance / what's lagging" is genuinely blocked and is explicitly deferred; this tool is a *content-classification and advisory* system, not a performance-measurement one.

## Goal

A single Claude Code skill, `funnel-audit`, that:

- Generates grounded **MOFU asset ideas** to shore up the short-term gap.
- **Audits a proposed campaign** document for funnel-stage coverage and generates assets to fill gaps.
- Shows the **dispersion** of content effort across funnel stages (and by type / ICP / theme / product).
- Maintains a lightweight **content catalog** that grows as a *byproduct of use* — never as separate maintenance homework.

## Non-Goals (explicitly deferred)

- **Performance / "what's lagging" analysis** — blocked on HubSpot; catalog is built ready for it (see HubSpot-readiness).
- **Auto-population of the catalog** from HubSpot or any source — deferred until a HubSpot connector exists.
- **Passive nudges / dispersion dashboard** (daily-brief callout or Registry UI tab) — revisit once the catalog is large enough to be worth surfacing.
- **Finished copy production** — the skill outputs briefs and angles, not publish-ready copy.
- **Pinecone / embeddings** — catalog is small and read whole; semantic retrieval is premature.

---

## Architecture

One project-level skill backed by one committed flat file. No runtime job, no cron, no email, no R2.

- **Skill:** `.claude/skills/funnel-audit/SKILL.md` (same pattern as `os-feature-shaping`).
- **Catalog:** `data/funnel/content_catalog.json` — git-tracked via a new `!data/funnel/` allow-list line in `.gitignore`.
- **Invocation:** local Claude Code only. The skill reads/writes the working tree directly (no `registry_storage` plumbing, since no runtime job — brief, ask, avoma — touches this file). After any catalog write, the skill reminds the user to commit + push so `origin/main` does not drift (per repo push discipline in `CLAUDE.md`).

### The catalog (the spine)

`data/funnel/content_catalog.json` is a JSON list of asset records. Everything else (dispersion, gap detection, campaign audit) reads from this.

```json
{
  "id": "asset-a1b2",
  "title": "CrossFit programming ROI calculator",
  "type": "roi_calculator",
  "stage": "BOFU",
  "sub_stage": "evaluation",
  "product": "os",
  "theme": "proving ROI / justifying spend",
  "icp": ["crossfit", "sports_performance"],
  "status": "live",
  "publish_date": "2026-05-14",
  "url": "https://... (HubSpot/Drive link, optional)",
  "source": "campaign_audit",
  "campaign": "Q3 CrossFit push (optional)",
  "added_at": "2026-08-26",
  "notes": "..."
}
```

**Field semantics:**

| Field | Values | Notes |
|---|---|---|
| `stage` | `TOFU` \| `MOFU` \| `BOFU` | The primary funnel axis. Trent's mapping: TOFU=Awareness, MOFU=Consideration, BOFU=Evaluation+Decision collapsed (prospect is with a salesperson or on the platform by then). |
| `sub_stage` | `awareness` \| `consideration` \| `evaluation` \| `decision` | Stored under the hood so a future HubSpot lifecycle-stage mapping drops in with **no re-tag**. |
| `type` | controlled vocabulary (below) | The format axis — second dimension of the dispersion view. Controlled, never free text, or aggregation fragments. |
| `product` | `os` \| `strength` \| `both` | Defaults to `os`. Prevents Strength programming content from inflating the OS funnel's MOFU counts. Docs warn heavily against conflating the two products. |
| `theme` | free text, nudged toward reuse | Narrative axis — surfaces theme-continuity gaps (a theme loud at TOFU that vanishes by MOFU). Skill nudges toward existing themes to avoid fragmentation. |
| `icp` | list of segment slugs (below) | An asset can serve multiple segments. |
| `status` | `live` \| `draft` \| `planned` \| `retired` | A `planned` asset does **not** count as covering a gap. Audit distinguishes "we have it" from "we intend it." |
| `publish_date` | ISO date | Real-world publish/launch date. Distinct from `added_at` (when it entered the catalog). Powers a future recency view. |
| `source` | `seed` \| `campaign_audit` \| `manual` | Provenance. |

**Type controlled vocabulary** (tendencies noted, not enforced — `stage` and `type` are independent; skill warns on unusual combos but does not block):

- Typically TOFU: `blog`, `social_post`, `podcast`, `short_video`, `infographic`, `guest_article`
- Typically MOFU: `webinar`, `ebook_guide`, `email_nurture`, `comparison_guide`, `checklist_template`, `case_study`
- Typically BOFU: `roi_calculator`, `demo_video`, `comparison_page`, `objection_one_pager`, `pricing_page`, `customer_story`
- Stage-flexible: `interactive_tool` (TOFU/MOFU lead-magnet tools — e.g. StoryBuildr, Profit Calculator; distinct from `roi_calculator`, which is a BOFU calculator handed to a prospect mid-sales-cycle)

**ICP segment slugs** (hard-coded, drawn from repo docs — JTBD snapshot, competitor spec, project memory):

| Slug | Segment |
|---|---|
| `sports_performance` | Sport-performance coaches / facilities (crown-jewel fit) |
| `crossfit` | CrossFit / functional-fitness boxes |
| `pt_studio` | Personal-training studios |
| `hybrid_clinic_gym` | Clinician-owned rehab/PT + performance (emerging segment) |
| `boutique` | General-population class / class-adjacent facilities (catch-all) |

---

## The four modes

`funnel-audit` is one skill that routes on what the user provides.

### Mode 1 · Seed
User pastes a YTD strategy/initiatives doc (or any batch of assets). The skill extracts each asset, classifies it (`stage` / `sub_stage` / `type` / `product` / `icp` / `theme`), presents the proposed rows as a table for correction, then writes confirmed rows to the catalog. This is the initial large deposit and the path for later batch adds.

### Mode 2 · Campaign audit (core loop)
User pastes a campaign concept/outline. The skill:
1. Maps each *intended* asset in the campaign to a funnel stage.
2. Cross-references the existing catalog — what the campaign already has covered vs. net-new.
3. Flags coverage gaps against the campaign's own goal, with emphasis on the MOFU bridge (does Awareness content hand off to a Consideration-stage asset, or dead-end before the salesperson?).
4. Generates specific assets to fill gaps (title, format, stage, the prospect pain it answers, supporting `[PROVABLE]` claims, and any `⚠ guardrail:` flag) — grounded per Grounding Sources.
5. Proposes logging the campaign's assets to the catalog (byproduct capture), status `planned` unless told otherwise.

### Mode 3 · Dispersion report
Reads the whole catalog. Shows the TOFU/MOFU/BOFU split and the secondary axes (by `type`, `icp`, `theme`, `product`). Framed for TeamBuildr's actual funnel shape — **not** a 33/33/33 target, but "MOFU is the structural bridge and it's thin; here is Awareness content that never gets a Consideration follow-through." Includes the theme-continuity check.

### Mode 4 · MOFU ideation
Focused Consideration-stage brainstorm for the short-term need. Grounded in real catalog gaps + real prospect questions (Grounding Sources).

---

## Grounding sources

Modes 2 and 4 read these automatically. Every output **leads with a "Sources pulled" block** — which calls were scanned (with date range), which deals were referenced, and the unique-prospect counts behind each claim — so the evidence is always visible, not just the conclusion.

1. **Avoma transcripts — the MOFU goldmine.** Scans analyzed call data (via the Notion meeting-notes MCP / `query-avoma`) for recurring consideration-stage questions and objections, counting how many *unique* prospects raised each. A question 6 prospects asked unprompted is a MOFU asset brief writing itself. This is what separates grounded output from generic B2B idea lists.
2. **JTBD + positioning snapshot — the guardrail layer.** `docs/teambuildr-jtbd-product-knowledge-snapshot.md` tags claims `[PROVABLE] / [POSITIONING] / [INTERNAL] / [GUARDRAIL]`. Every generated asset idea is checked against it, and any idea that leans on a non-`[PROVABLE]` claim or trips an explicit guardrail (attacking "two invoices," framing CRM/marketing as a gap, claiming published price against PushPress/Wodify/Walla) is **flagged with the specific conflict for Trent to decide on — not silently suppressed.** The idea still appears; it carries a visible `⚠ guardrail:` note naming the rule it brushes against and why. Generated briefs cite which `[PROVABLE]` claims back them. Highest-leverage grounding — surfaces the positioning risk on every idea so nothing reaches a copywriter unexamined, while keeping the call with Trent.
3. **market-intel competitor data** (`market-intel/data/`) — keeps comparison/differentiation content current and steers around themes competitors already own.
4. **Pipeline cache** (`data/pipeline_cache.json`) — which ICP segments have deals actively stalling in the consideration/evaluation zone now, so MOFU/BOFU ideation prioritizes the segment losing deals this quarter. Checks `fetched_at` freshness first; warns and offers `sync-pipeline-cache` if stale (>7 days).

**Scope guardrail:** the skill produces **briefs and angles**, not finished copy. Generated assets land in the catalog as `planned`, never `live`.

---

## Error handling & edge cases

- **Empty catalog:** Mode 3 and gap analysis in Mode 2 state plainly that the catalog is sparse and that conclusions are weak until seeded — no false confidence from a 3-item catalog.
- **Stale pipeline cache:** warn and offer to re-sync before trusting pipeline grounding.
- **Unusual stage/type combo:** warn (possible mistag), do not block.
- **Theme fragmentation:** on write, surface existing similar themes for reuse.
- **Duplicate asset:** on write, match against existing titles/URLs and ask before creating a near-duplicate.
- **Offline / MCP unavailable (Avoma/Notion):** proceed with the sources that are available, and say explicitly in "Sources pulled" which source could not be reached — never silently omit.
- **Push discipline:** after any catalog write, remind the user to commit + push so `origin/main` does not drift.

---

## HubSpot-readiness (Phase 2, deferred)

The catalog is built so the eventual HubSpot connector is additive, not a rebuild:

- `sub_stage` already maps to HubSpot lifecycle stages → no re-tag when performance data arrives.
- `url` links each catalog asset to its HubSpot/Drive counterpart.
- A future per-asset `performance` block (views, conversions, influenced pipeline) flips Mode 3 from *content dispersion* → *content performance*, unblocking the deferred "what's lagging" goal.
- HubSpot can later auto-populate the catalog, resolving the scattered-content root cause; until then, byproduct capture fills it.

---

## Success criteria

- Seeding the YTD doc produces a catalog whose stage/type/ICP tags Trent agrees with after minimal correction.
- A campaign audit surfaces at least one MOFU gap Trent recognizes as real and hands back asset briefs specific enough to act on (grounded in named calls/deals, with any positioning-guardrail conflicts flagged rather than hidden).
- The dispersion report makes the MOFU thinness legible at a glance and ties gaps to real prospect questions.
- The catalog grows across sessions without any dedicated maintenance effort.
