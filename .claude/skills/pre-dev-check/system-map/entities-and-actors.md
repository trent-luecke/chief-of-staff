# Entities and actors

Seeded from the OS backend mirror (`~/dev/gymstudio/backend`). Coupling-relevant only; incompleteness at v1 is expected, not a placeholder. Paths are mirror-relative.

## Actors

An **Account** (`backend/app/modules/accounts/mysqlModel.ts`) belongs to a **Studio** and is either staff (holds one or more studio roles) or a client/member (no staff role). `Studio.assertFindByReq(req, roles)` gates every route by role.

### Staff roles (`StaffRolesENUM`, `core/config/common.ts:516`)
| Role | Value | Relevant capabilities |
|------|-------|-----------------------|
| Owner | `owner` | Full studio admin; create/edit schedules, appointments, pay rates; **assign `payRateId` at schedule creation** |
| Admin | `admin` | Same as owner for scheduling/payroll create paths |
| Front desk | `front-desk` | Create schedules and book appointments on behalf of clients (`createOne.ts`, `createOneAppointmentBooking.ts`) — **carries the rate-assignment step** |
| Teacher | `teacher` | Book appointments for their own categories (`createOneAppointmentBooking.ts` gates teacher to own appointment via `validateTeacherAccess`); is the payee on `schedule_items_accounts` |

### Client / member
- A member is an `Account` with **no staff role**. Booking on their behalf currently always goes through a staff-gated route (`bookAppointment` is invoked from staff routes with `userType: Account`).
- **Capability gap (the anchored miss):** a member has **no** capability to run the schedule/appointment *creation* flow, and therefore no rate-assignment step. Adding member-initiated booking introduces a new actor at a creation entry point that the payroll coupling assumes only staff reach.

### External user / partners
- `BookingUserTypesENUM.EXTERNAL_USER` (`core/config/common.ts:240`) — non-Account bookers (e.g. ClassPass / OneFit integrations). Book onto existing schedule items; do not create schedules.

## Entities (coupling-relevant)

| Entity | Model / path | Notes |
|--------|-------------|-------|
| Studio | `backend/app/modules/studios/mysqlModel.ts` | Top-level tenant; scopes every request via `blsm-studio-id` |
| Account | `backend/app/modules/accounts/mysqlModel.ts` | Staff or member; has unused `defaultPayRateId` column (per-teacher default, not read by the create flow) |
| Schedule | `backend/app/modules/schedules/mysqlModel.ts` | Recurring template (`lesson`/`appointment`); holds `payRateId`, `noPayout` |
| ScheduleItem | `backend/app/modules/schedules/item.mysqlModel.ts` | Dated occurrence; **payroll-bearing**; nullable `payRateId` FK → `payrates` |
| Appointment | `backend/app/modules/appointments/mysqlModel.ts` | Appointment *type* (name/duration/category + internal pricing option); has no price/rate of its own |
| Lesson | `backend/app/modules/lessons/mysqlModel.ts` | Class type an occurrence can reference |
| Workshop | `backend/app/modules/workshops/mysqlModel.ts` | Multi-session event; alternate parent of `ScheduleItem` |
| Booking | `backend/app/modules/bookings/mysqlModel.ts` | A client's reservation on a `ScheduleItem` (or workshop); created by `Booking.bookAppointment` |
| PayRate | `backend/app/modules/payroll/mysqlModel.ts` | Rate definition (`flatAmount` + optional booking bonus); one `isDefault` per studio; `totalAmount(bookings)` computes earnings |
| schedule_items_accounts | `backend/core/database/mysql/junctionTables/scheduleItemsAccounts.ts` | Teacher ↔ ScheduleItem link (`isSubstitute` flag) — who gets paid |

## Actor → capability summary (scheduling/payroll)

- **Create a Schedule/appointment and thereby set the pay rate:** owner, admin, front-desk (and teacher, for their own appointments). This is the *only* place `payRateId` originates.
- **Be paid for an occurrence:** teacher / substitute teacher (via `schedule_items_accounts`), using the occurrence's `payRateId`.
- **Book onto an occurrence:** staff (on behalf of a member), external partners. Booking does **not** touch `payRateId`.
- **Member:** book/attend only — no creation, no rate assignment. Extending members into the creation path is the change class this map is built to catch.
