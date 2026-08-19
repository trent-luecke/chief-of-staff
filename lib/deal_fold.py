"""Fold DealEvents into current email-keyed deals."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from lib.deal_crosswalk import domain_to_name


@dataclass
class Deal:
    email: str
    account_name: str = ""
    rep: str = ""
    demo_date: str | None = None
    trial_start_date: str | None = None
    cycle_start: str | None = None
    close_date: str | None = None
    outcome: str = "open"
    stage: str = ""
    contact_emails: list = field(default_factory=list)
    source: str = ""
    deal_value: float | None = None
    lost_reason: str = ""
    provenance: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)
    last_event_at: str | None = None


def _days_since(iso: str, today: str) -> int:
    try:
        return (date.fromisoformat(today[:10]) - date.fromisoformat(iso[:10])).days
    except (ValueError, TypeError):
        return 0


def _norm(email: str | None) -> str | None:
    return email or None


def _group_components(events: list) -> list[list]:
    """Union-find over emails. Cross-demo merges happen ONLY via a shared
    contact email — a demo's primary email is unioned with each of its
    `contact_emails`, so two demos that share an attendee fold into one
    component. Same-domain alone is NOT a merge signal: two demos on the same
    domain with no shared attendee stay separate components (a later manual
    merge action is what would join those). `unresolved:<uuid>` keys stay
    singleton. Returns a list of event-lists, one per component. Deterministic
    and order-independent. Total: malformed events (missing/blank `email`)
    are skipped, never raise."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        lo, hi = sorted((ra, rb))  # smaller string wins → deterministic root
        parent[hi] = lo

    # Register every email that appears as a key.
    for e in events:
        if not e.email:
            continue
        find(e.email)

    # Cross-demo merge edges: a demo's primary email links to each of its
    # (real) contact emails. unresolved keys never take edges.
    for e in events:
        if e.kind != "demo" or not e.email or e.email.startswith("unresolved:"):
            continue
        for c in e.payload.get("contact_emails", []) or []:
            if c and not str(c).startswith("unresolved:"):
                union(e.email, c)

    # Bucket events by the root of their key.
    buckets: dict[str, list] = {}
    for e in events:
        if not e.email:
            continue
        buckets.setdefault(find(e.email), []).append(e)
    # Deterministic ordering of components by root key.
    return [buckets[root] for root in sorted(buckets)]


def _canonical_key(component_events: list) -> str:
    """Primary email of the earliest demo in the component; falls back to the
    lexicographically smallest key seen."""
    demos = [e for e in component_events if e.kind == "demo" and e.email]
    if demos:
        demos = sorted(demos, key=lambda e: (e.timestamp or "", e.event_id))
        return demos[0].email
    keys = sorted({e.email for e in component_events if e.email})
    return keys[0] if keys else ""


def build_deals(events: list, crosswalk: dict, today: str, stale_days: int = 45) -> dict:
    deals: dict[str, Deal] = {}
    for comp in _group_components(events):
        evs = sorted(comp, key=lambda e: (e.timestamp or "", e.event_id))
        email = _canonical_key(comp)
        d = Deal(email=email)
        contacts: list[str] = []
        ambiguous_reason = None
        lost_reason = ""
        check_back = ""
        last_active_at = None
        for e in evs:
            if e.kind == "demo":
                ts = e.timestamp or None
                if ts and (d.demo_date is None or ts < d.demo_date):
                    d.demo_date = ts
                for c in e.payload.get("contact_emails", []) or []:
                    if c not in contacts:
                        contacts.append(c)
                if e.rep:
                    d.rep = e.rep
                if e.payload.get("ambiguous_reason"):
                    ambiguous_reason = e.payload["ambiguous_reason"]
            if e.kind == "status":
                st = e.payload.get("status")
                if st == "lost":
                    d.outcome = "lost"
                    lost_reason = e.payload.get("lost_reason", "") or lost_reason
                elif st == "hold":
                    check_back = e.payload.get("check_back", "") or ""
                    last_active_at = None  # a fresh hold clears a prior active reset
                elif st == "active":
                    last_active_at = e.timestamp
                    check_back = ""        # moving again clears any snooze
            if e.timestamp and (d.last_event_at is None or e.timestamp > d.last_event_at):
                d.last_event_at = e.timestamp

        d.contact_emails = contacts
        d.cycle_start = d.demo_date  # min(trial, demo) == demo in Phase 1a
        if d.outcome == "lost":
            d.stage = "lost"
            d.lost_reason = lost_reason
        else:
            d.outcome = "open"
            d.stage = "demoed"
        d.account_name = "" if email.startswith("unresolved:") else (crosswalk.get(email) or domain_to_name(email))

        # Cross-demo merge spanning >1 derived account → account_conflict.
        # Only fires on a REAL cross-demo merge (>1 demo event in the
        # component), and never clobbers an existing per-demo reason (e.g.
        # a single demo's own multi_domain label).
        real = [c for c in contacts if c and "@" in c and not c.startswith("unresolved:")]
        accounts = {(crosswalk.get(c) or domain_to_name(c)) for c in real}
        accounts.discard("")
        demo_count = sum(1 for e in evs if e.kind == "demo")
        if not ambiguous_reason and demo_count > 1 and len(accounts) > 1:
            ambiguous_reason = "account_conflict"

        snoozed = isinstance(check_back, str) and bool(check_back) and check_back > today[:10]
        effective_start = max([s for s in (d.cycle_start, last_active_at) if s], default=None)

        if d.outcome == "lost":
            d.review = {"needs": False}
        elif ambiguous_reason:
            d.review = {"needs": True, "kind": "ambiguous", "reason": ambiguous_reason,
                        "proposed": {"email": email, "account_name": d.account_name, "rep": d.rep}}
        elif snoozed:
            d.review = {"needs": False, "check_back": check_back}
        elif effective_start and _days_since(effective_start, today) >= stale_days:
            d.review = {"needs": True, "kind": "stale_check", "reason": "aged_%dd" % stale_days,
                        "proposed": None}
        else:
            d.review = {"needs": False}

        deals[email] = d
    return deals
