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

### "Attendance" and "sign-in" both derive from a staff-set `booking.isSignedIn` flag
- **Depends on:** any attendance / engagement / churn metric assumes `booking.isSignedIn` reflects whether the member actually showed up
- **Held by:** `isSignedIn` is a boolean on `Booking` toggled ONLY by a staff route (`bookings/routes/signIn.ts`, gated `OWNER/ADMIN/FRONT-DESK/TEACHER`). The canonical reports define `attended = status===booked && isSignedIn` and `noShow = booked && !isSignedIn && past` (`reports/helpers/bookings/bookingsGetAttendance.ts:66-82`, mirrored in `members/membersGetAttendance.ts`). There is no member self-check-in and no door/access-control feed into this flag.
- **Invalidated when:** data coupling — a new consumer treats `isSignedIn` as ground-truth attendance. At any studio that does not rigorously check members in, `isSignedIn` is false for attendees, so attendance reads as zero for the whole roster. A churn/at-risk report keyed on this silently flags everyone at low-check-in-discipline studios.
- **Code:** `backend/app/modules/bookings/routes/signIn.ts:37-44` (staff gate), `backend/app/modules/bookings/mysqlModel.ts:71,128-135` (`isSignedIn`, `setSignInStatus`), `backend/app/modules/reports/helpers/bookings/bookingsGetAttendance.ts:66-82` (attended/noShow definition)
- **Severity:** high
- **Discovered:** 2026-08-17 · analysis:at-risk-report

### Report date boundaries must be computed in `studio.timeZone`, not server/UTC time
- **Depends on:** any report with calendar-boundary semantics (last full week Mon–Sun, last full calendar month, "as of Sunday evening") assumes boundaries are in the studio's local time
- **Held by:** TWO date-range paths exist. Timezone-AWARE: `queryGetDateRange(start, end, studio.timeZone)` / `zonedTimeToUtc` — used by `members/membersGetAttendance.ts:29-32`, `reports/routes/payroll/*`, `reports/routes/teambuildr/quickStats.ts:19-20`. Timezone-NAIVE: `reports/helpers/dateRange.ts:getDateRange` does a raw `startDate >= gte AND <= lte` on the UTC column, and `bookingsGetAttendance.ts` uses `startOfDay(new Date())` = server time. The contract-renewal cron also runs on `startOfDay(new Date())` server time (`crons/routes/contractCrons.ts`).
- **Invalidated when:** data coupling / entry-point — a new report or snapshot cron picks the naive path. Studios not in server-UTC get shifted week/month boundaries; a globally-timed "Sunday evening" snapshot fires at the wrong local moment and clips the just-closed week.
- **Code:** aware — `@core/utils queryGetDateRange`, `date-fns-tz zonedTimeToUtc`; naive — `backend/app/modules/reports/helpers/dateRange.ts:getDateRange`, `bookingsGetAttendance.ts:52,80`; studio tz — `studios/mysqlModel.ts:150,1164` (`timeZone`)
- **Severity:** high
- **Discovered:** 2026-08-17 · analysis:at-risk-report

### "Package" is not an entity — it's a `PricingOption.type`-tagged bundle of `Credit` rows; memberships also mint Credits
- **Depends on:** package-only logic (low-credit, expiring-package, no-active-package) assumes it can identify "a package" and its credit balance/expiry
- **Held by:** there is no Package model. A purchase mints `Credit` rows (`credits/mysqlModel.ts` createFromSale) whose source type is `pricingOption.type` — `MEMBERSHIP` vs `CATEGORIES`/`APPOINTMENTS`/`HYBRID` (`credits/mysqlModel.ts:180-188`). Memberships ALSO mint Credit rows (type `MEMBERSHIP`), refreshed every cycle by the contract-renewal cron. Balance is not a stored field: it's Σ(`amount` − `used`) over non-deleted, non-expired credits whose contract isn't paused/canceled (`credits/mysqlModel.ts:316` uses `used < amount`; contract-pause check at `:454-485`). A member can hold several bundles with different expiries.
- **Invalidated when:** data coupling — a churn report queries credit balance/expiry without filtering `pricingOption.type != MEMBERSHIP`, so it fires package alerts on membership members near cycle-end; or treats "a package" as one balance/expiry when a member holds multiple bundles.
- **Code:** `backend/app/modules/credits/mysqlModel.ts:180-188` (type discriminator), `:316` (remaining filter), `:454-485` (contract active check); `pricing/mysqlModel.ts` (`PricingOptionTypesENUM`); renewal via `crons/routes/contractCrons.ts` + `sales/helpers/handleSaleOnSuccess.ts`
- **Severity:** high
- **Discovered:** 2026-08-17 · analysis:at-risk-report

### "Cancellation" is overloaded — booking-status cancel vs `contract.isCanceled`, and studio-initiated cascades
- **Depends on:** a "cancellations in last 28 days" churn signal assumes cancellations mean member-initiated disengagement
- **Held by:** booking cancels live on `booking.status ∈ {canceled(3), late-cancel(4)}` (`core/config/common.ts:213-231`); membership cancel is a separate `contract.isCanceled` boolean. Studio/class-level cancellations CASCADE to members' bookings, flipping them to CANCELED / LATE-CANCEL in bulk (`bookings/helpers/cancelAllBookingsByTimeFrameForAccount.ts:68-102`, `workshops/routes/deleteOne.ts:86`, `sales/mysqlModel.ts:475`) — these are not member disengagement. The canonical attendance report already counts `canceled = canceled || late-cancel` (`bookingsGetAttendance.ts:73-77`).
- **Invalidated when:** data coupling — the report counts raw booking-status cancellations without excluding studio-initiated cascades or deciding on late-cancel, inflating the churn signal with gym-caused cancellations.
- **Code:** `backend/core/config/common.ts:213-231` (status enum), `backend/app/modules/bookings/helpers/cancelAllBookingsByTimeFrameForAccount.ts:68-102`, `backend/app/modules/reports/helpers/bookings/bookingsGetAttendance.ts:73-77`, `contracts/mysqlModel.ts` (`isCanceled`)
- **Severity:** med
- **Discovered:** 2026-08-17 · analysis:at-risk-report
