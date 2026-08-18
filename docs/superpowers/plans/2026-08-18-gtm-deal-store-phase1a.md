# GTM Deal Store — Phase 1a (Demo Spine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the producer-side deal data layer: collect demo facts, resolve them into a clean email-keyed deal record, project into the existing `pipeline_cache.json`, and push directly to OS-Metric-Sync.

**Architecture:** Append-only `data/deal_events.jsonl` (git-anchored, like `tasks.jsonl`) holds `DealEvent`s; `build_deals()` folds them per normalized email into current deals. The fold output is projected into `pipeline_cache.json` (unchanged shape → all existing consumers untouched) and pushed to OMS `/api/deals/ingest`. Notion is removed from the data path. Demo-event emission rides the existing nightly `avoma_sync.py` (reuses its analyzed transcripts — no second Claude pass).

**Tech Stack:** Python 3.11, pytest, `requests`, `lib.storage` (LocalStorage via `registry_storage`), existing `collectors/avoma.py`.

**Spec:** `docs/superpowers/specs/2026-08-18-gtm-deal-store-phase1a-design.md`

## Global Constraints

- Python 3.11 (the `avoma_sync.yml` runner).
- Registry files (`deal_events.jsonl`, `deal_crosswalk.json`) MUST be accessed via `lib.storage.registry_storage(config)` (a `LocalStorage` on the working tree), never `build_storage`/R2. Storage keys strip the `data/` prefix (e.g. key `"deal_events.jsonl"` → `data/deal_events.jsonl`).
- Storage API (from `lib/storage.py`): `read(key)->str|None`, `write(key,str)`, `append_line(key,str)`, `read_json(key,default)`, `write_json(key,data)`, `exists(key)`.
- `deal_events.jsonl` gets the `merge=union` git driver like `tasks.jsonl`.
- All new registry files must be added to the `.gitignore` un-ignore allow-list AND the `avoma_sync.yml` commit-back `git add` list.
- No `Date.now()`/`random` nondeterminism in pure functions — pass `today`/timestamps in.
- The internal domain to filter is `@teambuildr.com`.
- Every push/IO to external systems is non-fatal (never raises up the orchestration).
- TDD throughout; commit after each green task.

---

### Task 1: Email normalization

**Files:**
- Create: `lib/email_norm.py`
- Test: `tests/test_email_norm.py`

**Interfaces:**
- Produces: `normalize_email(raw: str | None) -> str | None` — lowercased, trimmed, `+tag` stripped, `@teambuildr.com` and malformed/empty → `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_norm.py
from lib.email_norm import normalize_email


def test_lowercases_and_trims():
    assert normalize_email("  Coach@Acme.com ") == "coach@acme.com"


def test_strips_plus_tags():
    assert normalize_email("jane+demo@acme.com") == "jane@acme.com"


def test_drops_internal_domain():
    assert normalize_email("trent@teambuildr.com") is None


def test_rejects_empty_and_malformed():
    assert normalize_email("") is None
    assert normalize_email(None) is None
    assert normalize_email("not-an-email") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_email_norm.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.email_norm'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/email_norm.py
"""Normalize a raw email into a deal join key, or None if unusable."""
from __future__ import annotations

_INTERNAL_DOMAIN = "@teambuildr.com"


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    e = raw.strip().lower()
    if "@" not in e:
        return None
    local, _, domain = e.partition("@")
    local = local.split("+", 1)[0]
    if not local or not domain:
        return None
    norm = f"{local}@{domain}"
    if norm.endswith(_INTERNAL_DOMAIN):
        return None
    return norm
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_email_norm.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/email_norm.py tests/test_email_norm.py
git commit -m "feat(deals): email normalization for deal keys"
```

---

### Task 2: Deal event store

**Files:**
- Create: `lib/deal_events.py`
- Test: `tests/test_deal_events.py`

**Interfaces:**
- Consumes: storage API (Task Global Constraints).
- Produces:
  - `DealEvent` dataclass: `event_id, email, email_raw, kind, timestamp, account_name="", rep="", source="", payload: dict`.
  - `make_event_id(kind: str, native_id: str, email: str) -> str` — deterministic 16-char hash.
  - `append_events(storage, events: list[DealEvent], key="deal_events.jsonl") -> int` — appends only unseen `event_id`s; returns count appended.
  - `load_events(storage, key="deal_events.jsonl") -> list[DealEvent]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deal_events.py
from lib.storage import LocalStorage
from lib.deal_events import DealEvent, make_event_id, append_events, load_events


def _store(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_make_event_id_is_deterministic():
    a = make_event_id("demo", "uuid-1", "x@acme.com")
    b = make_event_id("demo", "uuid-1", "x@acme.com")
    c = make_event_id("demo", "uuid-2", "x@acme.com")
    assert a == b and a != c and len(a) == 16


def test_append_is_idempotent_by_event_id(tmp_path):
    s = _store(tmp_path)
    e = DealEvent(event_id="e1", email="x@acme.com", email_raw="X@acme.com",
                  kind="demo", timestamp="2026-08-01T10:00:00Z")
    assert append_events(s, [e]) == 1
    assert append_events(s, [e]) == 0          # re-append is a no-op
    loaded = load_events(s)
    assert len(loaded) == 1 and loaded[0].email == "x@acme.com"
    assert loaded[0].kind == "demo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deal_events.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.deal_events'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/deal_events.py
"""Append-only DealEvent log. Deals are derived by folding these events."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

_KEY = "deal_events.jsonl"


@dataclass
class DealEvent:
    event_id: str
    email: str
    email_raw: str
    kind: str  # demo | trial | sale | status | manual
    timestamp: str  # ISO 8601
    account_name: str = ""
    rep: str = ""
    source: str = ""
    payload: dict = field(default_factory=dict)


def make_event_id(kind: str, native_id: str, email: str) -> str:
    raw = f"{kind}|{native_id}|{email}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_events(storage, key: str = _KEY) -> list[DealEvent]:
    content = storage.read(key) or ""
    events: list[DealEvent] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(DealEvent(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return events


def append_events(storage, events: list[DealEvent], key: str = _KEY) -> int:
    seen = {e.event_id for e in load_events(storage, key)}
    appended = 0
    for e in events:
        if e.event_id in seen:
            continue
        storage.append_line(key, json.dumps(asdict(e)))
        seen.add(e.event_id)
        appended += 1
    return appended
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deal_events.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/deal_events.py tests/test_deal_events.py
git commit -m "feat(deals): append-only deal event store"
```

---

### Task 3: Crosswalk + account naming

**Files:**
- Create: `lib/deal_crosswalk.py`
- Test: `tests/test_deal_crosswalk.py`

**Interfaces:**
- Consumes: storage API.
- Produces:
  - `domain_to_name(email: str) -> str` — placeholder account name from the email domain (e.g. `michael.hine@port-vale.co.uk` → `"Port Vale"`).
  - `load_crosswalk(storage, key="deal_crosswalk.json") -> dict[str, str]` — manual email→account overrides.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deal_crosswalk.py
from lib.storage import LocalStorage
from lib.deal_crosswalk import domain_to_name, load_crosswalk


def test_domain_to_name():
    assert domain_to_name("michael.hine@port-vale.co.uk") == "Port Vale"
    assert domain_to_name("a@acme.com") == "Acme"


def test_load_crosswalk_defaults_empty(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    assert load_crosswalk(s) == {}


def test_load_crosswalk_reads_overrides(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write_json("deal_crosswalk.json", {"a@acme.com": "Acme Barbell Co"})
    assert load_crosswalk(s)["a@acme.com"] == "Acme Barbell Co"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deal_crosswalk.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.deal_crosswalk'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/deal_crosswalk.py
"""email <-> account_name crosswalk (derived + manual overrides)."""
from __future__ import annotations

_KEY = "deal_crosswalk.json"


def domain_to_name(email: str) -> str:
    if "@" not in email:
        return ""
    domain = email.split("@", 1)[1]
    core = domain.split(".")[0] if "." in domain else domain
    return core.replace("-", " ").replace("_", " ").title()


def load_crosswalk(storage, key: str = _KEY) -> dict:
    return storage.read_json(key, default={}) or {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deal_crosswalk.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/deal_crosswalk.py tests/test_deal_crosswalk.py
git commit -m "feat(deals): email<->account crosswalk + domain naming"
```

---

### Task 4: Demo event normalizer (multi-email auto path)

**Files:**
- Create: `lib/deal_normalize.py`
- Test: `tests/test_deal_normalize.py`

**Interfaces:**
- Consumes: `normalize_email` (Task 1); `DealEvent`, `make_event_id` (Task 2); `AvomaTranscript.attendees` (already `[{name,email}]` from Phase 0).
- Produces: `normalize_demo_events(transcripts: list) -> list[DealEvent]`. One demo event per demo transcript, keyed by a primary prospect email (or `"unresolved:<uuid>"` when none). `payload = {avoma_uuid, contact_emails, ambiguous_reason, title}`; `ambiguous_reason ∈ {None, "multi_domain", "no_email", "generic_inbox"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deal_normalize.py
from dataclasses import dataclass, field
from lib.deal_normalize import normalize_demo_events


@dataclass
class T:
    uuid: str; title: str; start_at: str; call_type: str; os_interested: bool
    rep_name: str = ""; attendees: list = field(default_factory=list)


def _demo(uuid, attendees, ct="demo", os=True):
    return T(uuid, "Demo", "2026-08-10T15:00:00Z", ct, os, "Luke Martin", attendees)


def test_clean_single_domain_demo():
    ev = normalize_demo_events([_demo("u1", [
        {"name": "Ryan Allwein", "email": "ryan@teambuildr.com"},
        {"name": "Jane", "email": "jane@acme.com"},
        {"name": "Bob", "email": "bob@acme.com"},
    ])])[0]
    assert ev.kind == "demo" and ev.email == "jane@acme.com"
    assert ev.rep == "Luke Martin"
    assert ev.payload["contact_emails"] == ["jane@acme.com", "bob@acme.com"]
    assert ev.payload["ambiguous_reason"] is None


def test_multi_domain_flags_reason():
    ev = normalize_demo_events([_demo("u2", [
        {"name": "A", "email": "a@acme.com"},
        {"name": "B", "email": "b@other.com"},
    ])])[0]
    assert ev.payload["ambiguous_reason"] == "multi_domain"


def test_no_email_is_unresolved():
    ev = normalize_demo_events([_demo("u3", [{"name": "NoEmail Guy", "email": ""}])])[0]
    assert ev.email == "unresolved:u3"
    assert ev.payload["ambiguous_reason"] == "no_email"


def test_generic_inbox_flagged():
    ev = normalize_demo_events([_demo("u4", [{"name": "Front Desk", "email": "info@acme.com"}])])[0]
    assert ev.payload["ambiguous_reason"] == "generic_inbox"


def test_non_demo_and_non_os_skipped():
    assert normalize_demo_events([
        _demo("u5", [{"name": "X", "email": "x@acme.com"}], ct="follow_up"),
        _demo("u6", [{"name": "Y", "email": "y@acme.com"}], os=False),
    ]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deal_normalize.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.deal_normalize'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/deal_normalize.py
"""Turn analyzed Avoma demo transcripts into email-keyed DealEvents."""
from __future__ import annotations

from lib.deal_events import DealEvent, make_event_id
from lib.email_norm import normalize_email

_GENERIC_LOCALS = {"info", "sales", "office", "admin", "contact", "hello", "team", "support"}


def _domain(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else ""


def normalize_demo_events(transcripts: list) -> list[DealEvent]:
    events: list[DealEvent] = []
    for t in transcripts:
        if getattr(t, "call_type", "") != "demo" or not getattr(t, "os_interested", False):
            continue
        uuid = getattr(t, "uuid", "")
        prospects: list[str] = []
        for a in getattr(t, "attendees", []) or []:
            ne = normalize_email(a.get("email"))
            if ne and ne not in prospects:
                prospects.append(ne)

        reason = None
        if not prospects:
            reason = "no_email"
            primary = f"unresolved:{uuid}"
        else:
            if len({_domain(e) for e in prospects}) > 1:
                reason = "multi_domain"
            elif all(e.split("@", 1)[0] in _GENERIC_LOCALS for e in prospects):
                reason = "generic_inbox"
            primary = prospects[0]

        events.append(DealEvent(
            event_id=make_event_id("demo", uuid, primary),
            email=primary,
            email_raw="",
            kind="demo",
            timestamp=getattr(t, "start_at", ""),
            account_name="",
            rep=getattr(t, "rep_name", "") or "",
            source="avoma",
            payload={
                "avoma_uuid": uuid,
                "contact_emails": prospects,
                "ambiguous_reason": reason,
                "title": getattr(t, "title", ""),
            },
        ))
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deal_normalize.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/deal_normalize.py tests/test_deal_normalize.py
git commit -m "feat(deals): demo event normalizer with multi-email auto path"
```

---

### Task 5: Fold events into deals

**Files:**
- Create: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py`

**Interfaces:**
- Consumes: `DealEvent` (Task 2); `domain_to_name` (Task 3).
- Produces:
  - `Deal` dataclass: `email, account_name, rep, demo_date, trial_start_date, cycle_start, close_date, outcome, stage, contact_emails, source, deal_value, lost_reason, provenance, review, last_event_at`.
  - `build_deals(events: list[DealEvent], crosswalk: dict, today: str, stale_days: int = 45) -> dict[str, Deal]`. Groups by `email`; demo folding is order-independent. `outcome="open"`, `stage="demoed"` in Phase 1a. `review` = `{needs, kind, reason, proposed}` (`kind ∈ {ambiguous, stale_check}`). (Status/manual event application is added in Phase 1b.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deal_fold.py
from lib.deal_events import DealEvent
from lib.deal_fold import build_deals

TODAY = "2026-08-18"


def _demo(uuid, email, ts, contacts, reason=None, rep="Luke Martin"):
    return DealEvent(event_id=uuid, email=email, email_raw="", kind="demo", timestamp=ts,
                     rep=rep, source="avoma",
                     payload={"avoma_uuid": uuid, "contact_emails": contacts, "ambiguous_reason": reason})


def test_dedup_by_email_takes_earliest_demo_date():
    events = [_demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"]),
              _demo("b", "x@acme.com", "2026-08-02T00:00:00Z", ["x@acme.com", "y@acme.com"])]
    deals = build_deals(events, {}, TODAY)
    assert set(deals) == {"x@acme.com"}
    d = deals["x@acme.com"]
    assert d.demo_date == "2026-08-02T00:00:00Z"
    assert d.cycle_start == "2026-08-02T00:00:00Z"
    assert d.outcome == "open" and d.stage == "demoed"
    assert "y@acme.com" in d.contact_emails


def test_fold_is_order_independent():
    e1 = _demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"])
    e2 = _demo("b", "x@acme.com", "2026-08-02T00:00:00Z", ["x@acme.com"])
    assert build_deals([e1, e2], {}, TODAY)["x@acme.com"].demo_date == \
           build_deals([e2, e1], {}, TODAY)["x@acme.com"].demo_date


def test_ambiguous_reason_sets_identity_review():
    d = build_deals([_demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"], reason="multi_domain")], {}, TODAY)["x@acme.com"]
    assert d.review["needs"] is True and d.review["kind"] == "ambiguous"
    assert d.review["reason"] == "multi_domain"


def test_aged_open_deal_sets_stale_review():
    d = build_deals([_demo("a", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])], {}, TODAY, stale_days=45)["x@acme.com"]
    assert d.review["needs"] is True and d.review["kind"] == "stale_check"


def test_recent_clean_deal_needs_no_review():
    d = build_deals([_demo("a", "x@acme.com", "2026-08-15T00:00:00Z", ["x@acme.com"])], {}, TODAY)["x@acme.com"]
    assert d.review["needs"] is False


def test_account_name_from_crosswalk_then_domain():
    deals = build_deals([_demo("a", "x@acme.com", "2026-08-15T00:00:00Z", ["x@acme.com"])],
                        {"x@acme.com": "Acme Barbell"}, TODAY)
    assert deals["x@acme.com"].account_name == "Acme Barbell"
    deals2 = build_deals([_demo("b", "y@acme.com", "2026-08-15T00:00:00Z", ["y@acme.com"])], {}, TODAY)
    assert deals2["y@acme.com"].account_name == "Acme"


def test_unresolved_key_has_blank_account():
    d = build_deals([_demo("u1", "unresolved:u1", "2026-08-15T00:00:00Z", [], reason="no_email")], {}, TODAY)["unresolved:u1"]
    assert d.account_name == ""
    assert d.review["kind"] == "ambiguous"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deal_fold.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.deal_fold'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/deal_fold.py
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


def build_deals(events: list, crosswalk: dict, today: str, stale_days: int = 45) -> dict:
    by_email: dict[str, list] = {}
    for e in events:
        by_email.setdefault(e.email, []).append(e)

    deals: dict[str, Deal] = {}
    for email, evs in by_email.items():
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
        d.cycle_start = d.demo_date  # min(trial, demo) == demo in Phase 1a
        d.outcome = "open"
        d.stage = "demoed"
        d.account_name = "" if email.startswith("unresolved:") else (crosswalk.get(email) or domain_to_name(email))

        if ambiguous_reason:
            d.review = {"needs": True, "kind": "ambiguous", "reason": ambiguous_reason,
                        "proposed": {"email": email, "account_name": d.account_name, "rep": d.rep}}
        elif d.cycle_start and _days_since(d.cycle_start, today) >= stale_days:
            d.review = {"needs": True, "kind": "stale_check", "reason": "aged_%dd" % stale_days}
        else:
            d.review = {"needs": False}

        deals[email] = d
    return deals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deal_fold.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat(deals): fold events into email-keyed deals with review flags"
```

---

### Task 6: Projection to pipeline_cache.json (the seam)

**Files:**
- Create: `lib/deal_projection.py`
- Test: `tests/test_deal_projection.py`

**Interfaces:**
- Consumes: `Deal` (Task 5).
- Produces: `deals_to_pipeline_cache(deals: dict, fetched_at: str) -> dict` emitting the **current cache schema**: `{fetched_at, leads:[{page_id, name, contact, email, status, priority, last_contacted, days_since_contact, estimated_value, source, stale}]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deal_projection.py
from lib.deal_fold import Deal
from lib.deal_projection import deals_to_pipeline_cache

_CACHE_LEAD_KEYS = {"page_id", "name", "contact", "email", "status", "priority",
                    "last_contacted", "days_since_contact", "estimated_value", "source", "stale"}


def test_projection_matches_cache_schema():
    d = Deal(email="x@acme.com", account_name="Acme", rep="Luke Martin",
             demo_date="2026-08-10T00:00:00Z", cycle_start="2026-08-10T00:00:00Z",
             stage="demoed", contact_emails=["x@acme.com"], last_event_at="2026-08-10T00:00:00Z",
             review={"needs": False})
    out = deals_to_pipeline_cache({"x@acme.com": d}, "2026-08-18T00:00:00Z")
    assert out["fetched_at"] == "2026-08-18T00:00:00Z"
    lead = out["leads"][0]
    assert set(lead.keys()) == _CACHE_LEAD_KEYS
    assert lead["page_id"] == "deal:x@acme.com"
    assert lead["name"] == "Acme" and lead["email"] == "x@acme.com"
    assert lead["status"] == "demoed" and lead["stale"] is False


def test_stale_review_maps_to_stale_flag():
    d = Deal(email="x@acme.com", stage="demoed", review={"needs": True, "kind": "stale_check"})
    assert deals_to_pipeline_cache({"x@acme.com": d}, "t")["leads"][0]["stale"] is True


def test_unresolved_key_blanks_email():
    d = Deal(email="unresolved:u1", stage="demoed", review={"needs": True, "kind": "ambiguous"})
    lead = deals_to_pipeline_cache({"unresolved:u1": d}, "t")["leads"][0]
    assert lead["email"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deal_projection.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.deal_projection'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/deal_projection.py
"""Project derived deals into today's pipeline_cache.json shape (the seam)."""
from __future__ import annotations


def deals_to_pipeline_cache(deals: dict, fetched_at: str) -> dict:
    leads = []
    for email, d in deals.items():
        review = d.review or {}
        leads.append({
            "page_id": f"deal:{email}",
            "name": d.account_name,
            "contact": d.contact_emails[0] if d.contact_emails else "",
            "email": "" if email.startswith("unresolved:") else email,
            "status": d.stage,
            "priority": None,
            "last_contacted": d.last_event_at,
            "days_since_contact": None,
            "estimated_value": d.deal_value,
            "source": d.source,
            "stale": bool(review.get("needs") and review.get("kind") == "stale_check"),
        })
    return {"fetched_at": fetched_at, "leads": leads}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deal_projection.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/deal_projection.py tests/test_deal_projection.py
git commit -m "feat(deals): project deals into pipeline_cache.json shape"
```

---

### Task 7: OMS push transport

**Files:**
- Modify: `lib/metrics_client.py` (add `push_deals` after `push_demos`, ~line 90)
- Test: `tests/test_push_deals.py`

**Interfaces:**
- Produces: `push_deals(base_url: str, password: str, deals: list[dict], timeout: int = 60) -> dict` — `POST {base_url}/api/deals/ingest` with body `{"deals": deals}`, basic auth `("", password)`. Never raises; returns parsed JSON or `{"status":"error","error":...}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_push_deals.py
from unittest.mock import patch, MagicMock
from lib.metrics_client import push_deals


def test_push_deals_posts_to_ingest_and_returns_json():
    with patch("lib.metrics_client.requests.post") as mp:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"inserted": 2, "updated": 0}
        mp.return_value = resp
        out = push_deals("https://engine.example", "pw", [{"email": "x@acme.com"}])
    assert out == {"inserted": 2, "updated": 0}
    args, kwargs = mp.call_args
    assert args[0] == "https://engine.example/api/deals/ingest"
    assert kwargs["json"] == {"deals": [{"email": "x@acme.com"}]}
    assert kwargs["auth"] == ("", "pw")


def test_push_deals_is_non_fatal_on_error():
    import requests
    with patch("lib.metrics_client.requests.post", side_effect=requests.RequestException("down")):
        out = push_deals("https://engine.example", "pw", [{"email": "x@acme.com"}])
    assert out["status"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_push_deals.py -q`
Expected: FAIL — `ImportError: cannot import name 'push_deals'`

- [ ] **Step 3: Write minimal implementation** — append to `lib/metrics_client.py`:

```python
def push_deals(base_url: str, password: str, deals: list[dict], timeout: int = 60) -> dict:
    """POST resolved deals to the engine /api/deals/ingest. Never raises."""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/deals/ingest",
            auth=("", password),
            json={"deals": deals},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️  Deal push failed (non-fatal): {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)[:200]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_push_deals.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/metrics_client.py tests/test_push_deals.py
git commit -m "feat(deals): push_deals transport to OMS /api/deals/ingest"
```

---

### Task 8: Deal-store composition (`refresh_deal_store`)

**Files:**
- Create: `lib/deal_sync.py`
- Test: `tests/test_deal_sync.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: `refresh_deal_store(transcripts, storage, today, fetched_at, stale_days=45, base_url="", password="") -> dict`. Normalizes demo events → appends → loads all → folds → **writes `pipeline_cache.json` via storage** → pushes to OMS if `base_url`. Returns `{"deals": N, "appended": M, "pushed": bool}`. Non-fatal on push.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deal_sync.py
from dataclasses import dataclass, field
from unittest.mock import patch
from lib.storage import LocalStorage
from lib.deal_sync import refresh_deal_store


@dataclass
class T:
    uuid: str; title: str; start_at: str; call_type: str; os_interested: bool
    rep_name: str = ""; attendees: list = field(default_factory=list)


def test_refresh_builds_events_cache_and_pushes(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    transcripts = [T("u1", "Demo", "2026-08-15T15:00:00Z", "demo", True, "Luke Martin",
                     [{"name": "Ryan Allwein", "email": "ryan@teambuildr.com"},
                      {"name": "Jane", "email": "jane@acme.com"}])]
    with patch("lib.deal_sync.push_deals", return_value={"inserted": 1}) as mp:
        out = refresh_deal_store(transcripts, s, today="2026-08-18",
                                 fetched_at="2026-08-18T00:00:00Z",
                                 base_url="https://engine", password="pw")
    assert out == {"deals": 1, "appended": 1, "pushed": True}
    cache = s.read_json("pipeline_cache.json")
    assert cache["leads"][0]["email"] == "jane@acme.com"
    assert cache["leads"][0]["status"] == "demoed"
    assert mp.call_count == 1


def test_refresh_is_idempotent_and_skips_push_without_base_url(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    transcripts = [T("u1", "Demo", "2026-08-15T15:00:00Z", "demo", True, "Luke Martin",
                     [{"name": "Jane", "email": "jane@acme.com"}])]
    refresh_deal_store(transcripts, s, "2026-08-18", "2026-08-18T00:00:00Z")
    out = refresh_deal_store(transcripts, s, "2026-08-18", "2026-08-18T00:00:00Z")
    assert out == {"deals": 1, "appended": 0, "pushed": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_deal_sync.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.deal_sync'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/deal_sync.py
"""Compose the deal store: demo events -> deals -> pipeline_cache + OMS push."""
from __future__ import annotations

import dataclasses

from lib.deal_crosswalk import load_crosswalk
from lib.deal_events import append_events, load_events
from lib.deal_fold import build_deals
from lib.deal_normalize import normalize_demo_events
from lib.deal_projection import deals_to_pipeline_cache
from lib.metrics_client import push_deals


def refresh_deal_store(transcripts, storage, today: str, fetched_at: str,
                       stale_days: int = 45, base_url: str = "", password: str = "") -> dict:
    appended = append_events(storage, normalize_demo_events(transcripts))
    events = load_events(storage)
    crosswalk = load_crosswalk(storage)
    deals = build_deals(events, crosswalk, today, stale_days=stale_days)

    storage.write_json("pipeline_cache.json", deals_to_pipeline_cache(deals, fetched_at))

    pushed = False
    if base_url:
        push_deals(base_url, password, [dataclasses.asdict(d) for d in deals.values()])
        pushed = True

    return {"deals": len(deals), "appended": appended, "pushed": pushed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_deal_sync.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add lib/deal_sync.py tests/test_deal_sync.py
git commit -m "feat(deals): refresh_deal_store composition"
```

---

### Task 9: Wire into avoma_sync + persistence config

**Files:**
- Modify: `scripts/avoma_sync.py` (after the demo-push block, ~line 307)
- Modify: `config.json` (add a `deals` config block)
- Modify: `.gitignore` (un-ignore the two new registry files)
- Modify: `.gitattributes` (merge driver for `deal_events.jsonl`)
- Modify: `.github/workflows/avoma_sync.yml` (commit-back `git add`)

**Interfaces:**
- Consumes: `refresh_deal_store` (Task 8), `registry_storage` (`lib.storage`).
- Produces: nightly deal-store refresh riding the existing Avoma run. No new exported symbols.

- [ ] **Step 1: Add the `deals` config block** to `config.json` (sibling of the existing `demos` block):

```json
  "deals": {
    "stale_days": 45
  },
```

- [ ] **Step 2: Un-ignore the new registry files** — add to `.gitignore` after line `!data/routines.json`:

```
!data/deal_events.jsonl
!data/deal_crosswalk.json
```

- [ ] **Step 3: Add the merge driver** — append to `.gitattributes`:

```
data/deal_events.jsonl merge=union
```

- [ ] **Step 4: Wire the refresh into `scripts/avoma_sync.py`** — immediately after the `except Exception as e: print("⚠️  Demo detection/push error ...")` block (the one ending ~line 307), insert:

```python
    # ── Refresh the email-keyed deal store (projection seam + OMS push) ──
    try:
        from lib.storage import registry_storage
        from lib.deal_sync import refresh_deal_store
        from datetime import datetime

        dstore = registry_storage(config)
        stale_days = config.get("deals", {}).get("stale_days", 45)
        summary = refresh_deal_store(
            transcripts, dstore, today=today,
            fetched_at=datetime.utcnow().isoformat() + "Z",
            stale_days=stale_days, base_url=base_url, password=password,
        )
        print(f"   Deal store: {summary}")
    except Exception as e:
        print(f"⚠️  Deal store refresh error (non-fatal): {e}", file=sys.stderr)
```

Note: `transcripts`, `today`, `base_url`, and `password` are already in scope from the demo-push block above.

- [ ] **Step 5: Add the new files to the workflow commit-back** — in `.github/workflows/avoma_sync.yml`, after the `git add data/notion_updates_queue.jsonl` line (line 46), add:

```yaml
          git add data/deal_events.jsonl 2>/dev/null || true
          git add data/deal_crosswalk.json 2>/dev/null || true
```

- [ ] **Step 6: Verify the whole suite is green**

Run: `python3 -m pytest tests/test_email_norm.py tests/test_deal_events.py tests/test_deal_crosswalk.py tests/test_deal_normalize.py tests/test_deal_fold.py tests/test_deal_projection.py tests/test_push_deals.py tests/test_deal_sync.py -q`
Expected: PASS (all deal-store tests green)

- [ ] **Step 7: Smoke-test the wiring locally** (no network — confirms imports + scope are correct)

Run:
```bash
python3 -c "import ast; ast.parse(open('scripts/avoma_sync.py').read()); print('avoma_sync.py parses OK')"
python3 -c "import json; json.load(open('config.json')); print('config.json valid')"
```
Expected: both print OK.

- [ ] **Step 8: Commit**

```bash
git add scripts/avoma_sync.py config.json .gitignore .gitattributes .github/workflows/avoma_sync.yml
git commit -m "feat(deals): wire deal store into nightly avoma_sync + persistence config"
```

---

## Post-implementation validation (before trusting metrics)

These are **not** code tasks — they're the real-data checks the spec (§5, §9) calls for, to run after the first live `avoma_sync` produces a `deal_events.jsonl`:

1. Inspect `data/pipeline_cache.json` after a run — confirm demo-derived deals look right (accounts, emails, stages).
2. Sample the `review.kind == "ambiguous"` deals — is the multi-email auto path picking sane primaries? Tune `_GENERIC_LOCALS` / the domain-collapse heuristic if not.
3. Confirm with OMS that `/api/deals/ingest` exists and the record shape matches (task t-78bb8e) **before** relying on the pushed data — until then the push returns `{"status":"error"}` harmlessly.

## Self-Review

- **Spec coverage:** event store (T2) ✓, email norm (T1) ✓, demo normalizer + multi-email auto path (T4) ✓, build_deals + review flags (T5) ✓, crosswalk (T3) ✓, projection seam (T6) ✓, push_deals (T7) ✓, orchestration/persistence (T8–T9) ✓. Phase 1b review-surface (Today-tab block, `/api/deals` endpoints, status/manual event application in the fold) is intentionally **out of scope** — separate plan.
- **Placeholders:** none — every step has real code/commands.
- **Type consistency:** `DealEvent` fields, `Deal` fields, `review` dict shape (`needs/kind/reason/proposed`), and `refresh_deal_store` return (`{deals,appended,pushed}`) are used identically across tasks and tests.
