# Phase 1b (a) — Deal Fold Extension + Read Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `lib/deal_fold.build_deals` to *apply* `status` and `manual` DealEvents and to merge deals across demos that share a contact email, then expose a pure read-model builder that shapes the two review queues.

**Architecture:** Pure, event-sourced fold. `build_deals` already folds `demo` events per normalized email. This plan (1) groups emails into deal components via union-find over shared `contact_emails` (cross-demo merge), (2) applies `status` events (lost / on-hold / still-active) and `manual` events (confirm / choose-primary / merge / split / not-a-deal) during the fold, and (3) adds `build_deals_to_review(deals)` which filters `review.needs` into two render-ready queues. Everything is a pure function over the event log — no UI, no I/O, no new store. Human decisions are themselves DealEvents (added by Plan b), so a resolved flag clears on the next fold and never re-prompts.

**Tech Stack:** Python 3, dataclasses, `pytest`. No new dependencies.

## Global Constraints

- **The fold is pure and total.** `build_deals(events, crosswalk, today, stale_days=45)` takes only its arguments and must never do I/O. It must not raise on malformed events — bad rows degrade gracefully.
- **Order-independence is a hard invariant.** Shuffling the event list must produce identical deals. A Critical order-dependence bug already bit Phase 1a; every group's events are sorted by `(timestamp, event_id)` before folding. Every new behavior gets an order-independence test.
- **Never auto-Lost.** The 45-day rule only ever *flags* a deal for review (`review.kind == "stale_check"`). Only an explicit `status` event with `status="lost"` sets `outcome="lost"`.
- **Human decisions ARE events; resolved flags clear on the next fold.** A `manual` event on a deal clears its `ambiguous` review; a `status` event clears/updates its `stale_check` review. Never re-prompt for a resolved decision.
- **`unresolved:<uuid>` keys are singletons.** They carry no real email, so they never union-merge with anything.
- **Event vocab is fixed** (`lib/deal_events.py`): `DealEvent(event_id, email, email_raw, kind, timestamp, account_name, rep, source, payload)`, `kind ∈ {demo, trial, sale, status, manual}`. Do not change the dataclass in this plan.
- **`status`/`manual` payload contracts** (defined here, produced by Plan b's endpoints):
  - `status` payload: `{"status": "lost"|"hold"|"active", "lost_reason"?: str, "check_back"?: "YYYY-MM-DD"}`. `email` = the deal key the action targeted.
  - `manual` payload: `{"action": "confirm"|"choose_primary"|"merge"|"split"|"not_a_deal", "primary_email"?: str, "merge_with"?: str, "groups"?: [[str,...],...]}`. `email` = the deal key the action targeted.
- **Run the full deal suite after every task:** `python -m pytest tests/test_deal_fold.py tests/test_deal_sync.py -q` must stay green (existing Phase 1a tests must not regress).

---

## File Structure

- `lib/deal_fold.py` — **modify.** All new fold behavior lands here: union-find grouping, `status`/`manual` application, review computation. Add one pure helper module-level function `build_deals_to_review`.
- `tests/test_deal_fold.py` — **modify.** Add tests for every new behavior alongside the existing Phase 1a tests.

No new files. `deal_sync.refresh_deal_store` already calls `build_deals(...)` and needs no change — it folds the whole event log every run, so applying new event kinds is automatic once the fold understands them.

---

## Task 1: Refactor the fold into component grouping (behavior-preserving)

Replace the strict `by_email` grouping with a union-find that today produces one component per email (identical output), so later tasks can add merge edges without another rewrite. This is a pure refactor: all existing tests must still pass with zero changes.

**Files:**
- Modify: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py`

**Interfaces:**
- Consumes: `DealEvent` from `lib/deal_events.py`; `domain_to_name` from `lib/deal_crosswalk.py`.
- Produces: `build_deals(events, crosswalk, today, stale_days=45) -> dict[str, Deal]` (unchanged signature). New private helpers `_group_components(events) -> list[list[DealEvent]]` and `_canonical_key(component_events) -> str`.

- [ ] **Step 1: Write the failing test** — a component helper exists and, with no merge edges, gives one component per distinct email.

```python
# add near the top-level tests in tests/test_deal_fold.py
from lib.deal_fold import _group_components, _canonical_key


def test_group_components_one_per_email_without_edges():
    e1 = _demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"])
    e2 = _demo("b", "y@beta.com", "2026-08-11T00:00:00Z", ["y@beta.com"])
    comps = _group_components([e1, e2])
    keys = sorted(_canonical_key(c) for c in comps)
    assert keys == ["x@acme.com", "y@beta.com"]


def test_canonical_key_is_earliest_demo_primary():
    # two demos, same component (shared contact), different primaries
    e_late = _demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com", "shared@acme.com"])
    e_early = _demo("b", "z@acme.com", "2026-08-02T00:00:00Z", ["z@acme.com", "shared@acme.com"])
    comps = _group_components([e_late, e_early])
    assert len(comps) == 1
    assert _canonical_key(comps[0]) == "z@acme.com"  # earliest demo's primary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_deal_fold.py::test_group_components_one_per_email_without_edges tests/test_deal_fold.py::test_canonical_key_is_earliest_demo_primary -v`
Expected: FAIL with `ImportError: cannot import name '_group_components'`.

- [ ] **Step 3: Add the union-find grouping and rewire `build_deals` to iterate components**

In `lib/deal_fold.py`, add these helpers above `build_deals`:

```python
def _norm(email: str | None) -> str | None:
    return email or None


def _group_components(events: list) -> list[list]:
    """Union-find over emails; same-domain and shared-contact emails merge into
    one component. `unresolved:<uuid>` keys stay singleton. Returns a list of
    event-lists, one per component. Deterministic and order-independent."""
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
        if e.kind != "demo" or e.email.startswith("unresolved:"):
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
```

Then change `build_deals` to iterate components instead of `by_email`. Replace the grouping loop:

```python
def build_deals(events: list, crosswalk: dict, today: str, stale_days: int = 45) -> dict:
    deals: dict[str, Deal] = {}
    for comp in _group_components(events):
        evs = sorted(comp, key=lambda e: (e.timestamp or "", e.event_id))
        email = _canonical_key(comp)
        d = Deal(email=email)
        contacts: list[str] = []
        ambiguous_reason = None
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
            if e.timestamp and (d.last_event_at is None or e.timestamp > d.last_event_at):
                d.last_event_at = e.timestamp

        d.contact_emails = contacts
        d.cycle_start = d.demo_date
        d.outcome = "open"
        d.stage = "demoed"
        d.account_name = "" if email.startswith("unresolved:") else (crosswalk.get(email) or domain_to_name(email))

        if ambiguous_reason:
            d.review = {"needs": True, "kind": "ambiguous", "reason": ambiguous_reason,
                        "proposed": {"email": email, "account_name": d.account_name, "rep": d.rep}}
        elif d.cycle_start and _days_since(d.cycle_start, today) >= stale_days:
            d.review = {"needs": True, "kind": "stale_check", "reason": "aged_%dd" % stale_days,
                        "proposed": None}
        else:
            d.review = {"needs": False}

        deals[email] = d
    return deals
```

- [ ] **Step 4: Run the full fold suite to verify no regression + new tests pass**

Run: `python -m pytest tests/test_deal_fold.py -v`
Expected: PASS — all pre-existing Phase 1a tests plus the two new ones.

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "refactor(deals): fold over union-find components (behavior-preserving)"
```

---

## Task 2: Cross-demo account merge + `account_conflict` reason

With union-find in place, two demos that share a contact email now fold into one deal. Add the `account_conflict` flag for the case the design calls out: a merge that joins two *different* derived account names (a demo email matched an existing deal on a different domain/account).

**Files:**
- Modify: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py`

**Interfaces:**
- Consumes: `_group_components`, `domain_to_name`.
- Produces: components whose events span >1 derived account name carry `ambiguous_reason = "account_conflict"` in the folded `Deal.review`.

- [ ] **Step 1: Write the failing tests**

```python
def test_cross_demo_same_domain_merges_to_one_deal():
    # jane and bob, same domain, two separate demos → ONE deal
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com"])
    e2 = _demo("d2", "bob@acme.com", "2026-08-12T00:00:00Z", ["bob@acme.com"])
    # they merge only if a shared contact links them; simulate a shared attendee
    e1.payload["contact_emails"] = ["jane@acme.com", "shared@acme.com"]
    e2.payload["contact_emails"] = ["bob@acme.com", "shared@acme.com"]
    deals = build_deals([e1, e2], {}, TODAY)
    assert len(deals) == 1
    d = list(deals.values())[0]
    assert set(d.contact_emails) >= {"jane@acme.com", "bob@acme.com", "shared@acme.com"}
    assert d.review.get("reason") != "account_conflict"  # one account, no conflict


def test_account_conflict_flagged_when_merge_spans_accounts():
    # a shared person bridges two different-domain demos → account_conflict
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com", "consultant@shared.com"])
    e2 = _demo("d2", "bob@beta.com", "2026-08-12T00:00:00Z", ["bob@beta.com", "consultant@shared.com"])
    deals = build_deals([e1, e2], {}, TODAY)
    assert len(deals) == 1
    d = list(deals.values())[0]
    assert d.review["needs"] is True
    assert d.review["kind"] == "ambiguous"
    assert d.review["reason"] == "account_conflict"


def test_cross_demo_merge_is_order_independent():
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com", "shared@acme.com"])
    e2 = _demo("d2", "bob@acme.com", "2026-08-12T00:00:00Z", ["bob@acme.com", "shared@acme.com"])
    fwd = build_deals([e1, e2], {}, TODAY)
    bwd = build_deals([e2, e1], {}, TODAY)
    assert list(fwd) == list(bwd)
    assert sorted(list(fwd.values())[0].contact_emails) == sorted(list(bwd.values())[0].contact_emails)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_deal_fold.py::test_account_conflict_flagged_when_merge_spans_accounts -v`
Expected: FAIL (`reason` is `None`, not `"account_conflict"`).

- [ ] **Step 3: Compute `account_conflict` during the component fold**

In `build_deals`, after the per-event loop and after `d.contact_emails = contacts`, compute whether the component spans multiple accounts, and let it override a missing reason. Insert before the `if ambiguous_reason:` block:

```python
        # Cross-demo merge spanning >1 derived account → account_conflict.
        real = [c for c in contacts if c and "@" in c and not c.startswith("unresolved:")]
        accounts = {(crosswalk.get(c) or domain_to_name(c)) for c in real}
        accounts.discard("")
        if len(accounts) > 1:
            ambiguous_reason = "account_conflict"
```

- [ ] **Step 4: Run the full fold suite**

Run: `python -m pytest tests/test_deal_fold.py -v`
Expected: PASS (all existing + three new).

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat(deals): cross-demo account merge + account_conflict flag"
```

---

## Task 3: Apply `status` events — Lost

`status` events with `status="lost"` set `outcome="lost"`, record `lost_reason`, set `stage="lost"`, and clear any review flag. Lost is terminal.

**Files:**
- Modify: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py`

**Interfaces:**
- Consumes: `DealEvent(kind="status", payload={"status":"lost","lost_reason":...})`.
- Produces: `Deal.outcome == "lost"`, `Deal.lost_reason`, `Deal.stage == "lost"`, `Deal.review["needs"] is False`.

- [ ] **Step 1: Write the failing test + a `_status` fixture helper**

```python
def _status(uuid, email, ts, status, lost_reason="", check_back=""):
    payload = {"status": status}
    if lost_reason:
        payload["lost_reason"] = lost_reason
    if check_back:
        payload["check_back"] = check_back
    return DealEvent(event_id=uuid, email=email, email_raw="", kind="status", timestamp=ts,
                     rep="", source="ui", payload=payload)


def test_status_lost_sets_outcome_and_clears_review():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])  # aged → would be stale
    lost = _status("s1", "x@acme.com", "2026-08-18T00:00:00Z", "lost", lost_reason="went with competitor")
    d = build_deals([demo, lost], {}, TODAY)["x@acme.com"]
    assert d.outcome == "lost"
    assert d.stage == "lost"
    assert d.lost_reason == "went with competitor"
    assert d.review["needs"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_deal_fold.py::test_status_lost_sets_outcome_and_clears_review -v`
Expected: FAIL (`outcome == "open"`).

- [ ] **Step 3: Track status state during the fold and apply Lost**

In `build_deals`, inside the per-event loop, add handling for `status` events. Add locals before the loop: `lost_reason = ""`, `latest_status = None`. Inside the loop add:

```python
            if e.kind == "status":
                st = e.payload.get("status")
                if st == "lost":
                    d.outcome = "lost"
                    lost_reason = e.payload.get("lost_reason", "") or lost_reason
```

After the loop, once `d.outcome` is set, replace the fixed `d.stage = "demoed"` / `d.outcome = "open"` lines so they respect a Lost result:

```python
        d.cycle_start = d.demo_date
        if d.outcome == "lost":
            d.stage = "lost"
            d.lost_reason = lost_reason
        else:
            d.outcome = "open"
            d.stage = "demoed"
```

Then guard review so terminal deals never flag. Change the review block's head:

```python
        if d.outcome == "lost":
            d.review = {"needs": False}
        elif ambiguous_reason:
            ...
```

(Keep the existing `ambiguous` and `stale_check` branches after this new head.)

- [ ] **Step 4: Run the full fold suite**

Run: `python -m pytest tests/test_deal_fold.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat(deals): apply status:lost in fold"
```

---

## Task 4: Apply `status` events — On-hold (check-back snooze) and Still-active (clock reset)

On-hold sets a `check_back` date that suppresses the 45-day review until that date, keeping `outcome="open"`. Still-active resets the 45-day clock from the event's timestamp. Both are order-independent (latest event wins by timestamp).

**Files:**
- Modify: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py`

**Interfaces:**
- Consumes: `status` events `{"status":"hold","check_back":"YYYY-MM-DD"}` and `{"status":"active"}`.
- Produces: On-hold → `Deal.review["needs"] is False` while `check_back > today`, `Deal.review` carries `check_back`; the deal re-surfaces as `stale_check` once `check_back <= today`. Still-active → stale clock measured from the latest `active` timestamp.

- [ ] **Step 1: Write the failing tests**

```python
def test_status_hold_suppresses_stale_until_check_back():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])  # aged
    hold = _status("s1", "x@acme.com", "2026-08-10T00:00:00Z", "hold", check_back="2026-09-30")
    d = build_deals([demo, hold], {}, TODAY)["x@acme.com"]  # TODAY = 2026-08-18
    assert d.outcome == "open"
    assert d.review["needs"] is False
    assert d.review.get("check_back") == "2026-09-30"


def test_status_hold_resurfaces_after_check_back_date():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])
    hold = _status("s1", "x@acme.com", "2026-07-01T00:00:00Z", "hold", check_back="2026-08-01")
    d = build_deals([demo, hold], {}, TODAY)["x@acme.com"]  # check_back is in the past
    assert d.review["needs"] is True
    assert d.review["kind"] == "stale_check"


def test_status_active_resets_the_45_day_clock():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])  # would be stale
    active = _status("s1", "x@acme.com", "2026-08-15T00:00:00Z", "active")   # 3 days ago
    d = build_deals([demo, active], {}, TODAY, stale_days=45)["x@acme.com"]
    assert d.review["needs"] is False


def test_status_events_are_order_independent():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])
    a = _status("s1", "x@acme.com", "2026-07-01T00:00:00Z", "active")
    h = _status("s2", "x@acme.com", "2026-08-10T00:00:00Z", "hold", check_back="2026-09-30")
    fwd = build_deals([demo, a, h], {}, TODAY)["x@acme.com"].review
    bwd = build_deals([h, a, demo], {}, TODAY)["x@acme.com"].review
    assert fwd == bwd
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_deal_fold.py -k "hold or active" -v`
Expected: FAIL.

- [ ] **Step 3: Track hold/active state and fold it into the stale computation**

Add locals before the per-event loop: `check_back = ""`, `last_active_at = None`. In the loop's `status` branch (events are already timestamp-sorted, so the last write wins):

```python
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
```

Replace the `stale_check` branch to honor the reset clock and the snooze. The review block becomes:

```python
        snoozed = bool(check_back) and check_back > today[:10]
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
```

Note: `_days_since` slices `[:10]`, and `check_back`/`today` compare on the date prefix — `today[:10]` guards the case where `today` is passed with a time component.

- [ ] **Step 4: Run the full fold suite**

Run: `python -m pytest tests/test_deal_fold.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat(deals): apply status hold/active (snooze + 45d clock reset)"
```

---

## Task 5: Apply `manual` events — confirm, choose-primary, not-a-deal

Identity resolution that operates *within* an already-computed component: `confirm` clears the ambiguous flag, `choose_primary` re-keys the deal to a chosen email and clears the flag, `not_a_deal` drops the deal from output entirely.

**Files:**
- Modify: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py`

**Interfaces:**
- Consumes: `manual` events `{"action":"confirm"}`, `{"action":"choose_primary","primary_email":...}`, `{"action":"not_a_deal"}`.
- Produces: `confirm`/`choose_primary` → `review["needs"] is False`; `choose_primary` → deal keyed by `primary_email`; `not_a_deal` → the deal is absent from `build_deals(...)` output.

- [ ] **Step 1: Write the failing tests + `_manual` fixture**

```python
def _manual(uuid, email, ts, action, primary_email="", merge_with="", groups=None):
    payload = {"action": action}
    if primary_email:
        payload["primary_email"] = primary_email
    if merge_with:
        payload["merge_with"] = merge_with
    if groups is not None:
        payload["groups"] = groups
    return DealEvent(event_id=uuid, email=email, email_raw="", kind="manual", timestamp=ts,
                     rep="", source="ui", payload=payload)


def test_manual_confirm_clears_ambiguous():
    demo = _demo("d1", "x@acme.com", "2026-08-15T00:00:00Z", ["x@acme.com"], reason="free_email")
    conf = _manual("m1", "x@acme.com", "2026-08-16T00:00:00Z", "confirm")
    d = build_deals([demo, conf], {}, TODAY)["x@acme.com"]
    assert d.review["needs"] is False


def test_manual_choose_primary_rekeys_and_clears():
    demo = _demo("d1", "info@acme.com", "2026-08-15T00:00:00Z", ["info@acme.com", "jane@acme.com"], reason="generic_inbox")
    pick = _manual("m1", "info@acme.com", "2026-08-16T00:00:00Z", "choose_primary", primary_email="jane@acme.com")
    deals = build_deals([demo, pick], {}, TODAY)
    assert "jane@acme.com" in deals
    assert deals["jane@acme.com"].review["needs"] is False


def test_manual_not_a_deal_drops_it():
    demo = _demo("d1", "noreply@vendor.com", "2026-08-15T00:00:00Z", ["noreply@vendor.com"], reason="no_email")
    drop = _manual("m1", "noreply@vendor.com", "2026-08-16T00:00:00Z", "not_a_deal")
    deals = build_deals([demo, drop], {}, TODAY)
    assert deals == {}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_deal_fold.py -k "manual_confirm or choose_primary or not_a_deal" -v`
Expected: FAIL.

- [ ] **Step 3: Apply manual actions**

Add locals before the per-event loop: `manual_resolved = False`, `chosen_primary = ""`, `dropped = False`. In the loop, add a `manual` branch:

```python
            if e.kind == "manual":
                act = e.payload.get("action")
                if act in ("confirm", "choose_primary", "merge", "split"):
                    manual_resolved = True
                if act == "choose_primary":
                    chosen_primary = e.payload.get("primary_email", "") or chosen_primary
                if act == "not_a_deal":
                    dropped = True
```

After the loop, re-key if a primary was chosen (do this before computing `account_name`, since it depends on `email`):

```python
        if chosen_primary:
            email = chosen_primary
            d.email = email
```

Make the ambiguous branch respect resolution — change its guard:

```python
        elif ambiguous_reason and not manual_resolved:
            d.review = {...}
```

Finally, skip dropped deals when assembling the result. Change the tail:

```python
        if dropped:
            continue
        deals[email] = d
```

- [ ] **Step 4: Run the full fold suite**

Run: `python -m pytest tests/test_deal_fold.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat(deals): apply manual confirm/choose_primary/not_a_deal"
```

---

## Task 6: Apply `manual` events — merge and split

`merge` forces two emails into one component even when no shared contact links them (Queue A's "merge into existing"). `split` forces named email groups into separate deals even though the fold would union them. Both must be derived in the fold (never by rewriting the append-only log), and both must be order-independent.

**Files:**
- Modify: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py`

**Interfaces:**
- Consumes: `manual` `{"action":"merge","merge_with":"<email>"}` and `{"action":"split","groups":[["a@x"],["b@x"]]}`.
- Produces: `_group_components(events)` honors merge edges and split partitions; `merge` → the two deals fold into one; `split` → the named emails become separate deals.

- [ ] **Step 1: Write the failing tests**

```python
def test_manual_merge_joins_two_unlinked_deals():
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com"])
    e2 = _demo("d2", "bob@beta.com", "2026-08-12T00:00:00Z", ["bob@beta.com"])
    merge = _manual("m1", "bob@beta.com", "2026-08-13T00:00:00Z", "merge", merge_with="jane@acme.com")
    deals = build_deals([e1, e2, merge], {}, TODAY)
    assert len(deals) == 1
    d = list(deals.values())[0]
    assert set(d.contact_emails) >= {"jane@acme.com", "bob@beta.com"}


def test_manual_split_separates_a_merged_component():
    # shared contact would union these; split forces two deals
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com", "shared@acme.com"])
    e2 = _demo("d2", "bob@acme.com", "2026-08-12T00:00:00Z", ["bob@acme.com", "shared@acme.com"])
    split = _manual("m1", "jane@acme.com", "2026-08-13T00:00:00Z", "split",
                    groups=[["jane@acme.com"], ["bob@acme.com"]])
    deals = build_deals([e1, e2, split], {}, TODAY)
    assert set(deals) == {"jane@acme.com", "bob@acme.com"}


def test_merge_and_split_are_order_independent():
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com"])
    e2 = _demo("d2", "bob@beta.com", "2026-08-12T00:00:00Z", ["bob@beta.com"])
    merge = _manual("m1", "bob@beta.com", "2026-08-13T00:00:00Z", "merge", merge_with="jane@acme.com")
    assert list(build_deals([e1, e2, merge], {}, TODAY)) == list(build_deals([merge, e2, e1], {}, TODAY))
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_deal_fold.py -k "manual_merge or manual_split or merge_and_split" -v`
Expected: FAIL.

- [ ] **Step 3: Feed merge edges and split partitions into `_group_components`**

Extend `_group_components` to read `manual` events. After the demo-edge loop and before bucketing, add:

```python
    # Manual merge edges (force-join two keys).
    for e in events:
        if e.kind == "manual" and e.payload.get("action") == "merge":
            other = e.payload.get("merge_with")
            if e.email and other:
                find(e.email); find(other)
                union(e.email, other)
```

Splits can't be expressed as union edges (you can't un-union), so apply them as a post-pass that re-partitions a component. After bucketing into `buckets` and before the return, add:

```python
    # Collect split directives: email -> group index within its split set.
    split_groups: list[list[str]] = []
    for e in events:
        if e.kind == "manual" and e.payload.get("action") == "split":
            groups = e.payload.get("groups") or []
            if groups:
                split_groups.append([str(x) for grp in groups for x in grp])  # affected emails
    # Build a map affected_email -> canonical split-subkey.
    split_assign: dict[str, str] = {}
    for e in events:
        if e.kind == "manual" and e.payload.get("action") == "split":
            for grp in (e.payload.get("groups") or []):
                grp_norm = sorted(str(x) for x in grp)
                subkey = grp_norm[0] if grp_norm else ""
                for x in grp_norm:
                    split_assign[x] = subkey

    if split_assign:
        rebucketed: dict[str, list] = {}
        for root, evs in buckets.items():
            for ev in evs:
                key = split_assign.get(ev.email, root)
                rebucketed.setdefault(key, []).append(ev)
        buckets = rebucketed

    return [buckets[root] for root in sorted(buckets)]
```

(Delete the earlier `return [...]` line so only this final one remains.)

- [ ] **Step 4: Run the full fold suite**

Run: `python -m pytest tests/test_deal_fold.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat(deals): apply manual merge/split via component grouping"
```

---

## Task 7: Read-model — `build_deals_to_review(deals)`

A pure function that turns folded deals into the two render-ready queues consumed by Plan b's UI and the email brief. No filtering logic beyond `review.needs`; the shaping (fields the card needs) lives here so both surfaces agree.

**Files:**
- Modify: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py`

**Interfaces:**
- Consumes: `dict[str, Deal]` from `build_deals`.
- Produces: `build_deals_to_review(deals) -> dict` of shape:

```python
{
  "identity": [ {"deal_key","account_name","rep","reason","proposed","contact_emails","demo_date"} ],
  "stale":    [ {"deal_key","account_name","rep","cycle_start","last_event_at","check_back"} ],
  "counts":   {"identity": int, "stale": int, "total": int},
}
```

- [ ] **Step 1: Write the failing test**

```python
from lib.deal_fold import build_deals_to_review


def test_build_deals_to_review_splits_two_queues():
    ambiguous = _demo("d1", "x@acme.com", "2026-08-15T00:00:00Z", ["x@acme.com"], reason="free_email")
    stale = _demo("d2", "y@beta.com", "2026-06-01T00:00:00Z", ["y@beta.com"])
    clean = _demo("d3", "z@gamma.com", "2026-08-17T00:00:00Z", ["z@gamma.com"])
    deals = build_deals([ambiguous, stale, clean], {}, TODAY)
    review = build_deals_to_review(deals)
    assert review["counts"] == {"identity": 1, "stale": 1, "total": 2}
    assert review["identity"][0]["deal_key"] == "x@acme.com"
    assert review["identity"][0]["reason"] == "free_email"
    assert review["stale"][0]["deal_key"] == "y@beta.com"
    # clean deal appears in neither queue
    keys = {r["deal_key"] for r in review["identity"] + review["stale"]}
    assert "z@gamma.com" not in keys


def test_build_deals_to_review_is_deterministically_ordered():
    a = _demo("d1", "b@x.com", "2026-08-15T00:00:00Z", ["b@x.com"], reason="free_email")
    b = _demo("d2", "a@x.com", "2026-08-15T00:00:00Z", ["a@x.com"], reason="free_email")
    review = build_deals_to_review(build_deals([a, b], {}, TODAY))
    assert [r["deal_key"] for r in review["identity"]] == ["a@x.com", "b@x.com"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_deal_fold.py -k build_deals_to_review -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement the builder**

Append to `lib/deal_fold.py`:

```python
def build_deals_to_review(deals: dict) -> dict:
    """Shape folded deals into the identity + 45-day review queues. Pure."""
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
```

- [ ] **Step 4: Run the full fold suite**

Run: `python -m pytest tests/test_deal_fold.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat(deals): build_deals_to_review read-model for the two queues"
```

---

## Task 8: Validate against real folded demos

Prove the extended fold on the real `data/deal_events.jsonl` (which already contains a `free_email` case) plus a hand-added `status`/`manual` event, with a throwaway script. No test file — this is an inspection gate before Plan b builds the UI on top.

**Files:**
- None committed. Use a scratch script.

- [ ] **Step 1: Fold the real event log and print the review queues**

Run:

```bash
python -c "
from lib.storage import registry_storage
from lib.deal_events import load_events
from lib.deal_crosswalk import load_crosswalk
from lib.deal_fold import build_deals, build_deals_to_review
import json
s = registry_storage({})
deals = build_deals(load_events(s), load_crosswalk(s), '2026-08-19')
print(json.dumps(build_deals_to_review(deals), indent=2, default=str))
"
```

Expected: JSON with the real `jcook.tpa@gmail.com` deal in the `identity` queue with `reason == "free_email"`, and `counts.total >= 1`.

- [ ] **Step 2: Confirm order-independence on real data**

Run:

```bash
python -c "
import random
from lib.storage import registry_storage
from lib.deal_events import load_events
from lib.deal_crosswalk import load_crosswalk
from lib.deal_fold import build_deals
s = registry_storage({}); evs = load_events(s); cw = load_crosswalk(s)
a = build_deals(list(evs), cw, '2026-08-19')
random.shuffle(evs)
b = build_deals(list(evs), cw, '2026-08-19')
assert sorted(a) == sorted(b), 'ORDER-DEPENDENT!'
print('order-independent OK; deals:', sorted(a))
"
```

Expected: prints `order-independent OK` and the deal keys.

- [ ] **Step 3: No commit** (validation only). Record the observed counts in the Plan b handoff.

---

## Self-Review

- **Spec coverage:** §3.10 status events (lost/hold/active) → Tasks 3–4; manual events (confirm/choose/merge/split/not-a-deal) → Tasks 5–6; cross-demo merge + `account_conflict` → Task 2; read model (`build_deals_to_review`, filter `review.needs`) → Task 7; real-data validation → Task 8. The `deals_to_review` *surfacing* (Today tab, endpoints, UI) is Plan b, by design.
- **Order-independence:** covered by dedicated tests in Tasks 2, 4, 6 and real-data check in Task 8.
- **Never auto-Lost:** Task 3 only sets `lost` from an explicit `status` event; Task 4's stale branch only *flags*.
- **Type consistency:** `_group_components`/`_canonical_key` names used identically across Tasks 1, 6; `build_deals_to_review` output shape defined once (Task 7) and consumed by Plan b.
