# Mission Control — Feature Shaping Spec

*Shaped via `os-feature-shaping`, 2026-08-12. Evidence Brief + decision doc. Revised after pulling the live TB OS Business Reports spec + existing OS reporting docs.*

---

## ⚠️ Read this first — the direction correction

Pulling the internal reporting docs materially reframed this feature. Two facts changed the pitch:

1. **OS reporting is already extensive.** OS ships a **General Dashboard** (Revenue, Revenue-per-category, Attendance, New Members) **plus five reports** — Sales, Memberships (incl. forward-looking MRR projections), Payroll, Attendance — all CSV-exportable. There's even a static "Monthly Business Review" how-to telling owners to click through all five. **Most of the "OS can auto-fill it" half of the Mission Control sheet already exists in a report today.**
2. **TB OS Business Reports (Approved, Cycle 4 — Shape: Teofe, FE: Josh, BE: Nick, Design: Jasmine) is filling the last gap** — a Churn Report, a Low/Expired Credit Report, and an At-Risk-for-Churn report. It even floats a *nice-to-have* "widget-type customizable General dashboard." Crucially, it draws an explicit boundary: **"Not advising on direct action of any metric."**

**Consequence:** the weakest version of Mission Control is now "centralize / auto-fill the data" — OS largely does this already and Cycle 4 finishes it. Pitched that way, it gets waved off. **The strong version is the layer Business Reports deliberately declined to build:** composition into one scorecard + a **Claude-run weekly review** (interpretation, "what moved & what to do," cadence). That's cheaper (data exists), politically clean (it's the north-star for Teofe's widget nice-to-have, not a competing build), and owns the one thing no competitor or internal project claims.

**One overlap to manage, not ignore:** the Business Reports "widget-dashboard" nice-to-have overlaps Mission Control's "compose into one view." Fold it into the Mission Control vision *with Teofe* rather than let two half-versions ship. Trent is already a commenter on that doc — the opening exists.

---

## Evidence Brief

The research reframes this feature rather than cleanly endorsing it.

**The original pitch — "gym owners are flying blind and want a business command center" — is the weakest-supported version.** Customer voice for it is thin: across the Avoma sales-call analyses, *zero* prospects said "flying blind" or "I want it all in one place" unprompted; nearly every "reporting" mention was a rep *demoing* the Reports tab. Competitively, a dashboard is **table stakes, not a wedge** — Mindbody (Analytics 2.0 + peer-benchmarking beta), PushPress, Wodify, and Kilo all ship one. And internally, OS already has the reports + a Cycle-4 build finishing the churn/at-risk gap.

**What makes a *different, stronger* version real:**

1. **The demand exists as a workaround.** The Workflow Builder's most-requested Phase-2 template is owners piping OS data *out* to Google Sheets to hand-build a scorecard. They're building Mission Control by hand because there's no native composed view.
2. **The interpretation layer is unclaimed — by everyone.** No competitor markets an AI that reads your metrics and tells you what to do; and Business Reports explicitly puts *"advising on direct action"* out of scope. That's the seam.
3. **The ritual is what made the original work.** Trent's FitLab Mission Control survived because a paid mentor ran a standing weekly meeting off it — the discipline lived in the cadence + analysis, not the sheet. That's what OS's five-tabs-and-a-how-to-doc conspicuously lacks.

**Honest weakness:** the case rests on *internal conviction + a proven workaround + narrow feature-level asks* (Derrell Levy — *"see how different revenue sources stack up"*; Andrea's churn-chart confusion; PitFit; Boston SP) — not a loud unprompted chorus. And the strong unprompted consolidation signal (Warren, Jamie Tellier, Ryan Pace, Thomas Howes) is **operational consolidation** ("one login"), which OS already sells — *not* analytics demand. Don't conflate them; a skeptic will catch it.

**Net:** don't pitch a dashboard, and don't pitch data-centralization. Pitch the **weekly business review** — composed from reports OS already has, interpreted by Claude, delivered on a cadence — as the layer on top of Business Reports.

---

## Mission Control

*The weekly business review your gym never had a coach to run — composed from the reports OS already has, interpreted by Claude, delivered on a cadence.*

**The situation**
OS already gives owners the data — a General Dashboard and five reports. What it doesn't give them is the *habit*, or the *interpretation*. There's a static doc telling owners to run their own monthly review across five tabs; almost none do, because raw numbers across five tabs isn't a review — it's homework. The proof that owners want a composed scorecard is behavioral: OS's single most-requested upcoming automation is owners exporting data *out* to Google Sheets to build one by hand. Business Reports (Cycle 4) is finishing the churn/at-risk data — but by its own scope, it stops at showing the numbers and explicitly won't advise on action.

**The ask**
Build Mission Control as the one surface that (a) **composes** OS's existing reports + the new Business Reports churn/at-risk data into a single weekly/monthly scorecard, and (b) layers a **Claude-run review** on top — "here's what moved, here's what to look at, here's who to call" — on a weekly cadence. Reserve the columns OS genuinely can't see (leads/trials/conversion, full P&L) for the Workflow Builder to fill via CRM and QuickBooks. It's the "seeing + sense-making" layer; the Builder is the "connecting" layer.

**Why this, why now**
- **The workaround is the demand.** The Builder's top Phase-2 templates are "pipe OS data into my spreadsheet" — owners are building this by hand today.
- **The data + primitive already exist.** OS ships 5 reports; Business Reports (Cycle 4, Teofe) finishes churn/at-risk. Mission Control composes + interprets what's already there — a Medium build on top, not a reporting engine from scratch.
- **The wedge is explicitly unclaimed.** Every competitor ships dashboards; none markets an AI that interprets and recommends. Business Reports *by its own scope* won't ("not advising on direct action"). Mindbody's Analytics 2.0 + benchmarking beta shows the category moving — the AI-review differentiator won't sit unclaimed forever.
- **Clear ICP with an existing voice.** Reporting asks cluster in multi-revenue-stream performance/PT operators (In-Tech's Derrell Levy, PitFit, Boston SP, Andrea) — the operator-minded segment most likely to adopt *and* pay.
- **It's the front door to the Builder.** Every empty row (leads, conversion, expenses) is a concrete reason the owner *wants* the paid integrations — Mission Control manufactures Builder demand.

**Design principles**
- **The review layer is the product, not polish.** The Claude "what moved / what to do" cadence is the wedge *and* the retention mechanic — it recreates the mentor's standing meeting. If we ship only a composed dashboard, we've shipped a sixth tab nobody opens.
- **Compose, don't rebuild.** Sit on top of the existing reports + Business Reports data. Do not fork a second reporting stack.
- **Zero-integration value on day one.** The member-ops + revenue scorecard populates from data OS already has. Never ship the empty-manual-entry graveyard version.
- **Degrade gracefully on data OS can't see.** Leads/conversion/P&L rows show a clear "connect to fill this" state (→ Builder), never broken empty financials.

**What good looks like in 90 days**
- **Primary bar: ≥40% of activated gyms viewed Mission Control in the last 7 days at week 12.** A weekly-active ratio, not an activation count — proves the ritual stuck.
- **Ritual signal:** ≥X% of active gyms opened/expanded a weekly Claude review (proves the *review*, not just the page, is what they return for). This is the metric that separates Mission Control from the five report tabs.
- **Builder pull-through:** N gyms connect a CRM or QuickBooks source specifically to fill Mission Control's empty rows.

**What we're not doing**
- Not building a reporting engine or re-deriving metrics OS already reports.
- Not making manual entry the primary path.
- Not marketing dashboards as a differentiator — that's parity; the AI review is the story.
- Not natively populating front-of-funnel (leads/trials) or P&L this release — those wait for the Builder.
- Not shipping a static composed dashboard *without* the review layer — that's the failure mode.

**Open questions**
- **Merge or layer with Business Reports' widget-dashboard nice-to-have?** Business Reports (Cycle 4) already floats a customizable widget General dashboard. Mission Control's compose-into-one-view overlaps it. The call — and it's a Teofe conversation — is whether Mission Control *becomes* the vision for that nice-to-have (recommended) or layers above it. Resolve before this goes to dev to avoid two half-built dashboards.
- **What % of the base bills through OS (Stripe)?** Determines whether the revenue block is live day one.
- **Where does the weekly review live — in-app, an email/Slack push, or both?** The nudge *is* the ritual; delivery is a design decision, not a detail.
- **Is the AI review the free retention hook that sells the Builder's Pro tier, or gated into Pro itself?** Strong strategic fork — the review may be worth more as the free thing that makes owners crave the paid integrations.

---

## Appendix — source scan summary

| Source | Verdict |
|--------|---------|
| **Avoma calls** | Strategic "flying blind" pain effectively absent unprompted; real asks are narrow "better Reports tab" from ~4 multi-stream operators; nice-to-have, zero deals lost over it. Operational-consolidation signal is strong but ≠ analytics demand. |
| **Pipeline cache** | Fresh (1 day old) but status-only ledger — 25 leads, no notes/rep fields; structurally can't confirm or deny the thesis. |
| **Competitors** | Catching up, not leading — Mindbody/PushPress/Wodify/Kilo/ClubOS all ship dashboards. The AI weekly-review layer is the only undefended wedge. Mindbody Analytics 2.0 + peer benchmarking (beta) is the move to watch. |
| **Internal (initial)** | Mission Control net-new (never scoped). Builder's Phase-2 crowd-pleaser = exporting OS data to Sheets. Source sheet = EOS/Traction "Weekly Mission Control Meeting" scorecard; rows trisect into OS-owned / CRM-fed / QuickBooks-fed. |
| **Internal (Business Reports pull)** | OS already ships General Dashboard + 5 reports (Sales/Memberships/Payroll/Attendance) w/ CSV + MRR projections. **TB OS Business Reports = Approved, Cycle 4, Teofe/Josh/Nick/Jasmine**: adds Churn / Low-Credit / At-Risk reports; nice-to-have widget dashboard; explicitly **"not advising on direct action of any metric."** → auto-fill value is largely solved; Mission Control's net-new value = **compose + interpret + cadence**. |
