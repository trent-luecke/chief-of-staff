---
name: pre-dev-check
description: >
  Runs a codebase-grounded blind-spot check on a feature plan AFTER shaping is done and BEFORE it goes to devs.
  Use when Trent pastes a feature-planning transcript or plan and says things like "pre-mortem this plan",
  "what are we missing before we send this to devs", "check this feature plan", or "run a blind-spot check".
  This is the technical coupling counterpart to os-feature-shaping: it does NOT re-litigate whether to build
  the feature or re-run the seven framing questions — it assumes the "should we build this" call is already
  made and hunts for the "we forgot payroll" class of miss by tracing what the change actually touches in the
  real OS codebase.
---

# Pre-Dev Check

Five phases, run in order. The value is in the targeted codebase reads in Phase 2 — don't let this collapse
into a generic checklist skim. Everything this skill needs to reason with already exists in this repo:

- `reference/mirror-setup.md`, `reference/analysis-lens.md`, `reference/cross-cutting-concerns.md`,
  `reference/report-template.md` — static reference material, read them, don't restate them here.
- `system-map/README.md`, `system-map/couplings.md`, `system-map/entities-and-actors.md`,
  `system-map/subsystems/` — the growing OS system map. Consult before reading code; grow it after.
- The mirror at `~/dev/gymstudio/backend` + `~/dev/gymstudio/admin-frontend` — the actual OS source, outside
  this repo, never committed here.

---

## Phase 0 — Refresh the mirror

Run the refresh commands in `reference/mirror-setup.md`. Capture the `backend` short SHA — it goes in the
report header (`backend @ <short sha>`).

If a mirror directory is missing, run the first-time clone from `reference/mirror-setup.md` and **STOP**.
Do not analyze against a missing or stale-but-absent mirror.

---

## Phase 1 — Ingest the transcript & detect change-types

Read the feature plan / transcript Trent dropped. Restate the feature in 2-3 sentences — this becomes the
report's "What we understood you're building" and is how a misread gets caught immediately, before any
codebase work is wasted on the wrong feature.

Using `reference/analysis-lens.md`, determine which of the 5 change-types the feature introduces (actor,
entry-point, state/lifecycle, scale/cardinality, data coupling). List only the ones that apply.

If the feature or its changes can't be pinned down from what was pasted, **ask** for the plan notes rather
than guessing — a wrong restatement or a missed change-type poisons every downstream phase.

---

## Phase 2 — Change-lens analysis (the core work)

For each change-type detected in Phase 1:

1. Consult `system-map/couplings.md` first — a known coupling may already document exactly what breaks.
2. Then do **targeted reads** into the affected subsystem in the mirror (start from
   `system-map/subsystems/` and `system-map/entities-and-actors.md` to orient, then follow into the actual
   backend/admin-frontend source) to confirm the known coupling still holds and to find anything the map
   doesn't yet cover.

Tag every finding with its grounding:
- **code-confirmed** — traced to actual mirror source for this analysis.
- **map** — taken from `system-map/couplings.md` without re-verifying in code this run.
- **heuristic** — inferred from the change-type pattern, not yet grounded in either.

If a subsystem the feature touches is neither in the map nor locatable in the mirror, record it as a gap
("couldn't verify") in the report. Never fabricate a coupling or a code path to fill the gap.

---

## Phase 3 — Cross-cutting sweep

Walk every row of `reference/cross-cutting-concerns.md`. For each concern, mark whether the feature touches
it and whether the plan handles that touch: hit / miss / N-A, with a one-line reason. Where the system map
already has a hook location for a concern, cite it; "not yet located" is a valid, honest answer — not a
placeholder to fill with a guess.

---

## Phase 4 — Operational contingencies (light)

A handful of pointed bullets across Support, Docs, Comms/rollout, Pricing/packaging — whatever is genuinely
relevant to this feature. This is deliberately light: a few sentences each, not a second full analysis. If a
category clearly doesn't apply, say so in one line and move on.

---

## Phase 5 — Emit the report & grow the map

Produce the report using `reference/report-template.md`. Rank blind spots by severity × confidence —
highest-severity, highest-confidence findings first.

Then, before handing back the report:

1. Append any newly discovered couplings to `system-map/couplings.md`, using the coupling entry schema in
   `system-map/README.md` (Depends on / Held by / Invalidated when / Code / Severity / Discovered).
2. Bump the map version in `system-map/README.md`.
3. List the new couplings under the report's "New couplings added to the map" section so Trent can see what
   the map learned from this run.

Offer to save the finished report to Notion (via the Notion MCP) or hand it back as paste-ready markdown —
same delivery convention as `os-feature-shaping`. This skill never writes into dev tickets or task trackers
on its own; the report is Trent's to place.

---

## Usage notes

- This skill assumes shaping already happened. If Trent pastes a rough idea that hasn't been pressure-tested
  yet, point him at `os-feature-shaping` first, or ask if he wants both run back to back.
- Depth scales with the change: a small UI tweak with no actor/entry-point change may clear Phase 2 with a
  quick map lookup and no code reads. A change that opens a new entry point or a new actor warrants full
  targeted reads before this skill's findings can be trusted.
- The system map is intentionally incomplete at any point in time — gaps are expected and should be reported
  as gaps, not padded over. The map grows a little with every run of this skill.
