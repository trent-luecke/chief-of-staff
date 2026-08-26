# TeamBuildr — JTBD + Product Knowledge Snapshot

**Purpose:** Knowledge snapshot to feed the sales-content assistant project. Consolidates the most current Jobs-To-Be-Done work and product knowledge for **TeamBuildr Strength** and **TeamBuildr OS**.
**Owner:** Trent Luecke (VP Sales, TeamBuildr) · **Snapshot date:** 2026-08-20
**Sources:** `scout/os_grounding.md` (hand-curated OS profile), `docs/os-competitor-comparison-spec.md`, the 4 JTBD interview drafts in `data/state/interviews/`, and the chief-of-staff project memory.

---

## ⚠️ How to read this (for sales content generation)

Every claim below is tagged with its confidence level. **Only `[PROVABLE]` claims are safe to put in outbound-facing sales copy without re-verification.**

| Tag | Meaning | Use in sales content? |
|-----|---------|----------------------|
| `[PROVABLE]` | Confirmed fact about our own product; safe to publish | ✅ Yes |
| `[POSITIONING]` | Confirmed strategic stance / framing we've chosen | ✅ Yes, as framing |
| `[INTERNAL]` | Directional / research finding — informs the pitch, not a public claim | ⚠️ Shape the message, don't quote as fact |
| `[GUARDRAIL]` | A thing we must NOT say | 🚫 Never |

Competitor facts are **not** included here as sales-ready claims — see `docs/os-competitor-comparison-spec.md`, where each competitor cell is separately marked confirmed vs. "(reported)". Prices/promos are volatile and must be re-pulled at publish time.

---

# PART 1 — PRODUCT KNOWLEDGE

TeamBuildr ships **two distinct products** that are frequently conflated. Tag every fact with which product it belongs to before using it.

## 1A. TeamBuildr Strength (the classic S&C product)

The original TeamBuildr: a strength & conditioning **programming and athlete-management** platform. This is the "crown jewel" capability that OS inherits its programming depth from.

**What it is / does**
- `[PROVABLE]` Periodized, %-based strength & conditioning programming — genuine sport-performance training depth (best-in-class vs. CrossFit-native tools).
- `[PROVABLE]` Workout delivery & tracking features surfaced in the interviews: custom videos, dateless programs, questionnaires, RPE / autoregulation programming, exportable workout reports (e.g. for a 12-week reassessment), athlete journals for biofeedback.
- `[PROVABLE]` Has an **AMS** (Athlete Management System) with its own webhook infrastructure (SQS → `ams-integrations` lambdas → DynamoDB-TTL debounce). *This webhook layer belongs to Strength, NOT OS.*

**Commercial model**
- `[PROVABLE]` Strength **has pricing tiers**: Silver / Gold / Platinum / Platinum Pro. (This is the key contrast with OS, which has no tiers.)

**Where Strength shows up in the JTBD work**
- `[INTERNAL]` The heaviest Strength-specific demand came from Dr. Razor (FSP): natural-language → TeamBuildr programming, a data round-trip pain (export → analyze → manually re-type programs for 25–35 athletes/day), and an alerts/trigger system (pain reported → notify coach). Much of Razor's transcript (~60%) is Strength product-roadmap requests: recurring-session scheduling, per-category credit IDs, calendar color-coding, coaches' calendar/OOO, video download, native SMS/parent comms.

## 1B. TeamBuildr OS (the gym/facility management platform)

The newer product: gym/facility **operations** — booking, scheduling, billing, memberships, POS — that carries Strength's programming into a single member-facing app.

### Strengths (crown jewel first) — all `[PROVABLE]`
1. **Programming depth** — periodized, %-based S&C; genuine sport-performance fit (inherited from Strength). Best-in-class vs. CrossFit-native tools.
2. **One member app** — booking + scheduling + billing + workout tracking in a **single member-facing app** (OS + Strength combo). *This is the flagship differentiator.*
3. **Transparent single price** — **$200/mo or $2,000/yr** (~17% annual savings), **published**, no tiers, no feature-gating. OS + Strength bundle ≈ 20% off (varies by Strength tier).
4. **0% payment processing cut** — Stripe-native; our only revenue is the subscription ("we only make money if you stay happy").
5. **Facility ops** — scheduling, check-in, membership management (recurring + expiring credit packages, waitlists w/ auto-promotion, late-cancel charges, self-booking). Solid, but not category-leading. **Note: OS has NO access control.**
6. **Contracts** — month-to-month (cancel anytime) or annual.

### Gaps (know these so content doesn't over-claim) — `[INTERNAL]`
1. **Reporting is the headline gap** — no at-risk/churn report, no granular revenue reporting (revenue per membership/package, net-new MRR), no per-class/service attendance economics, no location-separated revenue.
2. **Multi-location** — reporting aggregates across the whole account, not per-location. (Live pain — see Orca/Taylor interview.)
3. **Integrations / automation** — Zapier shipped but **dead on arrival: 3 of 91 accounts use it, 6 zaps total**. The OS Workflow Builder pitch is the in-progress answer.
4. **Native AI** — a gap, but **actively being built/explored** (Workflow Builder's Claude layer). Frame competitor AI as "in progress," never a blind spot.
5. **Lead management + native marketing (email/campaigns/CRM)** — `[POSITIONING]` **deliberately out of scope.** Position as focus + integration, never as a missing feature.
6. **SSO** — exists, but a paid add-on for larger accounts. **Member-booked appointments** — was ~10 days from launch as of 2026-08-06 (treat as shipped/imminent; move from gap → strength once confirmed live).

### Provable positioning claims (safe for sales copy) — `[PROVABLE]` / `[POSITIONING]`
- **"One app for your members. Not two."** — Members use a single app for booking, scheduling, billing AND workout tracking. Competitors either deliver programming via a second app (MindBody/Glofox → Trainerize) or have none (Walla).
- **"We publish our price."** — $200/mo, published. *Only beats quote-only competitors (MindBody, Glofox, Exercise.com) — NOT Walla / PushPress / Wodify, who also publish.*
- **"0% cut of your processing."** — Stripe-native, we take no processing markup. Strong provable contrast vs. PushPress / Wodify (tiered processing markups).
- **Incentive-alignment line (fully provable):** *"We take zero cut of your payment processing. Our only revenue is your subscription — so we only make money if you stay happy."*
- **Wedge vs. CrossFit-native tools (PushPress, Wodify, SugarWOD):** programming **depth** (periodized, %-based S&C) + serious sport-performance fit — NOT "built by gym owners" (PushPress owns that ground) and NOT app-count.

### Guardrails — things sales content must NOT say — `[GUARDRAIL]`
- 🚫 **Never attack a competitor for being "two products / two invoices / an integration between them."** OS + Strength is itself two separate subscriptions on two invoices sharing one member app — that's a glass house. (The single **member app** claim is still fine; the billing is what's two.)
- 🚫 **Never claim we publish price against Walla / PushPress / Wodify** — they publish too.
- 🚫 **Never frame OS's lack of marketing/CRM as a gap** — it's a deliberate stance (focus + integration).
- 🚫 Don't state any competitor "(reported)" fact as confirmed — see the comparison spec.

---

# PART 2 — JOBS-TO-BE-DONE (JTBD)

**Important framing:** The dedicated JTBD interview program was run to validate the **OS Workflow Builder** pitch. So the *interview corpus* is OS-centric (with Strength surfacing inside it). There is **one confirmed canonical OS JTBD statement**; there is **no separate formal JTBD statement for Strength** — Strength's jobs appear inside the OS/Workflow-Builder interviews (esp. Dr. Razor).

## 2A. Canonical OS JTBD (confirmed by Trent 2026-08-06) — `[POSITIONING]`

**Buyer:** the S&C / sport-performance facility owner-coach.

**Functional job:**
> *"When I'm running my facility across a pile of disconnected tools — programming in one place, scheduling/billing/members in another — I want one platform that runs the operation AND delivers real, periodized S&C programming through a single member app, so I can run a legit, professional facility without stitching together a stack or becoming a software company."*

**Emotional job:** feel in control and credible — not duct-taping tools or apologizing for a clunky member experience.

**Social job:** look as buttoned-up to my athletes/members (and youth-sport-performance parents) as a big franchise does.

**The wedge OS uniquely gets hired for:** *consolidation + programming depth* — "be the hub, and be the one platform that actually does the training, not just the front desk."

**Hired over:**
- Front-desk tool + separate Trainerize
- Spreadsheets + calendars + booking tool
- A CrossFit-native tool with shallow programming

**NOT hired for:** a marketing/lead-gen engine, a multi-location HQ command center, or a maximal-feature Swiss-army platform.

## 2B. The two hardest, most load-bearing JTBD findings — `[INTERNAL]`

Both emerged unprompted across multiple interviews and drive the whole Workflow Builder thesis:

1. **A new login / learning curve = dead on arrival.** Owners fire any tool that isn't intuitive in the first few minutes. Hard requirement: the core loop must live *inside* OS with zero new auth. ("I can't handle another app. I don't wanna learn another thing." — Andrea)
2. **Consolidation is the wedge — NOT "automation."** Owners describe 4–6 disconnected surfaces and flatly refuse to add another. Lead with **"make OS the hub, not a spoke,"** not "Zapier for gyms." Corollary — automation appetite is *selective*: **"automate the busywork, keep the coaching"** (automate profile creation, roster sync, notifications, readiness intake; keep the human touch on sales/relationship comms).

## 2C. The interview corpus (4 interviews, Jul 2026) — `[INTERNAL]`

Recruited on the broad job (Moesta switch-interview method). Full drafts in `data/state/interviews/*.draft.md`.

### Interview 1 — Andrea, 410 Fitness (community/class gym, owner-operator)
- **Core job:** *"When a lead comes in for a free trial, I want to move them through to signup without ever dropping one, so I stop leaving money on the table — without adding another app, login, or surface."*
- **Sharpest pain:** dropped free-trial follow-ups = direct revenue leak ("that's money"). Lead-to-signup scattered across 6 surfaces (Strength, OS, custom display app, Kilo, Google Sheet, Google Calendar).
- **Automation signal:** `tried_and_stopped` — abandoned Zapier "almost immediately," dropped Mailchimp.
- **Archetype:** the **app-fatigued** owner. Firing criterion = any new login / learning curve. Cleanest signal of the four (dropped-lead pain was fully hers).
- **Go? Y.**

### Interview 2 — Miles, FSP (premium youth sports-performance, co-owner, ops side)
- **Core job:** *"When a new athlete signs up, I want their profile created once and propagated everywhere... and I want readiness data ahead of a session so I can adjust the program before they arrive instead of reprogramming on the fly."*
- **Pains:** (1) profile propagation — every new athlete hand-created across 4 systems (Strength, OS, Vald, Output); (2) readiness/biofeedback arrives ad hoc ~4 hrs pre-session (~5 min reprogramming). Explicitly does NOT want a CRM yet.
- **Automation signal:** guarded — "if it's not broke, don't fix it"; hiring bar = "an assistant, not a burden."
- **Caveat:** the biofeedback-on-booking idea was largely surfaced by the interviewer — discount as demand signal until volunteered.
- **Go? borderline (?).**

### Interview 3 — Dr. Razor (Razer), FSP (sports-science co-owner, programming engine)
- **Core job:** *"When I've decided what an athlete needs today, I want those changes to land in TeamBuildr without re-typing every movement/set/tempo by hand, so I can program for 25–35 athletes a day without the data round-trip eating my afternoon."*
- **Strongest demand artifact of all four:** he has **already hand-built** the "OS-as-hub + AI automation" layer the Builder envisions — Claude + per-athlete cloud files + custom agents — because TeamBuildr couldn't do it. Not "would you want this" but "I built a fragile version and would move it into OS tomorrow."
- **Killer ROI stat:** *"six hours a day for someone to coach 20 kids... all prior to starting the session"* (pre-session data round-trip).
- **Cleanest Builder demands:** (a) alert/trigger system (pain reported → notify coach + chiro — "the big one that's missing"); (b) natural-language → TeamBuildr programming (pull-API); (c) profile propagation.
- **Archetype:** the **power-user / capability-parity** buyer — NOT app-fatigued; his bar is matching his homegrown build. (~60% of transcript is Strength product-roadmap asks — bucket separately.)
- **Go? Y** (automation/alert/propagation slice specifically).

### Interview 4 — Taylor Evernden, Orca Performance (multi-location, 4→5–6 locations, active builder)
- **Core job:** *"When a lead finishes their testing session, I want the onboarding email sent and their pipeline card moved automatically — without waiting on my admin team — so a weekend signup isn't stuck until Monday and no one falls through the OS↔Gemini gap."*
- **Archetype:** mirror image of Andrea — **not app-fatigued at all** (builds his own Gemini/GoHighLevel + Claude workflows). His blocker is **pure time scarcity** (`not_tried`, "got a lot of projects on the go").
- **Strongest positioning quote of any interview:** he'd *forgotten Zapier exists* — *"there's so much talk with Claude and ChatGPT and Cowork and agents... you don't think of other options."* = the native-Claude-in-OS thesis, stated from the customer side. Pair with the 3-of-91 Zapier stat.
- **Keep three pains separate — only #1 is Builder scope:**
  1. **[Builder]** OS↔Gemini onboarding handoff (form → manual availability check → manual booking → manual onboarding email + card move). Real cost = admin dependency (Saturday session not onboarded until Monday). Rates the pain itself ~3/10.
  2. **[Product bug, his LOUDEST pain]** duplicate memberships — members exhaust credits, hit a generic "no credits → view pricing" popup, buy a 2nd identical membership (one had 7). Fix = block exact-duplicate memberships + reword the popup.
  3. **[Product roadmap]** multi-location consolidation — 6 locations × ~$150 USD ≈ ~$1,500 CAD/mo on bad FX; wants one umbrella + location toggle + tiered/location pricing.
- **Go? Y** (appointment → onboarding → card-move slice).

## 2D. What the corpus tells us about buyer archetypes — `[INTERNAL]`
Three distinct blockers to consolidation/automation, each needing a different message:
- **Fatigue** (Andrea) — fears any new login; sell "it's already inside OS, nothing new to learn."
- **Capability-parity** (Razer) — will only switch if it matches his homegrown build; sell depth + reliability.
- **Time-scarcity** (Taylor) — no fear, no skill gap, just no time; sell "we build it for you, native, zero setup."

---

# PART 3 — SEGMENTS & ICP — `[INTERNAL]` / `[POSITIONING]`

**ICP:** strength & conditioning facilities, sport-performance gyms, hybrid clinic-gyms. Serves — but is **not optimized for** — yoga / spa / general-wellness.

**Loses to** "sophisticated" operators: multi-location businesses, highly structured marketing funnels needing native CRM, or buyers who simply want lots of bells & whistles.

**Emerging segment — hybrid clinic-gyms** (`[INTERNAL]`): clinician-owned (DPT/chiro/exercise-physiologist) facilities combining PT/rehab with performance/gen-pop training. ~6% of OS demos and accelerating (~1.3/mo). Key insight: **they don't ask OS for EMR features — they arrive already running a clinical platform (Splose, ClinicSense, Cliniko, Aesthetic Record) and need the *bridge* between it and OS.** Anchor example: Baxter Pattison (neuro-rehab + performance, Newcastle AU) with 5 documented OS gaps (EMR integration, review-gated booking, no-show auto-suspension, insurance invoice fields, client self-book for 1:1s).

---

# PART 4 — THE ACTIVE GTM NARRATIVE (context, not sales copy) — `[INTERNAL]`

The JTBD work feeds one active pitch: the **OS Workflow Builder** — a Claude-powered, natural-language workflow/integration builder **native to OS** ("Claude as build-partner, not agent"), delivered via a net-new OS "Pro" tier. It replaces the dead-on-arrival Zapier integration (3/91 accounts). Positioning spine: **"make OS the hub, automate the busywork, keep the coaching — you don't have to become a software company to get software your way."** Detailed pitch, economics, and phasing live in project memory (`project_os_workflow_builder_pitch`). This is background for *why* the JTBD emphasis is where it is — not itself public sales copy yet.

---

## Provenance & freshness
- OS product profile & JTBD: `scout/os_grounding.md` (hand-curated, confirmed 2026-08-06).
- Positioning facts & competitor frame: `docs/os-competitor-comparison-spec.md` (2026-07-23).
- Interview corpus: `data/state/interviews/*.draft.md` (Jul 2026, 4 interviews).
- Demand validation: qualifying integration asks ≈ 14 (confirms the deck's "12"); Stripe & Mailchimp are native OS and excluded.
- **Stalest item to re-verify:** member-booked appointments launch status (was imminent 2026-08-06) and any pricing/promo before public use.
