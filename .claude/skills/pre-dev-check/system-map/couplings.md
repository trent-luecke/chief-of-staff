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
