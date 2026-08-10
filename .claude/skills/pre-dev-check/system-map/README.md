# OS system map

Coupling-relevant architecture only — NOT full code documentation. No secrets.

- **Version:** v1 (bump on each meaningful seed/expansion; report cites `map v<n>`)
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
