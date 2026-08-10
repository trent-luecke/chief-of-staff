# Subsystem: Scheduling ↔ Payroll

Seeded from the OS backend mirror (`~/dev/gymstudio/backend`, TypeScript/Express/Sequelize) and the staff UI (`~/dev/gymstudio/admin-frontend`). All paths below are mirror-relative. Describes structure only — no secrets or data.

## The model

A studio's calendar is built from three Sequelize models:

- **`Schedule`** — the recurring *template* for a lesson or appointment (`backend/app/modules/schedules/mysqlModel.ts`). Carries the shared config for every occurrence, including `payRateId` and `noPayout`. `type` is `lesson` or `appointment` (`ScheduleTypesENUM`).
- **`ScheduleItem`** — a single dated *occurrence* generated from a `Schedule` (`backend/app/modules/schedules/item.mysqlModel.ts`). This is the payroll-bearing row. Relevant fields:
  - `payRateId: ForeignKey<number> | null` — **nullable**, `references: { model: 'payrates' }` (item.mysqlModel.ts:54, 461-467).
  - `noPayout: boolean` — explicit "this occurrence pays nothing" flag.
  - `appointmentId: ForeignKey<number> | null`, `lessonId`, `workshopId` — what kind of thing this occurrence is.
- **`PayRate`** — the rate definition (`backend/app/modules/payroll/mysqlModel.ts`, table `payrates`): `flatAmount`, optional `enableBonusAfterBookings` / `bonusAmountPerBooking`, and an `isDefault` flag (only one default per studio, enforced by the `afterSave` hook `setOtherPayRatesForStudioAsNonDefault`). `PayRate.totalAmount(bookings)` computes what a teacher earns for an occurrence.

Teachers are linked to a `ScheduleItem` through the `schedule_items_accounts` junction (`backend/core/database/mysql/junctionTables/scheduleItemsAccounts.ts`, `isSubstitute` flag). The pay rate itself is **not** per-teacher on the occurrence — it is a single `payRateId` on the `ScheduleItem` row.

There is also an unused-by-this-flow `accounts.defaultPayRateId` column (migration `20220831193016-accounts-default-pay-rate-foreign-key-addition.js`) — a per-teacher default. The creation path does **not** read it; see below.

## Where / how / by whom the pay rate is assigned

The rate reaches a `ScheduleItem` in one deterministic path, driven entirely by a **staff user at creation time**:

1. **Staff picks the rate in the studio UI.** In `admin-frontend/app/containers/SchedulePage/ScheduleAppointmentForm.tsx` (and `ScheduleClassForm.tsx`), the form pre-selects the studio default rate via `find(payRates, { isDefault: true })` and lets staff override it. On submit it maps the chosen option to `values.payRateId` (ScheduleAppointmentForm.tsx:389-396); if "no payout" is toggled, `payRateId` is cleared. **A member has no access to this form.**
2. **Backend validates it as an optional field.** `backend/app/modules/schedules/helpers/validateSchedule.ts` and `backend/app/modules/bookings/helpers/validateAppointmentBooking.ts` both declare `payRateId: Joi.validateInteger(clearable)` — optional, no default, no server-side fallback.
3. **Staff-only route persists it onto the `Schedule` template.** `backend/app/modules/schedules/routes/createOne.ts:action` calls `Studio.assertFindByReq(req, [OWNER, ADMIN, FRONT-DESK])` then `Schedule.create({ studioId, ...req.body })`, writing `payRateId` onto the template. The appointment-booking variant `backend/app/modules/bookings/routes/createOneAppointmentBooking.ts:action` gates on `[FRONT-DESK, ADMIN, OWNER, TEACHER]` and does the same `Schedule.create`.
4. **It is copied verbatim onto every occurrence.** `backend/app/modules/schedules/helpers/bulkWriteScheduleItems.ts:bulkWriteCreateScheduleItems` does `pick(schedule.toJSON(), scheduleBulkFields)` and spreads the result into each `ScheduleItem.bulkCreate` body. `scheduleBulkFields` (`backend/app/modules/schedules/constants.ts:139-157`) **includes `payRateId`** and `noPayout`. Whatever the staff user chose is stamped onto every generated occurrence; if it was absent, the occurrences get `payRateId = null`. The same helper's `bulkWriteUpdateScheduleItems` re-applies `scheduleBulkFields` on edits.

**This is the buried assumption:** the pay rate only ever lands on a `ScheduleItem` because a staff user selected it in a staff-only form and it flowed template → items. There is **no code path that back-fills `payRateId`** from `accounts.defaultPayRateId`, from `PayRate.isDefault`, or anywhere else at the point an occurrence is created. `bulkWriteCreateScheduleItems` copies whatever is on the template and no more.

## Lifecycle

```
Staff opens Schedule form (admin-frontend)
  → default rate pre-filled from PayRate.isDefault, staff can override → values.payRateId
POST /schedules  or  POST /bookings/appointment   [STAFF ROLES ONLY]
  → validateSchedule / validateAppointmentBooking (payRateId optional)
  → Schedule.create({ ...req.body })                     # payRateId on template
  → bulkWriteCreateScheduleItems()                       # pick(scheduleBulkFields) → each item
      → ScheduleItem.bulkCreate([{ ..., payRateId }])    # rate stamped per occurrence
  → (appointment path) Booking.bookAppointment() per item
Later: payroll reporting reads ScheduleItem.payRateId with a fallback chain
  (payrollGetPayouts.ts:154-163: item.payRateId → teacher.payRate → studio defaultPayRate → $0)
  → PayRate.totalAmount(bookings)
  (exports: backend/app/modules/exports/routes/exportPayrollTeacherDetails.ts,
            exportPayrollPayouts.ts)
```

## Why it breaks under a member-booking feature

Every creation entry point above is staff-gated and carries the staff-driven rate-selection step. A member-initiated / self-serve booking is a **new actor + new entry point** that creates the `Schedule`/`ScheduleItem` without ever running that step. Because `payRateId` is nullable and nothing back-fills it at creation, the occurrence is persisted with `payRateId = null`.

Crucially, the failure is **silent, not a hard error**. At payroll-compute time `backend/app/modules/reports/helpers/payroll/payrollGetPayouts.ts:154-163` resolves the rate with a fallback chain: `let payRate = defaultPayRate` (studio-level default) → `if (item.payRateId)` use the item's rate → `else if (teacher.payRate)` use the teacher's default. So a member-booked occurrence with `payRateId = null` doesn't throw — it silently pays the teacher's default rate, else the studio default, else `$0`. None of those is a rate anyone deliberately assigned to that appointment type, and the discrepancy only surfaces in payroll, well downstream of the booking. That silent-wrong-pay behavior is what makes this the documented production miss anchoring the seed.

## Key symbols

| Path | Symbol | Role |
|------|--------|------|
| `backend/app/modules/schedules/item.mysqlModel.ts` | `ScheduleItem` (field `payRateId`) | payroll-bearing occurrence; nullable FK to `payrates` |
| `backend/app/modules/schedules/helpers/bulkWriteScheduleItems.ts` | `bulkWriteCreateScheduleItems` | copies `payRateId` from template onto each occurrence (write site) |
| `backend/app/modules/schedules/constants.ts` | `scheduleBulkFields` | the copied field list — includes `payRateId`, `noPayout` |
| `backend/app/modules/schedules/routes/createOne.ts` | `action` | staff-only (`OWNER/ADMIN/FRONT-DESK`) schedule creation |
| `backend/app/modules/bookings/routes/createOneAppointmentBooking.ts` | `action` | staff-only appointment booking (`FRONT-DESK/ADMIN/OWNER/TEACHER`) |
| `backend/app/modules/schedules/helpers/validateSchedule.ts` | `validateSchedule` | `payRateId` optional, no server default |
| `backend/app/modules/payroll/mysqlModel.ts` | `PayRate`, `PayRate.totalAmount` | rate definition + earnings computation |
| `backend/app/modules/reports/helpers/payroll/payrollGetPayouts.ts` | payout rate resolution (L154-163) | compute-time fallback `item.payRateId → teacher.payRate → studio defaultPayRate → $0` (why a null rate fails silently, not loudly) |
| `admin-frontend/app/containers/SchedulePage/ScheduleAppointmentForm.tsx` | (submit handler, ~L389-396) | staff UI where the rate is chosen/defaulted |
