# Mission Control — Pre-Dev-Check Input Brief

*Input for a `pre-dev-check` run. Shaping is complete (see companion `mission-control-spec.md` for the GTM case — deliberately excluded here). This doc's job is to state the technical shape and, above all, enumerate the **data-provenance assumptions** to verify against the real OS backend before dev handoff. Self-contained: assume the reading session has none of the prior conversation.*

**Primary thing to vet:** whether OS can actually source the metrics Mission Control assumes, **in the form a weekly/monthly review needs them** (historical snapshots + gym-wide aggregates), not just as live, current-state, date-range report views. Most of the "OS already has this" belief below is drawn from **Notion feature/marketing docs, not from code** — treat every such claim as an assumption to confirm in the mirror.

---

## What we're building (technical shape)

The existing OS **General Report page becomes "Mission Control"** — the first surface an owner looks at each morning/week. It does two things:

1. **Composes** metrics that today live spread across OS's existing reports (General Dashboard, Sales, Memberships, Payroll, Attendance) plus the in-flight *TB OS Business Reports* churn/at-risk data into a **single weekly + monthly scorecard**. The existing detailed reports remain, as drill-downs beneath it.
2. Layers a **Claude-generated weekly review** on top — a short narrative of "what moved, what to look at, who to call" — delivered on a cadence (surface + possibly an email/Slack push; delivery is an open design question).

"Same data, new front door + a narrator." We are **not** building a new reporting engine and **not** re-deriving metrics OS already computes — the premise is composition + interpretation over existing data. **That premise is exactly what needs verifying.**

---

## Suspected change-types (for the check to confirm / expand)

Flagged as hypotheses, not conclusions — the skill's Phase 1/2 should confirm against `analysis-lens.md` and the mirror:

- **Data coupling (primary).** Mission Control reads from every reporting subsystem at once + the new Business Reports tables. The bulk of the risk is here → see the ledger below.
- **Entry point.** A new composed surface, and (if the weekly review is pushed via email/Slack) a new outbound generation/delivery path.
- **State / lifecycle.** If a weekly review is *persisted* (a stored, timestamped review object owners can look back on), that's net-new state with its own lifecycle. Confirm whether reviews are ephemeral or stored.
- **Scale / cardinality.** A scorecard = gym-wide aggregates; the review = an LLM call **per gym, per week, across the whole customer base**. Confirm aggregate-query feasibility, batch timing, and cost/data-volume for large gyms.
- **Actor.** Likely no new *human* actor (owners already view reports). Confirm the AI review doesn't introduce a system-writer that trips permissions/audit assumptions.

---

## Data-provenance ledger — the core of this check

For each metric, verify against backend code: (a) does OS compute/store this today, (b) is it available as a **gym-wide aggregate**, (c) is it available **historically / as a point-in-time snapshot** (a review needs "end of last month" and week-over-week deltas), (d) what's the canonical definition. Confidence = how sure I am from the *docs*, which is not the same as from code.

### Believed OS-sourceable today — VERIFY THESE

| Metric | Assumed source (from Notion docs) | Confidence | Verify in code |
|---|---|---|---|
| New Members | General Dashboard "New Members" panel | Med | Count over arbitrary date range? Historical? "New" = new profile or new paid membership? |
| Active Members | Payroll/Memberships context metric | Low-Med | Canonical definition of "active" — consistent across reports? Point-in-time count? |
| Terminations / cancellations | Memberships (scheduled cancels) + incoming Churn Report | Low | Where do *completed* terminations live today vs. what Churn Report will add? |
| Freezes / holds | Memberships report | Low | Are holds queryable as a count over a period, historically? |
| # Sessions | Attendance / Payroll "classes run" | Med | Classes vs appointments both counted? Per-gym aggregate? |
| Client Visits | Attendance "Total Sign-Ins" (check-ins, not bookings) | Med | Sign-in data retained historically at gym-aggregate level? |
| People / Session | Derived: sign-ins ÷ sessions, or Payroll occupancy | Low | Computed anywhere today, or net-new derivation? |
| Gross Revenue | Sales report (paid transactions) | Med | "Gross" = paid only, or incl. pending? Excl. refunds? Historical monthly? |
| Avg Revenue / Member (ARM) | Derived: revenue ÷ active members | Low | Computed today or net-new? Which revenue + which member count? |
| Clients at month end | Snapshot of active count | Low | **Does OS retain point-in-time month-end state, or only live current?** (see Risk 1) |
| Attrition % (churn) | *In-flight* TB OS Business Reports Churn Report | Low | This is a **future** build, not shipped — confirm status + definition, don't assume it exists |
| Avg Lifetime Member Value (LTV) | — | **Very low** | Likely **not** computed natively anywhere. Assume net-new modeling until proven otherwise |

### Explicitly NOT OS-native — do NOT vet as native (Builder territory)

These are known-external and out of scope for OS-native sourcing; the plan routes them to the Workflow Builder (CRM / QuickBooks) later. Flag only if you find OS *does* have them:

- Funnel top: New Email Subscribers, New Leads, Lead Calls/Follow-ups, Completed Sales Conversations, LBOs/Trials Sold → live in CRM/email tools.
- Financials: Expense (Non-People / People / Savings / Taxes), Profit Before Owner's Pay, Owner Pay & Distributions → QuickBooks.

---

## The five provenance risks most likely to be the "forgot payroll" miss

1. **Point-in-time vs live.** A weekly/monthly review needs *historical snapshots* ("active members at end of last month," "attrition this month," week-over-week deltas). OS reports appear to be **live, current-state with date-range filters**. If the backend doesn't retain history, month-end snapshots and deltas may not be reconstructable — which quietly guts the "review" premise. **Verify snapshotting/historical retention first; it's load-bearing.**
2. **Gym-wide aggregate availability.** Is there an efficient path to gym-level aggregates, or would the scorecard require per-member iteration? Determines whether this is cheap composition or expensive net-new compute.
3. **Derived metrics may be net-new.** LTV, ARM, attrition, people/session — if OS doesn't calculate these today, "compose existing data" becomes "build new calculation logic," changing the effort estimate and the definition-ownership question.
4. **"Active member" definition drift.** Different reports may define active/attrition differently. One scorecard needs one canonical definition; reconciling them may surface disagreements. Verify a single source of truth exists.
5. **Billing dependency for revenue rows.** Revenue/ARM/LTV assume billing runs through OS (Stripe). Confirm how revenue is modeled and what a scorecard shows for gyms on external processors — null, hidden, or broken-empty.

### Bonus — the review layer's own data need
The Claude review's "who to call" actionability implies it needs **member-level at-risk detail**, not just aggregates (i.e., the incoming At-Risk-for-Churn report's row data). Confirm that member-level list is queryable and that surfacing it in an AI-generated summary doesn't cross a permissions/PII boundary the report UI currently gates.

---

## Context the check needs but should not re-open

- **TB OS Business Reports (Approved, Cycle 4; Shape: Teofe)** is an **in-flight** build adding Churn / Low-Credit / At-Risk reports and a *possible* customizable widget dashboard. Mission Control is intended to layer on / merge with it. For this check, treat its churn/at-risk data as **"will exist," not "exists"** — verify current status.
- **Out of scope for this check:** whether to build it (settled), and the widget-dashboard merge politics with Teofe (a product-org conversation, not a code question).
