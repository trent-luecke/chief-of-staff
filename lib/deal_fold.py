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


def _payload(e) -> dict:
    """Defensive payload accessor. load_events() coerces a non-dict payload
    to {} on the normal ingest path, but the fold must stay total even if an
    event object is constructed directly (tests, other callers) with a bad
    payload — never let a None/non-dict payload raise deep inside the fold."""
    p = e.payload
    return p if isinstance(p, dict) else {}


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

    # Register every email that appears as a key. A non-string truthy email
    # (e.g. an int from a malformed event) is treated as missing — the fold
    # must stay total and never dereference a non-string as a string.
    for e in events:
        if not isinstance(e.email, str) or not e.email:
            continue
        find(e.email)

    # Cross-demo merge edges: a demo's primary email links to each of its
    # (real) contact emails. unresolved keys never take edges.
    for e in events:
        if e.kind != "demo" or not isinstance(e.email, str) or not e.email or e.email.startswith("unresolved:"):
            continue
        for c in _payload(e).get("contact_emails", []) or []:
            if c and isinstance(c, str) and not c.startswith("unresolved:"):
                union(e.email, c)

    # Manual merge edges (force-join two keys) — human override that joins
    # deals with no shared contact. Guard against unresolved singletons and
    # missing/blank merge_with so a malformed event is a no-op, never a raise.
    for e in events:
        if e.kind != "manual" or _payload(e).get("action") != "merge":
            continue
        other = _payload(e).get("merge_with")
        if not isinstance(e.email, str) or not e.email:
            continue
        if not isinstance(other, str) or not other:
            continue
        if e.email.startswith("unresolved:") or other.startswith("unresolved:"):
            continue
        find(e.email)
        find(other)
        union(e.email, other)

    # Bucket events by the root of their key. A non-string email never got
    # registered above, so it's dropped here too — it forms no deal.
    buckets: dict[str, list] = {}
    for e in events:
        if not isinstance(e.email, str) or not e.email:
            continue
        buckets.setdefault(find(e.email), []).append(e)

    # Manual split (post-pass): union-find can't "un-union", so instead we
    # re-partition each already-bucketed component by any split directive
    # affecting its members. Build affected_email -> canonical split-subkey
    # (sorted group's first element, so the result is deterministic and
    # order-independent regardless of which component the group lands in).
    # Process split directives in deterministic (timestamp, event_id) order
    # (same key used everywhere else) so overlapping split directives that
    # assign the same email to different groups resolve the same way
    # regardless of the input list's order — last-write-wins by timestamp,
    # not by input position.
    split_assign: dict[str, str] = {}
    split_events = sorted(
        (e for e in events if e.kind == "manual" and _payload(e).get("action") == "split"),
        key=lambda e: (e.timestamp or "", e.event_id),
    )
    for e in split_events:
        groups = _payload(e).get("groups")
        if not isinstance(groups, list):
            continue
        for grp in groups:
            if not grp or not isinstance(grp, list):
                continue
            grp_norm = sorted(str(x) for x in grp if x)
            if not grp_norm:
                continue
            subkey = grp_norm[0]
            for x in grp_norm:
                split_assign[x] = subkey

    if split_assign:
        rebucketed: dict[str, list] = {}
        for root, evs in buckets.items():
            for ev in evs:
                key = split_assign.get(ev.email, root)
                rebucketed.setdefault(key, []).append(ev)
        buckets = rebucketed

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
        original_key = email  # pre-re-key identity; used as a fallback if a
        # later choose_primary re-key collides with another component's key.
        d = Deal(email=email)
        contacts: list[str] = []
        ambiguous_reason = None
        lost_reason = ""
        check_back = ""
        last_active_at = None
        manual_resolved = False
        chosen_primary = ""
        dropped = False
        seed_stage = ""
        seed_outcome = ""
        seed_import_ts = None
        seed_value = None
        seed_account = ""
        has_sale = False
        sale_source = ""
        for e in evs:
            if e.kind == "demo":
                ts = e.timestamp or None
                if ts and (d.demo_date is None or ts < d.demo_date):
                    d.demo_date = ts
                for c in _payload(e).get("contact_emails", []) or []:
                    # A non-string contact email (malformed event) is treated
                    # like a missing one — never stored, so later string
                    # derefs (e.g. "@" in c) can't raise on it.
                    if isinstance(c, str) and c and c not in contacts:
                        contacts.append(c)
                if e.rep:
                    d.rep = e.rep
                if _payload(e).get("ambiguous_reason"):
                    ambiguous_reason = _payload(e)["ambiguous_reason"]
            if e.kind == "status":
                st = _payload(e).get("status")
                if st == "lost":
                    d.outcome = "lost"
                    lost_reason = _payload(e).get("lost_reason", "") or lost_reason
                elif st == "hold":
                    check_back = _payload(e).get("check_back", "") or ""
                    last_active_at = None  # a fresh hold clears a prior active reset
                elif st == "active":
                    last_active_at = e.timestamp
                    check_back = ""        # moving again clears any snooze
            if e.kind == "manual":
                act = _payload(e).get("action")
                if act in ("confirm", "choose_primary", "merge", "split"):
                    manual_resolved = True
                if act == "choose_primary":
                    proposed_primary = _payload(e).get("primary_email", "")
                    # A non-string primary_email (malformed event) is a
                    # no-op here, not a re-key — keeps `email` a string so
                    # the later `.startswith` below can't raise.
                    if isinstance(proposed_primary, str) and proposed_primary:
                        chosen_primary = proposed_primary
                if act == "not_a_deal":
                    dropped = True
            if e.kind == "seed":
                p = _payload(e)
                if p.get("stage"):
                    seed_stage = p["stage"]
                if p.get("outcome"):
                    seed_outcome = p["outcome"]
                if p.get("import_ts"):
                    seed_import_ts = p["import_ts"]
                if p.get("estimated_value") is not None:
                    seed_value = p["estimated_value"]
                if e.account_name:
                    seed_account = e.account_name
            if e.kind == "sale":
                p = _payload(e)
                if e.timestamp:
                    d.close_date = e.timestamp        # evs sorted → later sale wins
                if p.get("deal_value") is not None:
                    d.deal_value = p["deal_value"]
                if e.source:
                    sale_source = e.source
                has_sale = True
            if e.timestamp and (d.last_event_at is None or e.timestamp > d.last_event_at):
                d.last_event_at = e.timestamp

        if chosen_primary:
            email = chosen_primary
            d.email = email

        d.contact_emails = contacts
        d.cycle_start = d.demo_date  # min(trial, demo) == demo in Phase 1a
        has_real = any(e.kind in ("demo", "trial", "sale") for e in evs)
        if d.outcome == "lost":                 # explicit status=lost event — terminal
            d.stage = "lost"
            d.lost_reason = lost_reason
        elif has_sale:                          # a sale closes the deal — won
            d.outcome = "won"
            d.stage = "won"
            if sale_source:
                d.source = sale_source
        elif has_real:                          # real demo/trial drives stage
            d.outcome = "open"
            d.stage = "demoed"
        elif seed_stage or seed_outcome:        # seed-only: imported state is ground truth
            d.outcome = seed_outcome or "open"
            d.stage = seed_stage or "demoed"
        else:
            d.outcome = "open"
            d.stage = "demoed"
        if d.deal_value is None and seed_value is not None:
            d.deal_value = seed_value
        d.account_name = "" if email.startswith("unresolved:") else (crosswalk.get(email) or seed_account or domain_to_name(email))

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

        # A seed-only OPEN deal anchors its 45-day clock to the import date
        # (clean slate: nothing stale on import day; ages in after import+45d).
        seed_anchor = seed_import_ts if (not has_real and (seed_stage or seed_outcome)) else None
        sale_only = has_sale and not any(e.kind in ("demo", "trial", "seed") for e in evs)
        snoozed = isinstance(check_back, str) and bool(check_back) and check_back > today[:10]
        effective_start = max([s for s in (d.cycle_start, last_active_at, seed_anchor) if s], default=None)

        if d.outcome == "lost":
            d.review = {"needs": False}
        elif ambiguous_reason and not manual_resolved:
            d.review = {"needs": True, "kind": "ambiguous", "reason": ambiguous_reason,
                        "proposed": {"email": email, "account_name": d.account_name, "rep": d.rep}}
        elif sale_only:
            d.review = {"needs": True, "kind": "unmatched_sale", "reason": "sale_no_demo",
                        "proposed": {"email": email, "account_name": d.account_name, "rep": d.rep}}
        elif snoozed:
            d.review = {"needs": False, "check_back": check_back}
        elif d.outcome == "open" and effective_start and _days_since(effective_start, today) >= stale_days:
            d.review = {"needs": True, "kind": "stale_check", "reason": "aged_%dd" % stale_days,
                        "proposed": None}
        else:
            d.review = {"needs": False}

        if dropped:
            continue

        if email in deals:
            # Re-key collision: a choose_primary event pointed this component
            # at a key another (independent) component already occupies —
            # either that component's natural key or its own chosen primary.
            # Never overwrite/lose either deal: the already-stored deal keeps
            # the contested key, and this one falls back to its own
            # pre-re-key identity, flagged for human review. Component
            # processing order is deterministic (sorted by root key — see
            # _group_components) and independent of the input events list
            # order, so which deal "wins" the contested key is stable.
            fallback_key = original_key
            if fallback_key == email or fallback_key in deals:
                # Extremely rare secondary collision (the fallback key is
                # itself already taken) — still must never lose data.
                suffix = 2
                candidate = f"{fallback_key}#conflict{suffix}"
                while candidate in deals:
                    suffix += 1
                    candidate = f"{fallback_key}#conflict{suffix}"
                fallback_key = candidate
            d.email = fallback_key
            d.review = {"needs": True, "kind": "ambiguous", "reason": "account_conflict",
                        "proposed": {"email": fallback_key, "account_name": d.account_name, "rep": d.rep}}
            deals[fallback_key] = d
        else:
            deals[email] = d
    return deals


def build_deals_to_review(deals: dict) -> dict:
    """Shape folded deals into the identity + 45-day review queues. Pure —
    never mutates `deals`, never raises. Deterministically ordered by deal
    key (sorted iteration) so the UI/brief render stably."""
    identity, stale = [], []
    for key in sorted(deals):
        d = deals[key]
        if not d.review.get("needs"):
            continue
        if d.review.get("kind") == "ambiguous":
            identity.append({
                "deal_key": d.email,
                "account_name": d.account_name,
                "rep": d.rep,
                "reason": d.review.get("reason", ""),
                "proposed": d.review.get("proposed"),
                "contact_emails": list(d.contact_emails),
                "demo_date": d.demo_date,
            })
        elif d.review.get("kind") == "stale_check":
            stale.append({
                "deal_key": d.email,
                "account_name": d.account_name,
                "rep": d.rep,
                "cycle_start": d.cycle_start,
                "last_event_at": d.last_event_at,
                "check_back": d.review.get("check_back", ""),
            })
    return {
        "identity": identity,
        "stale": stale,
        "counts": {"identity": len(identity), "stale": len(stale),
                   "total": len(identity) + len(stale)},
    }
