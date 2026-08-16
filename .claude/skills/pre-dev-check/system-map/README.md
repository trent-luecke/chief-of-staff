# OS system map

Coupling-relevant architecture only — NOT full code documentation. No secrets.

- **Version:** v4 (bump on each meaningful seed/expansion; report cites `map v<n>`)
  - v1 (2026-08-10): seed scan — scheduling/payroll anchor.
  - v2 (2026-08-10): refined the payroll coupling with the compute-time silent-fallback chain (`payrollGetPayouts.ts:154-163`), discovered during the acceptance backtest.
  - v3 (2026-08-12): added 3 couplings from the member-booked-appointments run + real-build feedback — linked accounts (parent books/purchases for linked child accounts; corrects a mis-scoped report suggestion), booking↔credit/payment decision, and staff-role-gated booking endpoint + `ignoreConflict` override.
  - v4 (2026-08-12): first read-side/reporting seed — `analysis:mission-control`. New `subsystems/reporting.md` + 6 couplings: no point-in-time snapshots (stock metrics not historical), "active member" definition drift, derived metrics (LTV/attrition/people-per-session/collected-ARM) absent in code, gross-revenue filter (`matchSucceededSale`+`isBlossom`), terminations/freezes mutable-not-event-log, and single-studio scoping (no cross-customer aggregate).
- **entities-and-actors.md** — OS entities, the actors, and each actor's capabilities.
- **couplings.md** — the running catalog of known couplings. Grows every analysis.
- **subsystems/** — per-subsystem deep-dives, seeded from the mirror.

## Coupling entry schema (used in couplings.md)
### <short coupling title>
- **Depends on:** <system A> assumes <assumption>
- **Held by:** <system B / where the assumption originates>
- **Invalidated when:** <which of the 5 change-types breaks it>
- **Code:** <repo/path:symbol> (mirror-relative)
- **Severity:** high | med | low
- **Discovered:** <date> · <seed scan | analysis:<feature> | production miss>
