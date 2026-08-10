# Pre-Dev Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. When authoring `SKILL.md` and reference files, also follow superpowers:writing-skills.

**Goal:** Build a `pre-dev-check` skill that ingests a feature-planning transcript and returns a codebase-grounded Blind-Spot Report, catching the "we forgot payroll" class of miss before dev handoff.

**Architecture:** A phased Claude skill (`.claude/skills/pre-dev-check/`) reads a transcript, detects the *changes* the feature introduces, and traces their blast radius against (a) a curated, version-controlled **system map** and (b) targeted reads of a **local mirror** of `GymStudio/backend` + `admin-frontend`. It sweeps a fixed cross-cutting-concern checklist, adds a light operational layer, emits a markdown report, and appends any newly found couplings back to the map so it compounds.

**Tech Stack:** Markdown skill files (SKILL.md + reference + system-map), `git` for the local mirror, `gh` for repo access. No new runtime dependencies. Existing skill patterns to mirror: `.claude/skills/os-feature-shaping/SKILL.md`, `.claude/skills/parse-internal-meeting/SKILL.md`.

## Global Constraints

- **Grounding discipline:** every report finding MUST be tagged `code-confirmed` | `map` | `heuristic`. A heuristic guess is NEVER presented as a confirmed breakage.
- **Mirror isolation:** the OS source mirror lives at `~/dev/gymstudio/`, OUTSIDE the chief-of-staff working tree, and is NEVER committed into this repo.
- **No secrets in the map:** the system map holds architectural/coupling knowledge only — no credentials, tokens, customer data, or secrets copied from source.
- **Output is paste-ready markdown** (for Notion / planning docs), matching `os-feature-shaping` and `parse-internal-meeting` delivery.
- **Follow existing skill conventions** in `.claude/skills/` (frontmatter shape, phased structure, tone).
- **This skill never re-evaluates whether to build the feature** — that is `os-feature-shaping`. It assumes the decision is made and interrogates the plan.

## File Structure

```
~/dev/gymstudio/                                  # local mirror (OUTSIDE repo, never committed)
  backend/                                        #   shallow clone of GymStudio/backend
  admin-frontend/                                 #   shallow clone of GymStudio/admin-frontend

.claude/skills/pre-dev-check/
  SKILL.md                                        # entry point: frontmatter + 5 phases
  reference/
    analysis-lens.md                              # the 5 change-types + what each breaks
    cross-cutting-concerns.md                     # the fixed concern checklist + hook locations
    report-template.md                            # the Blind-Spot Report format
    mirror-setup.md                               # how to clone/refresh the mirror
  system-map/
    README.md                                     # map organization + version + how to extend
    entities-and-actors.md                        # OS entities, actors, capabilities
    couplings.md                                  # running catalog of known couplings (compounds)
    subsystems/
      scheduling-payroll.md                       # anchor subsystem deep-dive
  test/
    fixtures/member-booked-appointments.md        # reconstructed backtest transcript
    expected-findings.md                          # what the report MUST contain to pass
```

---

### Task 1: Set up the local OS mirror

**Files:**
- Create: `~/dev/gymstudio/backend` (clone), `~/dev/gymstudio/admin-frontend` (clone)
- Create: `.claude/skills/pre-dev-check/reference/mirror-setup.md`

**Interfaces:**
- Produces: a refreshable local mirror at `~/dev/gymstudio/<repo>`; the documented refresh procedure other phases rely on.

- [ ] **Step 1: Verify repo access**

Run:
```bash
gh repo view GymStudio/backend --json name,visibility -q '.name+" "+.visibility' && \
gh repo view GymStudio/admin-frontend --json name,visibility -q '.name+" "+.visibility'
```
Expected: `backend PRIVATE` and `admin-frontend PRIVATE` printed. If this errors, stop — access must be resolved first.

- [ ] **Step 2: Shallow-clone both repos into the mirror**

Reads only current code, so history is not needed (`--depth 1` keeps disk/time small).
```bash
mkdir -p ~/dev/gymstudio && cd ~/dev/gymstudio && \
gh repo clone GymStudio/backend -- --depth 1 && \
gh repo clone GymStudio/admin-frontend -- --depth 1
```

- [ ] **Step 3: Verify the clones are readable**

Run:
```bash
git -C ~/dev/gymstudio/backend rev-parse --short HEAD && \
git -C ~/dev/gymstudio/admin-frontend rev-parse --short HEAD
```
Expected: two short SHAs printed.

- [ ] **Step 4: Write the mirror-setup reference**

Create `.claude/skills/pre-dev-check/reference/mirror-setup.md` with the exact clone commands above plus this refresh procedure:
```markdown
# Mirror setup & refresh

The mirror lives at `~/dev/gymstudio/` — OUTSIDE the chief-of-staff repo. Never commit it.

## First-time clone
    mkdir -p ~/dev/gymstudio && cd ~/dev/gymstudio
    gh repo clone GymStudio/backend -- --depth 1
    gh repo clone GymStudio/admin-frontend -- --depth 1

## Refresh before every analysis run
    git -C ~/dev/gymstudio/backend pull --depth 1 --ff-only
    git -C ~/dev/gymstudio/admin-frontend pull --depth 1 --ff-only

## On-demand (member-facing entry points)
    cd ~/dev/gymstudio && gh repo clone GymStudio/client-frontend -- --depth 1

## Record the SHA in every report
    git -C ~/dev/gymstudio/backend rev-parse --short HEAD

If a mirror directory is missing, run the first-time clone and STOP — do not analyze against a missing mirror.
```

- [ ] **Step 5: Confirm the mirror is not tracked by the chief-of-staff repo**

Run:
```bash
cd ~/dev/Claude-Projects/chief-of-staff && git status --porcelain | grep -i gymstudio || echo "OK: mirror not in repo tree"
```
Expected: `OK: mirror not in repo tree`

- [ ] **Step 6: Commit the reference file**

```bash
cd ~/dev/Claude-Projects/chief-of-staff && \
git add .claude/skills/pre-dev-check/reference/mirror-setup.md && \
git commit -m "feat(pre-dev-check): document OS mirror setup + refresh"
```

---

### Task 2: Write the static reference material (lens, concerns, report template)

These files need no code scan — they encode the analysis method and output shape.

**Files:**
- Create: `.claude/skills/pre-dev-check/reference/analysis-lens.md`
- Create: `.claude/skills/pre-dev-check/reference/cross-cutting-concerns.md`
- Create: `.claude/skills/pre-dev-check/reference/report-template.md`

**Interfaces:**
- Produces: `analysis-lens.md` (5 change-types), `cross-cutting-concerns.md` (12-item checklist), `report-template.md` (report sections) — all referenced by name from `SKILL.md` in Task 4.

- [ ] **Step 1: Write `analysis-lens.md`**

Create the file with this exact content:
```markdown
# Analysis lens — the change-types that invalidate assumptions

For each change the feature introduces, trace the systems that depended on the OLD version.

## 1. Actor change — who can now perform this action?
e.g. staff-only -> member. Breaks:
- data the old actor used to set at action time (e.g. the payroll pay rate)
- permission checks, ownership/attribution, audit trails
- notifications addressed to the old actor

## 2. Entry-point change — a new path into the system
e.g. studio view -> member booking flow. Breaks:
- validation & business rules that lived only on the old path
- default values, required fields
- side effects triggered only by the old entry point

## 3. State / lifecycle change — new states or transitions
e.g. members can now cancel. Breaks:
- cancellation policy, refunds, capacity release
- payroll reversal, downstream state machines

## 4. Scale / cardinality change — more, and more concurrent, activity
e.g. self-serve volume. Breaks:
- capacity limits, double-booking guards, rate limits
- performance assumptions

## 5. Data coupling — a field another system reads is now produced differently/later/not at all
Breaks: every downstream consumer of that field (reporting, billing, exports, integrations).

## How to use
1. From the transcript, list which of these 5 changes the feature introduces.
2. For each, consult system-map/couplings.md for known couplings, THEN do targeted reads
   into the affected subsystem in the mirror to confirm/expand.
3. Tag each finding: code-confirmed | map | heuristic.
```

- [ ] **Step 2: Write `cross-cutting-concerns.md`**

Create the file with this exact content:
```markdown
# Cross-cutting concern sweep

Concerns that ride along with almost any feature and are routinely forgotten.
For each: does the feature touch it? if so, is the touch handled in the plan?
Answer hit / miss / N-A with a one-line reason. "Hook location" is filled from the
mirror as the map matures; "not yet located" is a valid state, not a placeholder.

| Concern | Hook location (mirror path) |
|---|---|
| payroll | (to locate) |
| billing / payments | (to locate) |
| notifications & comms | (to locate) |
| permissions / roles | (to locate) |
| waivers & agreements | (to locate) |
| reporting / analytics | (to locate) |
| cancellation / refunds | (to locate) |
| capacity | (to locate) |
| timezones | (to locate) |
| multi-location | (to locate) |
| audit / logging | (to locate) |
| migration of existing data & in-flight records | (to locate) |
```

- [ ] **Step 3: Write `report-template.md`**

Create the file with this exact content:
```markdown
# Blind-Spot Report — <feature name>
_Source: <transcript name> · <date> · map v<n> · backend @ <short sha>_

## What we understood you're building
<2-3 sentences restating the feature from the transcript, so misreads are caught immediately>

## Changes this introduces
- Actor: <…> · Entry-point: <…> · State: <…> · Scale: <…> · Data: <…>
  (list only the ones that apply)

## Blind spots & breakages   [ranked: severity x confidence]
1. **<title>** — <what breaks and why> · <where in code / map ref> ·
   **Grounding: code-confirmed | map | heuristic** · Suggested consideration: <…>
2. …

## Cross-cutting concern sweep
| Concern | Touched? | Handled in plan? | Note |
|---|---|---|---|
| payroll | yes | NO | … |
| … | | | |

## Operational contingencies
- Support: … · Docs: … · Comms: … · Pricing: …

## Open questions for dev
- <framed as questions>

## New couplings added to the map
- <coupling> (from this analysis)
```

- [ ] **Step 4: Verify content criteria**

Run:
```bash
cd ~/dev/Claude-Projects/chief-of-staff/.claude/skills/pre-dev-check/reference && \
grep -c "^## [1-5]\." analysis-lens.md && \
grep -c "|" cross-cutting-concerns.md && \
grep -q "Grounding: code-confirmed | map | heuristic" report-template.md && echo "template OK"
```
Expected: `5` (five change-types), a count ≥ 14 (12 concern rows + header + separator), and `template OK`.

- [ ] **Step 5: Commit**

```bash
cd ~/dev/Claude-Projects/chief-of-staff && \
git add .claude/skills/pre-dev-check/reference/ && \
git commit -m "feat(pre-dev-check): analysis lens, concern checklist, report template"
```

---

### Task 3: Seed the system map from the mirror

Extract coupling-relevant knowledge from `backend` + `admin-frontend`, anchored on the scheduling/payroll subsystem (the known miss). The plan gives the exact file structure, a fixed per-coupling schema, and a fully worked example (the payroll coupling); executing the task fills the rest from the actual mirror code.

**Files:**
- Create: `.claude/skills/pre-dev-check/system-map/README.md`
- Create: `.claude/skills/pre-dev-check/system-map/entities-and-actors.md`
- Create: `.claude/skills/pre-dev-check/system-map/couplings.md`
- Create: `.claude/skills/pre-dev-check/system-map/subsystems/scheduling-payroll.md`

**Interfaces:**
- Consumes: the mirror from Task 1.
- Produces: `couplings.md` with a fixed per-coupling schema (used by Task 4 phase 2 and appended to at phase 5), and `subsystems/scheduling-payroll.md` documenting where the pay rate is set on a schedule item.

- [ ] **Step 1: Write the map README (schema definition)**

Create `.claude/skills/pre-dev-check/system-map/README.md`:
```markdown
# OS system map

Coupling-relevant architecture only — NOT full code documentation. No secrets.

- **Version:** v1 (bump on each meaningful seed/expansion; report cites `map v<n>`)
- **entities-and-actors.md** — OS entities, the actors, and each actor's capabilities.
- **couplings.md** — the running catalog of known couplings. Grows every analysis.
- **subsystems/** — per-subsystem deep-dives, seeded from the mirror.

## Coupling entry schema (used in couplings.md)
### <short coupling title>
- **Depends on:** <system A> assumes <assumption>
- **Held by:** <system B / where the assumption originates>
- **Invalidated when:** <which of the 5 change-types breaks it>
- **Code:** <repo/path:symbol> (mirror-relative)
- **Severity:** high | med | low
- **Discovered:** <date> · <seed scan | analysis:<feature> | production miss>
```

- [ ] **Step 2: Locate the payroll ↔ schedule-item coupling in the mirror**

Run (adjust terms to what the codebase actually uses):
```bash
cd ~/dev/gymstudio && \
grep -rniE "pay[_ ]?rate|payroll" backend --include=*.* -l | head -20 && \
grep -rniE "schedule[_ ]?item|appointment" backend --include=*.* -l | head -20
```
Read the files where pay-rate assignment and schedule-item/appointment creation intersect. Confirm: *where is the pay rate written, and by which actor, at creation time?* Note exact file path(s) and symbol name(s).

- [ ] **Step 3: Write the scheduling/payroll subsystem deep-dive**

Create `.claude/skills/pre-dev-check/system-map/subsystems/scheduling-payroll.md` documenting, from what you found in Step 2: the schedule-item/appointment model, how/where the pay rate is assigned, which actor assigns it, and at what point in the lifecycle. Cite mirror-relative paths + symbols. No secrets — describe structure, don't paste credentials or data.

- [ ] **Step 4: Record the payroll coupling in `couplings.md` (worked example)**

Create `.claude/skills/pre-dev-check/system-map/couplings.md` starting with this entry (fill the `Code:` path from Step 2):
```markdown
# Known couplings

### Pay rate assigned at schedule-item creation by the creating staff user
- **Depends on:** payroll assumes a pay rate exists on every schedule item
- **Held by:** schedule-item creation flow — the creating STAFF user sets the rate at creation
- **Invalidated when:** actor change (member-initiated creation) OR entry-point change (self-serve booking) — a member has no rate-assignment step, so the rate is never set
- **Code:** <backend/…:…> (from Step 2)
- **Severity:** high
- **Discovered:** 2026-08-10 · seed scan (known production miss: member-booked appointments)
```

- [ ] **Step 5: Write entities-and-actors**

Create `.claude/skills/pre-dev-check/system-map/entities-and-actors.md` listing the OS entities and actors you can identify from the mirror (at minimum: staff, member; schedule item, appointment type, payroll record) with each actor's relevant capabilities. Expand as the scan reveals more; incompleteness is expected at v1 and is not a placeholder.

- [ ] **Step 6: Verify the seed**

Run:
```bash
cd ~/dev/Claude-Projects/chief-of-staff/.claude/skills/pre-dev-check/system-map && \
grep -q "Severity:\*\* high" couplings.md && \
grep -qiE "backend/" couplings.md && \
test -f subsystems/scheduling-payroll.md && echo "seed OK"
```
Expected: `seed OK` (the payroll coupling is recorded with a real mirror path and the subsystem file exists).

- [ ] **Step 7: Commit**

```bash
cd ~/dev/Claude-Projects/chief-of-staff && \
git add .claude/skills/pre-dev-check/system-map/ && \
git commit -m "feat(pre-dev-check): seed system map (scheduling/payroll anchor)"
```

---

### Task 4: Write SKILL.md (the 5 phases)

**Files:**
- Create: `.claude/skills/pre-dev-check/SKILL.md`

**Interfaces:**
- Consumes: `reference/*` (Task 2), `system-map/*` (Task 3), the mirror (Task 1).
- Produces: the invocable skill; phase 5 appends to `system-map/couplings.md` using the Task-3 schema.

- [ ] **Step 1: Write the frontmatter + overview**

Model the frontmatter on `.claude/skills/os-feature-shaping/SKILL.md`. `name: pre-dev-check`; `description:` triggers on Trent bringing a feature-planning transcript / plan after shaping and before dev, e.g. "pre-mortem this plan", "what are we missing before we send this to devs", "check this feature plan", "run a blind-spot check". State explicitly it is the technical counterpart to os-feature-shaping and does NOT re-evaluate whether to build.

- [ ] **Step 2: Write Phase 0 — refresh the mirror**

Instruct: run the refresh commands from `reference/mirror-setup.md`; capture `backend` short SHA for the report; if a mirror dir is missing, run first-time clone and STOP.

- [ ] **Step 3: Write Phase 1 — ingest transcript & detect changes**

Instruct: read the transcript; restate the feature in 2-3 sentences (goes in report's "What we understood"); using `reference/analysis-lens.md`, list which of the 5 change-types the feature introduces. If the feature/changes can't be pinned down, ask for the plan notes rather than guessing.

- [ ] **Step 4: Write Phase 2 — change-lens analysis**

Instruct: for each detected change, first consult `system-map/couplings.md`, then do TARGETED reads into the affected subsystem in the mirror to confirm/expand. Every finding gets a grounding tag (code-confirmed | map | heuristic). If a subsystem is neither in the map nor locatable in the mirror, record it as a gap ("couldn't verify") — never fabricate.

- [ ] **Step 5: Write Phase 3 — cross-cutting sweep**

Instruct: walk every row of `reference/cross-cutting-concerns.md`; mark touched? / handled-in-plan? / note. Use hook locations from the map where present.

- [ ] **Step 6: Write Phase 4 — operational contingencies (light)**

Instruct: a handful of pointed bullets across Support, Docs, Comms/rollout, Pricing/packaging. Deliberately light — not a second full analysis.

- [ ] **Step 7: Write Phase 5 — emit report & grow the map**

Instruct: produce the report using `reference/report-template.md`, ranked severity x confidence; then append any newly discovered couplings to `system-map/couplings.md` using the schema, bump the map version in `system-map/README.md`, and list them under the report's "New couplings added to the map". Offer to save the report to Notion / hand back as paste-ready markdown.

- [ ] **Step 8: Verify the skill loads and is well-formed**

Run:
```bash
cd ~/dev/Claude-Projects/chief-of-staff/.claude/skills/pre-dev-check && \
head -12 SKILL.md | grep -q "name: pre-dev-check" && \
grep -c "^## Phase" SKILL.md
```
Expected: name matches and `6` (Phase 0–5) printed.

- [ ] **Step 9: Commit**

```bash
cd ~/dev/Claude-Projects/chief-of-staff && \
git add .claude/skills/pre-dev-check/SKILL.md && \
git commit -m "feat(pre-dev-check): SKILL.md 5-phase blind-spot analysis"
```

---

### Task 5: Backtest against the payroll miss (acceptance gate)

The whole design succeeds or fails here: fed a reconstructed member-booked-appointments transcript, the skill MUST surface the payroll coupling as a high-severity, code-confirmed finding.

**Files:**
- Create: `.claude/skills/pre-dev-check/test/fixtures/member-booked-appointments.md`
- Create: `.claude/skills/pre-dev-check/test/expected-findings.md`

**Interfaces:**
- Consumes: the full skill (Tasks 1–4).

- [ ] **Step 1: Write the fixture transcript**

Create `.claude/skills/pre-dev-check/test/fixtures/member-booked-appointments.md` — a realistic 1-page shaping-session transcript in which Trent + Teofe design "let members self-book appointments from the client app instead of a staff member booking it in the studio view." Include the feature intent and the actor/entry-point change, but — deliberately, mirroring the real miss — say NOTHING about payroll or pay rates.

- [ ] **Step 2: Write the expected-findings acceptance criteria**

Create `.claude/skills/pre-dev-check/test/expected-findings.md`:
```markdown
# Backtest acceptance criteria — member-booked appointments

The Blind-Spot Report PASSES only if ALL hold:
1. "Changes this introduces" lists an **actor change** (staff -> member) and an **entry-point change** (studio view -> member booking).
2. Blind spots include the **payroll pay-rate coupling**: member-initiated creation has no rate-assignment step, so the rate is never set.
3. That finding is **severity: high** and **Grounding: code-confirmed** (cites a real backend path), not heuristic.
4. The cross-cutting sweep marks **payroll = touched, NOT handled**.
5. No fabricated couplings: any unverifiable item is labeled "couldn't verify", not asserted.
```

- [ ] **Step 3: Run the skill on the fixture**

Invoke the `pre-dev-check` skill with the fixture transcript as input. Let it run all phases against the live mirror.

- [ ] **Step 4: Grade the report against the criteria**

Compare the produced report to `expected-findings.md`. Every one of the 5 criteria must hold.
Expected: all 5 pass. If criterion 2 or 3 fails (payroll not caught, or caught only as heuristic), the design has failed — fix Task 3 (map/subsystem accuracy) or Task 4 (phase 2 instructions) and re-run, do NOT loosen the criteria.

- [ ] **Step 5: Commit the fixtures**

```bash
cd ~/dev/Claude-Projects/chief-of-staff && \
git add .claude/skills/pre-dev-check/test/ && \
git commit -m "test(pre-dev-check): payroll-miss backtest fixture + acceptance criteria"
```

---

## Self-Review

**1. Spec coverage:**
- Workflow (transcript → report → fold in → devs) → Task 4 (phases) + Task 5 (fixture is a transcript). ✓
- Analysis lens (5 change-types) → Task 2 Step 1 + Task 4 Step 4. ✓
- Cross-cutting sweep (12 concerns) → Task 2 Step 2 + Task 4 Step 5. ✓
- Operational-contingency layer → Task 4 Step 6. ✓
- System map (schema, seed, grows) → Task 3 + Task 4 Step 7. ✓
- Local mirror (backend + admin-frontend, refresh, isolation) → Task 1. ✓
- Grounding discipline (code-confirmed/map/heuristic) → Global Constraints + Task 4 Step 4 + Task 5 criterion 3. ✓
- Report format → Task 2 Step 3. ✓
- Error handling (vague transcript, missing mirror, unmapped subsystem) → Task 4 Steps 2–4. ✓
- Backtest acceptance → Task 5. ✓
- Out-of-scope (no auto-ticketing, not a build/no-build evaluator) → Global Constraints + Task 4 Step 1. ✓

**2. Placeholder scan:** Content files ship complete inline. Where a step fills content from the actual mirror (map seed, subsystem doc), the plan supplies the exact schema + a worked example + precise extraction commands — the discovered content is the deliverable of execution, not a plan placeholder. No "TBD"/"handle edge cases"/"write tests for the above".

**3. Type consistency:** File paths, the coupling-entry schema (`README.md` ↔ `couplings.md` ↔ Task 4 phase 5), phase count (0–5 = 6, checked in Task 4 Step 8), and the grounding-tag vocabulary are consistent across tasks.
