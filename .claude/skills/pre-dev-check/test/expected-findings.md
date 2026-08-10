# Backtest acceptance criteria — member-booked appointments

The Blind-Spot Report PASSES only if ALL hold:
1. "Changes this introduces" lists an **actor change** (staff -> member) and an **entry-point change** (studio view -> member booking).
2. Blind spots include the **payroll pay-rate coupling**: member-initiated creation has no rate-assignment step, so the rate is never set.
3. That finding is **severity: high** and **Grounding: code-confirmed** (cites a real backend path), not heuristic.
4. The cross-cutting sweep marks **payroll = touched, NOT handled**.
5. No fabricated couplings: any unverifiable item is labeled "couldn't verify", not asserted.
