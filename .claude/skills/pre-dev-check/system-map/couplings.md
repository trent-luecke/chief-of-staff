# Known couplings

### Pay rate assigned at schedule-item creation by the creating staff user
- **Depends on:** payroll assumes a pay rate exists on every schedule item
- **Held by:** schedule-item creation flow — the creating STAFF user sets the rate at creation (defaulted from `PayRate.isDefault` in the studio UI, persisted onto the `Schedule` template, then copied onto each `ScheduleItem`); `payRateId` is a nullable column with no server-side back-fill
- **Invalidated when:** actor change (member-initiated creation) OR entry-point change (self-serve booking) — a member has no rate-assignment step and nothing back-fills `payRateId`, so the rate is never set and payroll computes to nothing
- **Code:** `backend/app/modules/schedules/helpers/bulkWriteScheduleItems.ts:bulkWriteCreateScheduleItems` (copies `scheduleBulkFields` incl. `payRateId` onto each item); entry points `backend/app/modules/schedules/routes/createOne.ts:action` and `backend/app/modules/bookings/routes/createOneAppointmentBooking.ts:action` (both staff-role gated); field `backend/app/modules/schedules/item.mysqlModel.ts:ScheduleItem.payRateId` (nullable)
- **Severity:** high
- **Discovered:** 2026-08-10 · seed scan (known production miss: member-booked appointments)
