# Analysis lens — the change-types that invalidate assumptions

For each change the feature introduces, trace the systems that depended on the OLD version.

## 1. Actor change — who can now perform this action?
e.g. staff-only -> member. Breaks:
- data the old actor used to set at action time (e.g. the payroll pay rate)
- permission checks, ownership/attribution, audit trails
- notifications addressed to the old actor

## 2. Entry-point change — a new path into the system
e.g. studio view -> member booking flow. Breaks:
- validation & business rules that lived only on the old path
- default values, required fields
- side effects triggered only by the old entry point

## 3. State / lifecycle change — new states or transitions
e.g. members can now cancel. Breaks:
- cancellation policy, refunds, capacity release
- payroll reversal, downstream state machines

## 4. Scale / cardinality change — more, and more concurrent, activity
e.g. self-serve volume. Breaks:
- capacity limits, double-booking guards, rate limits
- performance assumptions

## 5. Data coupling — a field another system reads is now produced differently/later/not at all
Breaks: every downstream consumer of that field (reporting, billing, exports, integrations).

## How to use
1. From the transcript, list which of these 5 changes the feature introduces.
2. For each, consult system-map/couplings.md for known couplings, THEN do targeted reads
   into the affected subsystem in the mirror to confirm/expand.
3. Tag each finding: code-confirmed | map | heuristic.
