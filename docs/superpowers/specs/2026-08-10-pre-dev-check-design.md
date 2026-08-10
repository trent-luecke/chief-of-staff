# Pre-Dev Check — Feature Pre-Mortem Gate

*Design spec — 2026-08-10*

## One-line

A skill that ingests a feature-planning transcript and returns a **Blind-Spot Report**: what the proposed feature quietly breaks, what cross-cutting concerns it forgets, and what operational contingencies it hasn't accounted for — grounded in the actual TeamBuildr OS codebase — so Trent and Teofe catch the misses *before* the plan reaches devs.

## The problem

Trent and Teofe's feature-planning cycles almost always miss a consideration, caveat, or limitation that only surfaces during the dev/build phase, causing delay and expense.

**Canonical example — member-booked appointments.** Members were given the ability to self-book appointments (previously staff-only via the studio view). Payroll had been purpose-built so a staff member assigns a pay rate to a schedule item *at the moment of creation*. There was no concept of a pre-assigned pay rate per appointment type for a member-initiated booking. Opening creation to a new actor (member) silently invalidated payroll's buried assumption ("the creator is staff and sets the rate").

This is not a random oversight — it's a **repeatable failure class**: an existing system holds a buried assumption, and the new feature invalidates it by changing *who* acts, *where* something enters the system, *what states* exist, *how much* volume flows, or *how* a piece of data is produced.

The reason these misses are hard to catch in planning: **the coupling lives in the code, not in the feature description on the whiteboard.**

## Where this fits

This is the **technical/feasibility counterpart** to the existing `os-feature-shaping` skill.

| | `os-feature-shaping` (exists) | `pre-dev-check` (this spec) |
|---|---|---|
| Question | *Should* we build this, and why? | What will building this quietly *break*? |
| Grounds in | Business data layer (pipeline, Avoma, competitors, Notion) | The OS **codebase** + a curated system map |
| Timing | Before/during shaping | **After** shaping, **before** dev handoff |
| Output | 2-min decision doc | Blind-Spot Report |

The two are complementary and can be run back-to-back on the same initiative. `pre-dev-check` never re-litigates whether to build the thing — it assumes the decision is made and interrogates the plan.

## Workflow

1. Trent + Teofe run their normal shaping session → produces a transcript (+ any rough plan notes).
2. Trent hands the transcript to the skill.
3. The skill:
   a. Extracts *what is actually being built* from the transcript — specifically the **changes** it introduces (new actors, entry points, states, scale, data).
   b. Runs those changes through the analysis lens against the **system map** + **targeted code reads** into the affected subsystems.
   c. Sweeps the fixed cross-cutting-concern checklist.
   d. Adds a light operational-contingency layer.
   e. Produces the Blind-Spot Report.
   f. Appends any newly discovered couplings back into the system map.
4. Trent + Teofe fold the catches into the plan, then send to devs.

Output is paste-ready markdown (Notion / planning doc), matching how `os-feature-shaping` and `parse-internal-meeting` already deliver.

## The analysis lens (the heart)

The engine checks the feature against the specific **kinds of change that invalidate existing assumptions**. For each change it detects in the transcript, it traces the systems that depended on the old version.

1. **Actor change** — who can now perform this action? (e.g. staff-only → member)
   - Breaks: data the old actor used to set at action time (← *the payroll rate*), permission checks, notifications addressed to the old actor, audit trails, ownership/attribution.
2. **Entry-point change** — a new path into the system (e.g. studio view → member booking flow).
   - Breaks: validation and business rules that lived only on the old path, default values, required fields, side effects triggered only by the old entry point.
3. **State / lifecycle change** — new states or transitions (e.g. members can now cancel).
   - Breaks: cancellation policy, refunds, capacity release, payroll reversal, downstream state machines.
4. **Scale / cardinality change** — self-serve implies more, and more concurrent, activity.
   - Breaks: capacity limits, double-booking guards, rate limits, performance assumptions.
5. **Data coupling** — a field or record another system reads is now produced differently, later, or not at all.
   - Breaks: every downstream consumer of that field (reporting, billing, exports, integrations).

Then a fixed sweep of **cross-cutting concerns that ride along with almost any feature and are routinely forgotten**:

> payroll · billing/payments · notifications & comms · permissions/roles · waivers & agreements · reporting/analytics · cancellation/refunds · capacity · timezones · multi-location · audit/logging · **migration of existing data & in-flight records**

Each concern is checked as: *does this feature touch it? if so, is the touch handled in the plan?* — hit / miss / N-A with a one-line reason.

### Light operational-contingency layer

Beyond code/product breakage, a short section flags non-code contingencies:
- **Support/CS** — new failure modes or questions this creates for the support team.
- **Docs/help center** — what needs documenting or updating.
- **Customer comms/rollout** — does this need announcing, gating, or a migration message to existing customers?
- **Pricing/packaging** — any tier/entitlement implication.

Kept deliberately light — a handful of pointed bullets, not a second full analysis.

## The system map

A curated, version-controlled description of OS's architecture *as it pertains to coupling* — not a full code map, only what's needed to reason about blast radius.

- **Contents:** entities (schedule item, appointment type, member, staff, payroll record…), actors and their capabilities, the cross-cutting concerns and where each one hooks in, and a running catalog of **known couplings** (each: system A depends on assumption X held by system B; where in code; how discovered).
- **Seeded once** by a deep scan of `GymStudio/backend`, starting with the scheduling/payroll subsystem (the known anchor), expanding outward as capacity allows.
- **Grows every run:** any coupling discovered during an analysis — or any real miss that reaches production — is appended. This is the compounding asset that makes the tool progressively better at catching OS-specific misses.
- **Location:** inside the chief-of-staff repo alongside the skill (version-controlled, travels with the skill). Architectural knowledge only — no secrets, no credentials.

## Repo access — local mirror

`GymStudio/*` is not cloned locally today. The skill relies on a **local mirror** of the key repos:

- Clone target repos to a location **outside** the chief-of-staff working tree (so OS source is never committed into it) — proposed `~/dev/gymstudio/`.
- Seed with `backend` (payroll/booking/scheduling live here); add `client-frontend` and `admin-frontend` as entry-point/actor tracing requires.
- The skill `git pull`s the mirror to refresh before a run and warns if the mirror is missing or stale.
- Reads are **targeted**: only into the subsystems the detected changes touch — not a full re-scan every run (the map carries recurring knowledge).

Trade-off accepted vs. on-demand `gh` reads: some local disk and a refresh step, in exchange for fast, deep tracing.

## The Blind-Spot Report (output format)

```
# Blind-Spot Report — <feature name>
_Source: <transcript name> · <date> · map v<n> · mirror @ <backend sha>_

## What we understood you're building
<2–3 sentences restating the feature from the transcript, so misreads are caught immediately>

## Changes this introduces
- Actor: <…>   Entry-point: <…>   State: <…>   Scale: <…>   Data: <…>
  (only the ones that apply)

## Blind spots & breakages   [ranked: severity × confidence]
1. **<title>**  — <what breaks and why> · <where in code / map ref> · **Grounding: code-confirmed | map | heuristic** · Suggested consideration: <…>
2. …

## Cross-cutting concern sweep
| Concern | Touched? | Handled in plan? | Note |
| payroll | yes | NO | … |
| billing | … | … | … |
…

## Operational contingencies
- Support: … · Docs: … · Comms: … · Pricing: …

## Open questions for dev
- <framed as questions>

## New couplings added to the map
- <coupling> (from this analysis)
```

**Grounding discipline (critical):** every finding is tagged `code-confirmed` (verified in source), `map` (from a recorded coupling), or `heuristic` (pattern-flagged, needs verification). The tool must never present a heuristic guess as a confirmed breakage. When a subsystem is neither in the map nor readable in the mirror, it says so plainly rather than fabricating.

## Skill structure

Follows the `os-feature-shaping` / `parse-internal-meeting` pattern: a `SKILL.md` with phased instructions, living at `.claude/skills/pre-dev-check/`.

- **Phase 0 (one-time / occasional):** seed & refresh the system map from the mirror.
- **Phase 1:** ingest transcript → extract feature + detect changes.
- **Phase 2:** run the change-lens analysis (map + targeted code reads).
- **Phase 3:** cross-cutting-concern sweep.
- **Phase 4:** operational-contingency layer.
- **Phase 5:** emit report + append new couplings to the map.

## Error handling / edge cases

- **Vague transcript** — if the feature or its changes can't be pinned down, the skill asks for the plan notes or a clarifying detail rather than guessing.
- **Missing/stale mirror** — refresh via `git pull`; if the mirror is absent, instruct how to clone and stop rather than running blind.
- **Unmapped, unreadable subsystem** — flag as a gap ("couldn't verify — no map entry, not located in mirror"), never fabricate a coupling.
- **Over-flagging** — findings are ranked and grounding-tagged so a wall of low-confidence heuristics doesn't drown the real catches.

## Testing / validation

- **Backtest against the payroll miss:** feed a reconstructed member-booked-appointments transcript and confirm the report surfaces the payroll actor/data coupling as a high-severity, code-confirmed finding. This is the acceptance test — if it doesn't catch the known miss, the design has failed.
- Dry-run on one or two additional past features where a miss is known, if transcripts exist.

## Explicitly out of scope (YAGNI)

- No automatic writing into dev tickets / Notion / task trackers — output is a report Trent places himself.
- Not a "should we build it" evaluator — that's `os-feature-shaping`.
- No full architectural documentation of OS — the map only holds coupling-relevant knowledge.
- No CI/automated trigger — invoked manually per planning cycle.

## Open questions for review

1. Mirror location — is `~/dev/gymstudio/` fine, or is there an existing clone path you'd rather use?
2. Map location — `.claude/skills/pre-dev-check/system-map/` (with the skill) vs. `data/` — any preference?
3. For the seed scan, is `backend` alone enough to start, or do you want `client-frontend` mirrored from day one (the member booking flow lives there)?
