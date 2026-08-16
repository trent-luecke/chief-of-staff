# Known couplings

### Pay rate assigned at schedule-item creation by the creating staff user
- **Depends on:** payroll assumes a pay rate exists on every schedule item
- **Held by:** schedule-item creation flow — the creating STAFF user sets the rate at creation (defaulted from `PayRate.isDefault` in the studio UI, persisted onto the `Schedule` template, then copied onto each `ScheduleItem`); `payRateId` is a nullable column with no server-side back-fill
- **Invalidated when:** actor change (member-initiated creation) OR entry-point change (self-serve booking) — a member has no rate-assignment step and nothing back-fills `payRateId` at creation, so it persists `null`. The failure is SILENT, not a hard error: at payroll-compute time the payout falls back `item.payRateId` → `teacher.payRate` → studio-level `defaultPayRate` → `$0`. So a member-booked appointment silently pays the teacher's default, the studio default, or nothing — none of which is a deliberately-assigned rate. Silent-wrong-pay is more dangerous than a loud null error because it surfaces in payroll, not at booking.
- **Code:** create side — `backend/app/modules/schedules/helpers/bulkWriteScheduleItems.ts:bulkWriteCreateScheduleItems` (copies `scheduleBulkFields` incl. `payRateId` onto each item); staff-gated entry points `backend/app/modules/schedules/routes/createOne.ts:action` and `backend/app/modules/bookings/routes/createOneAppointmentBooking.ts:action`; nullable field `backend/app/modules/schedules/item.mysqlModel.ts:ScheduleItem.payRateId`. Compute side (the silent fallback) — `backend/app/modules/reports/helpers/payroll/payrollGetPayouts.ts:154-163` (`let payRate = defaultPayRate; if (item.payRateId) … else if (teacher.payRate) …`).
- **Severity:** high
- **Discovered:** 2026-08-10 · seed scan (known production miss: member-booked appointments); compute-side fallback refined 2026-08-10 · analysis:backtest (member-booked-appointments)

### Book/purchase actor may be acting for a LINKED account, not themselves
- **Depends on:** any member-facing booking or purchasing flow implicitly assumes the actor transacts for their OWN account
- **Held by:** OS has first-class linked accounts — a parent account can book and purchase for linked child accounts without logging out and back in. So "the member" and "the account being booked/purchased for" are NOT the same thing.
- **Invalidated when:** actor change / entry-point change that lets a member self-initiate a booking or purchase — the flow MUST surface a "who are you booking/purchasing for?" profile selector (self or any linked account) and authorize the chosen target against the actor's linked set. Scoping the endpoint to "the caller's own `accountId` only" is WRONG: it silently breaks the core parent-books-for-child use case. (This directly corrects a mis-scoped suggestion the 2026-08-12 report made before the coupling was known.)
- **Code:** `backend/app/modules/linkedAccounts/mysqlModel.ts:LinkedAccounts` (junction `accountId` ↔ `linkedAccountId`); ready-made authz primitive `backend/app/modules/linkedAccounts/helpers/verifyLinkedAccounts.ts` (returns `{ linkedAccounts, isParentAccount }`; `isParentAccount = accountIds.every(id => linkedAccountIds.includes(id))`) and `getLinkedAccountsForAccountId.ts`; associations `backend/app/modules/accounts/mysqlModel.ts:107-108` (`parentAccount` / `childAccounts`). Booking creation stamps a single `accountId` (`backend/app/modules/bookings/routes/createOneAppointmentBooking.ts`).
- **Severity:** high
- **Discovered:** 2026-08-12 · analysis:member-booked-appointments (real-build miss reported by Trent; the report had missed it entirely). GENERALIZES: apply this lens to ANY feature that assumes an actor acts only on their own account (purchases, profile edits, waivers, notifications, data export).

### Appointment booking creation ↔ credit / payment decision
- **Depends on:** a booking for a priced appointment type resolves a credit/payment decision at creation (`useCredit`, pricingOption)
- **Held by:** the staff booking flow — the staff caller decides `useCredit` / pricing when booking on a member's behalf
- **Invalidated when:** actor/entry-point change (member self-booking) — no staff caller to make that decision; the member path must define credit-deduction / payment-collection / membership-included behavior explicitly, or members book priced sessions for free (or bookings fail)
- **Code:** `backend/app/modules/appointments/mysqlModel.ts:47` (`pricingOptions`); `backend/app/modules/bookings/constants.ts:47` + `backend/app/modules/bookings/mysqlModel.ts:68` (`creditId`, `useCredit`); booking loop `backend/app/modules/bookings/routes/createOneAppointmentBooking.ts`
- **Severity:** high
- **Discovered:** 2026-08-12 · analysis:member-booked-appointments (real coupling but was already on the team's roadmap — surface it as a confirm-we've-got-this, not a novel alarm)

### Appointment booking endpoint is staff-role gated (+ `ignoreConflict` staff override)
- **Depends on:** appointment creation authorizes the caller as studio staff, and trusts a staff-only `ignoreConflict` flag to bypass conflict checks
- **Held by:** `createOneAppointmentBooking.ts` — `Studio.assertFindByReq(req, [FRONT-DESK, ADMIN, OWNER, TEACHER])` (`:29-34`) plus a caller-is-teacher-or-admin check (`:63-71`); the booking loop passes `ignoreConflict` into `Booking.bookAppointment(...)`
- **Invalidated when:** actor change (member) — members hold no staff role, so the existing endpoint is unusable; a new member-scoped endpoint is required, and `ignoreConflict` must be forced `false` on it so self-serve can't override double-booking guards
- **Code:** `backend/app/modules/bookings/routes/createOneAppointmentBooking.ts:29-34,63-71` and the `ignoreConflict` arg to `Booking.bookAppointment` in the booking loop
- **Severity:** high
- **Discovered:** 2026-08-12 · analysis:member-booked-appointments

### Reports have NO point-in-time snapshots — stock metrics are not historically reconstructable
- **Depends on:** any weekly/monthly *review* assumes it can read "active members at end of last month," month-end client count, MRR/ARM as-of-a-date, and month-over-month stock deltas
- **Held by:** the reporting subsystem is entirely live queries over event tables filtered by a date range (`reports/helpers/dateRange.ts` = `field BETWEEN gte AND lte`). Flow metrics (New Members `Account.createdAt`, Revenue `Sale.invoiceDate`, Sign-Ins `Booking.startDate`) reconstruct for any past window because the event timestamp is immutable, and `prevDateRange.ts` already yields a prior-period delta. But **stock/point-in-time metrics are computed from CURRENT state only** — active-member counts come from live list filters (`accounts/readMany.ts` `isActive=1`), ARM from currently-active contracts (`contracts/readMany.ts` `endDate>now`). Grep confirms **zero** snapshot/`asOf`/month-end tables in the codebase.
- **Invalidated when:** state/lifecycle change — a review that quotes month-end stock or MoM stock deltas. There is no way to answer "active members on July 31" after the fact. Mission Control must either start writing its own periodic snapshots going forward (net-new state + lifecycle; no back-fill for history before it starts) or restrict point-in-time rows to event-timestamped flow metrics.
- **Code:** `backend/app/modules/reports/helpers/dateRange.ts`, `prevDateRange.ts`; stock sources `accounts/routes/readMany.ts:273-320`, `contracts/routes/readMany.ts:220-259`
- **Severity:** high
- **Discovered:** 2026-08-12 · analysis:mission-control

### "Active member" has no single canonical definition; the overview report has none at all
- **Depends on:** a single scorecard assumes one authoritative "active members" number
- **Held by:** OS has ≥3 divergent definitions and none live in `reports/`: `ACTIVE_MEMBERS` = `account.isActive=1`; `ACTIVE_MEMBERSHIPS` = `isActive=1` + a required active contract (`accounts/routes/readMany.ts:273-320`); `contracts/routes/readMany.ts` "active" = contract with `!endDate || endDate>param`. `reports/helpers/members/membersGetSummary.ts` returns only NEW-account counts, not an active count.
- **Invalidated when:** data coupling — composing one "active members" row forces a canonical choice that will disagree with numbers owners already see on other OS screens. Definition-ownership must be assigned before build.
- **Code:** `accounts/routes/readMany.ts:273-320`, `contracts/routes/readMany.ts:220-259`, `accounts/abstractions/MembershipStatusOptions.ts`
- **Severity:** high
- **Discovered:** 2026-08-12 · analysis:mission-control

### Derived business metrics (LTV, attrition, people/session, collected-revenue ARM) do not exist in code
- **Depends on:** "compose metrics OS already computes" assumes LTV / attrition / ARM / people-per-session are computed today
- **Held by:** grep finds **zero** churn/attrition/retention/LTV code in the backend. "# Sessions" (classes/appointments run) is counted nowhere in `reports/`. The only ARM-like calc (`contracts/readMany.ts:230-250` `averageValue`) is over *contracted MRR* with a hardcoded `WEEKS_IN_A_MONTH = 4.3` fudge (not collected revenue), and its own code comment concedes owners complain the number is off.
- **Invalidated when:** data coupling — "compose existing data" silently becomes "build + own the definition of 4 net-new metrics," moving both the effort estimate and the definition-ownership question.
- **Code:** absent by design; nearest artifact `contracts/routes/readMany.ts:230-250`
- **Severity:** high
- **Discovered:** 2026-08-12 · analysis:mission-control

### Gross Revenue is a filtered internal-ledger sum (matchSucceededSale + isBlossom), not raw Stripe
- **Depends on:** a revenue row assumes a clean, processor-agnostic gross number
- **Held by:** revenue = `SUM(Sale.total)` where `origin ∈ {contract,retail,invoice}` AND `transactionStatus ∈ {succeeded,refund,paid}` AND `isBlossom:false` (`reports/constants.ts:matchSucceededSale`, `salesGetData.ts`). `Sale` is OS's internal ledger with a `paymentProvider` field (Stripe is one of several) populated by contract-billing crons / retail / upgrades — so revenue needs OS to have *recorded* the sale, not Stripe specifically. Refund-status rows are included in the SUM.
- **Invalidated when:** data coupling — (a) Mission Control must replicate this exact filter or its revenue won't tie to the Sales report owners already see; (b) refund inclusion makes gross-vs-net ambiguous (depends on sign of refund `total`); (c) gyms billing entirely outside OS have no `Sale` rows → revenue/ARM/LTV render empty, not $0.
- **Code:** `backend/app/modules/reports/constants.ts` (`matchSucceededSale`), `reports/helpers/sales/salesGetData.ts`, `sales/mysqlModel.ts` (`paymentProvider`, `isBlossom`), `crons/routes/contractCrons.ts:184`
- **Severity:** med
- **Discovered:** 2026-08-12 · analysis:mission-control

### Terminations & freezes are mutable current-state, not an immutable event log
- **Depends on:** "terminations this month" / "freezes this month" assume a stable, timestamped event to count
- **Held by:** termination lives on `Contract.endDate` + `isCanceled`/`hasEnded` flags — **no `canceledAt` timestamp, no churn/termination event table**. Freezes live on `pauses.pauseStartDate/pauseEndDate` (and `contractsPauses`), editable/deletable. Both are queryable by their date fields but scheduled cancels are future-dated and cancels/pauses are reversible.
- **Invalidated when:** state/lifecycle — a historical review figure recomputed later can change (a cancel entered after the fact, or reversed). Fine for a live glance, shaky as an audit-grade monthly number.
- **Code:** `backend/app/modules/contracts/mysqlModel.ts` (`endDate,isCanceled,hasEnded,cancelReason`), `pauses/mysqlModel.ts`, `contractsPauses/mysqlModel.ts`
- **Severity:** med
- **Discovered:** 2026-08-12 · analysis:mission-control

### Report endpoints are single-studio; no cross-customer aggregate exists
- **Depends on:** a per-gym-per-week review across the whole customer base assumes a batch/aggregate read path
- **Held by:** every report route is scoped by the `blsm-studio-id` header via `Studio.assertFindByReq` and gated `[OWNER, ADMIN]` (overview/graphs). There is no all-studios endpoint. The one system-integration precedent is `reports/routes/teambuildr/quickStats.ts` (`apiKeyAuth:true` + `assertFindByReq(req, [])`).
- **Invalidated when:** scale/cardinality + actor — Mission Control's batch runs as a TeamBuildr system/superadmin actor calling the studio-scoped endpoints N times (per-call queries are cheap single COUNT/SUM, DB-side; cost is N × (queries + one Claude call)). Confirm the system actor is authorized to read owner-gated data and that per-gym member-level "who to call" detail surfaced in an AI summary (and any email/Slack push) doesn't cross the PII boundary the owner-gated report UI currently holds.
- **Code:** `reports/routes/getOverview.ts:27-30`, `reports/routes/teambuildr/quickStats.ts:14,47-48`
- **Severity:** med
- **Discovered:** 2026-08-12 · analysis:mission-control
