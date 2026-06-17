# $1M ARR Analysis — Handoff Context
**Date:** June 6, 2026  
**Source:** Chief-of-staff repo GTM metric investigation  
**Purpose:** Context for adding a $1M ARR timeline + tracking section to the OS Demo sync hosted dashboard

---

## Company Snapshot

- **Product:** TeamBuildr OS — B2B SaaS for strength & conditioning coaches
- **Current MRR:** ~$15,000
- **Current ARR:** ~$180,000
- **Estimated customer count:** ~75 (at $200/mo avg plan)

---

## GTM Inputs (Actuals)

| Metric | Actual | Monthly Target |
|---|---|---|
| New closes/month | **5** | 15 |
| Average deal ACV | **$200/mo** ($2,400/yr) | — |
| Monthly cancellations | **1.5/mo avg** (18 total Jul '25–Jun '26) | ≤2 |
| Avg plan value per churned account | **~$163/mo** | — |
| Monthly churn MRR | **~$244** | — |
| Monthly churn rate | **1.63%** | — |
| Annual churn rate | **17.9%** | — |
| Net new MRR/month | **$756** | — |

**Monthly funnel targets (from config):** 20 leads → 30 demos → 15 closes  
**Pipeline state (as of June 5, 2026):** 12 deals total — 4 late-stage (3 In-Trial, 1 No Trial/Post Demo), 1 Demo Scheduled, 5 cold/stale, 2 On-Hold  
**Leads MTD:** 0 (KPI sheet tab exists but no entries populated yet)

---

## Current Trajectory Math

The SaaS MRR model: `MRR ceiling = new_MRR_per_month / monthly_churn_rate`

At current pace:
- New MRR/month: $1,000 (5 × $200)
- Monthly churn rate: 1.63%
- **MRR ceiling: $61,350 → ARR ceiling: $736K**
- **$1M ARR is not achievable at 5 closes/month — ceiling is below target regardless of time**

Minimum close rate to make $1M ARR theoretically reachable (at 1.63% churn): **6.8 closes/month** (i.e., 7+ is the floor)

---

## Scenario Table

All scenarios start from $15K MRR, use the exponential SaaS growth model.

| Scenario | Closes/mo | ACV | Churn/mo | ARR Ceiling | **Months to $1M ARR** |
|---|---|---|---|---|---|
| Current pace | 5 | $200 | 1.63% | $736K | **Never** |
| 10 closes, same churn | 10 | $200 | 1.63% | $1.5M | 61 mo (5.1 yrs) |
| **15 closes (target), same churn** | **15** | **$200** | **1.63%** | **$2.2M** | **32 mo (2.7 yrs)** |
| 15 closes + fix churn to 1%/mo | 15 | $200 | 1.00% | $3.6M | 27 mo (2.2 yrs) |
| 10 closes + fix churn to 1%/mo | 10 | $200 | 1.00% | $2.4M | 46 mo (3.8 yrs) |
| 15 closes + $250 ACV, same churn | 15 | $250 | 1.63% | $2.8M | 23 mo (1.9 yrs) |
| 15 closes + $250 ACV + fix churn | 15 | $250 | 1.00% | $4.5M | 21 mo (1.8 yrs) |
| 20 closes + $250 ACV + fix churn | 20 | $250 | 1.00% | $6.0M | **15 mo (1.2 yrs)** |

**Most achievable near-term path:** Hit the 15 closes/month target at current churn → $1M ARR in ~32 months from today (February 2029).

---

## Lever Ranking

1. **Close rate (5 → 15/month)** — primary constraint. This is 3x current volume. Requires top-of-funnel to actually feed through (leads, demos). At current churn, hitting the close target alone gets you there in 2.7 years.

2. **Churn (1.63% → 1.0%/month)** — secondary accelerant. Reducing churn from 1.63% to 1.0% on top of 15 closes saves ~5 months. Fixing churn without fixing closes doesn't work — you'd need 13.5 years at 5 closes/month even with 1% churn.

3. **ACV ($200 → $250/month)** — worth pursuing. A 25% ACV increase on top of 15 closes shaves another ~9 months vs. the base case.

---

## Flags & Blockers

### Data gaps (operational)
- **Leads tab is empty** — the KPI sheet has the tab but no data. No leads are being tracked in June. This means lead-count metrics in any dashboard will show 0 until someone starts logging entries.
- **No demos or sales tabs** in the KPI sheet yet — those collectors are built in code but the Google Sheet tabs don't exist. Sales MTD and demos MTD are unavailable programmatically.
- **Onboarding cache** — not yet confirmed current. Onboarding coverage metric depends on `data/onboarding_cache.json` being synced.
- **June cancellation dated 6/24** — one entry in the MONTHLY Cancellations sheet is dated June 24, 2026 (future). Data quality issue; may have been entered early.

### Business flags
- **3 late-stage deals went 10–16 days without contact** (David Arcemant, Mike Brown/SAPT, Asher Wojciechowski — last contacted May 21–27). These are the nearest-term revenue.
- **Churn reasons 2025:** App complaints = 38%, competitor switching = 23%, business changes = 31%. The ~61% that is fixable maps to product/support issues — flagged for escalation.
- **Close rate gap is severe** — 5 actual vs. 15 target is 33% attainment. The pipeline does not have enough volume to close 15/month even if conversion were perfect.

---

## What To Build in the Dashboard

Suggested additions to the hosted dashboard:

1. **$1M ARR Progress Bar** — current ARR vs. $1M target, with % complete
2. **Current trajectory line** — projected MRR over time at current pace (showing the ceiling)
3. **Target scenario line** — projected MRR at 15 closes/month, current churn (shows Feb 2029 intercept)
4. **Monthly close rate tracker** — actual closes/month vs. 15 target, trailing 3-month avg
5. **Net MRR waterfall** — new MRR added vs. churn MRR lost, month-over-month
6. **Churn rate trend** — monthly churn rate % over time (watch for movement above/below 1.63%)
7. **Time-to-$1M estimate** — live calculation updated monthly as actuals come in

The underlying formula for time-to-target estimate:  
`t = ln((target_mrr - ceiling) / (current_mrr - ceiling)) / ln(1 - churn_rate)`  
where `ceiling = monthly_new_mrr / churn_rate`

**Key inputs the dashboard needs refreshed monthly:**
- Current MRR (manual entry or pulled from billing)
- Closes MTD (from KPI sheet once Sales tab exists)
- Cancellations MTD (already wired via MONTHLY Cancellations sheet)
