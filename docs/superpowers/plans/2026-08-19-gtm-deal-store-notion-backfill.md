# Notion Backfill (seed import) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-shot import of the ~111 legacy Notion pipeline records into the event-sourced deal store as `seed` DealEvents, so the pipeline board and review surface reflect the whole pipeline.

**Architecture:** A pure status-mapper and a pure cache→events normalizer produce `seed` DealEvents; the fold learns to honor a seed's stage/outcome as ground truth for components with no real demo/trial/sale events (real events supersede); a thin one-shot script appends the events to the git-anchored `deal_events.jsonl`. No consumer is swapped — the board/review already fold this log.

**Tech Stack:** Python 3, `pytest`, the existing deal-store libs (`lib/deal_events.py`, `lib/email_norm.py`, `lib/deal_fold.py`, `lib/storage.py`).

**Spec:** `docs/superpowers/specs/2026-08-19-gtm-deal-store-notion-backfill-design.md`

## Global Constraints

- The fold stays **PURE and TOTAL** — no I/O, never raises on malformed events; read payloads via the existing `_payload(e)` helper / `.get(...)`.
- **Order-independence** is a hard invariant — shuffling the event list yields identical deals (the fold sorts each component's events by `(timestamp, event_id)`).
- **NEVER auto-Lost** — `outcome="lost"` comes only from an explicit `status`/lost event or a seed whose Notion status was `Lost`, never from fold heuristics.
- **Real signal wins:** a component with any real `demo`/`trial`/`sale` event derives stage from those; the seed only provides fallback `account_name`/`deal_value`.
- **Clean-slate stale clock:** open seed-only deals anchor their 45-day clock to the seed's `import_ts`; nothing surfaces on import day. Terminal (`won`/`lost`) seeds never surface for review.
- **Idempotent:** `event_id = make_event_id("seed", page_id, key)`; re-running the backfill appends nothing new.
- **Keying:** `normalize_email(email)` when present, else `notion:<page_id>`.
- Do not modify pre-existing tests. Reuse fixtures already in `tests/test_deal_fold.py`.
- The status map is EXACT over the 8 live Notion statuses (verbatim strings, including the Notion misspelling `"Out of Demo / Need Upate"`); unknown/blank → `("demoed", "open")`.

---

## File Structure

- `lib/deal_status_map.py` — **create.** `map_notion_status(status) -> (stage, outcome)`. Pure, no deps.
- `lib/deal_backfill.py` — **create.** `normalize_seed_events(leads, import_ts) -> list[DealEvent]`. Depends on `deal_events`, `email_norm`, `deal_status_map`.
- `lib/deal_events.py` — **modify** (one comment line: add `seed` to the kind vocab).
- `lib/deal_fold.py` — **modify.** `build_deals` learns `seed` handling; add the `outcome=="open"` guard to the stale branch.
- `scripts/backfill_deals.py` — **create.** Thin one-shot orchestrator with `--dry-run`.
- `tests/test_deal_status_map.py`, `tests/test_deal_backfill.py` — **create.**
- `tests/test_deal_fold.py` — **modify** (add a `_seed` fixture + seed tests; do not touch existing tests).

---

## Task 1: `map_notion_status` — Notion status → (stage, outcome)

**Files:**
- Create: `lib/deal_status_map.py`
- Test: `tests/test_deal_status_map.py`

**Interfaces:**
- Produces: `map_notion_status(status: str | None) -> tuple[str, str]` returning `(stage, outcome)` where `stage ∈ {demoed, in_trial, won, lost}` and `outcome ∈ {open, won, lost}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_deal_status_map.py
import pytest
from lib.deal_status_map import map_notion_status


@pytest.mark.parametrize("status,expected", [
    ("Demo Scheduled", ("demoed", "open")),
    ("No-Show", ("demoed", "open")),
    ("Out of Demo / Need Upate", ("demoed", "open")),  # Notion's spelling
    ("No Trial / Post Demo", ("demoed", "open")),
    ("On-Hold", ("demoed", "open")),
    ("In-Trial / Post Demo", ("in_trial", "open")),
    ("Closed", ("won", "won")),
    ("Lost", ("lost", "lost")),
])
def test_known_statuses(status, expected):
    assert map_notion_status(status) == expected


def test_unknown_and_blank_default_to_demoed_open():
    assert map_notion_status("Something New") == ("demoed", "open")
    assert map_notion_status("") == ("demoed", "open")
    assert map_notion_status(None) == ("demoed", "open")


def test_surrounding_whitespace_tolerated():
    assert map_notion_status("  Closed  ") == ("won", "won")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_deal_status_map.py -v`
Expected: FAIL (`ModuleNotFoundError: lib.deal_status_map`).

- [ ] **Step 3: Implement**

```python
# lib/deal_status_map.py
"""Map a Notion pipeline Status to the deal store's (stage, outcome)."""
from __future__ import annotations

_STATUS_MAP: dict[str, tuple[str, str]] = {
    "Demo Scheduled": ("demoed", "open"),
    "No-Show": ("demoed", "open"),
    "Out of Demo / Need Upate": ("demoed", "open"),  # Notion's own spelling
    "No Trial / Post Demo": ("demoed", "open"),
    "On-Hold": ("demoed", "open"),
    "In-Trial / Post Demo": ("in_trial", "open"),
    "Closed": ("won", "won"),
    "Lost": ("lost", "lost"),
}


def map_notion_status(status: str | None) -> tuple[str, str]:
    """Return (stage, outcome) for a Notion Status string. Unknown/blank ->
    ('demoed', 'open'). Total: never raises."""
    return _STATUS_MAP.get((status or "").strip(), ("demoed", "open"))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_deal_status_map.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add lib/deal_status_map.py tests/test_deal_status_map.py
git commit -m "feat(deals): map_notion_status -> (stage, outcome)"
```

---

## Task 2: `normalize_seed_events` — cache leads → seed DealEvents

**Files:**
- Create: `lib/deal_backfill.py`
- Modify: `lib/deal_events.py` (kind vocab comment)
- Test: `tests/test_deal_backfill.py`

**Interfaces:**
- Consumes: `DealEvent`, `make_event_id` (`lib/deal_events.py`); `normalize_email` (`lib/email_norm.py`); `map_notion_status` (Task 1).
- Produces: `normalize_seed_events(leads: list[dict], import_ts: str) -> list[DealEvent]`. Each event: `kind="seed"`, `source="notion-backfill"`, `email` = normalized email or `notion:<page_id>`, `timestamp` = `last_contacted` else `import_ts`, `account_name` = lead `name`, `payload = {stage, outcome, import_ts, estimated_value, source, priority, contact, page_id, last_contacted}`.

- [ ] **Step 1: Update the kind-vocab comment in `lib/deal_events.py`**

Change line 16 from:
```python
    kind: str  # demo | trial | sale | status | manual
```
to:
```python
    kind: str  # demo | trial | sale | status | manual | seed
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_deal_backfill.py
from lib.deal_backfill import normalize_seed_events

IMPORT_TS = "2026-08-19T12:00:00Z"


def _lead(**kw):
    base = {"page_id": "p1", "name": "Acme Barbell", "contact": "Jane Doe",
            "email": "jane@acme.com", "status": "In-Trial / Post Demo",
            "priority": "High", "last_contacted": "2026-06-24",
            "estimated_value": 2000, "source": "Calendly Demo"}
    base.update(kw)
    return base


def test_email_lead_keys_by_normalized_email():
    ev = normalize_seed_events([_lead()], IMPORT_TS)[0]
    assert ev.kind == "seed"
    assert ev.email == "jane@acme.com"
    assert ev.source == "notion-backfill"
    assert ev.account_name == "Acme Barbell"
    assert ev.timestamp == "2026-06-24"
    assert ev.payload["stage"] == "in_trial"
    assert ev.payload["outcome"] == "open"
    assert ev.payload["import_ts"] == IMPORT_TS
    assert ev.payload["estimated_value"] == 2000
    assert ev.payload["page_id"] == "p1"


def test_emailless_lead_keys_by_notion_page_id():
    ev = normalize_seed_events([_lead(email=None, name="Baxter Pattison")], IMPORT_TS)[0]
    assert ev.email == "notion:p1"
    assert ev.account_name == "Baxter Pattison"


def test_missing_last_contacted_falls_back_to_import_ts():
    ev = normalize_seed_events([_lead(last_contacted=None)], IMPORT_TS)[0]
    assert ev.timestamp == IMPORT_TS
    assert ev.payload["last_contacted"] is None


def test_event_id_is_deterministic_on_page_id_idempotent():
    a = normalize_seed_events([_lead()], IMPORT_TS)[0]
    b = normalize_seed_events([_lead()], "2099-01-01T00:00:00Z")[0]  # different import_ts
    assert a.event_id == b.event_id  # keyed on page_id + key, not import_ts


def test_closed_and_lost_map_to_terminal_outcomes():
    won = normalize_seed_events([_lead(status="Closed")], IMPORT_TS)[0]
    lost = normalize_seed_events([_lead(status="Lost")], IMPORT_TS)[0]
    assert won.payload["stage"] == "won" and won.payload["outcome"] == "won"
    assert lost.payload["stage"] == "lost" and lost.payload["outcome"] == "lost"


def test_lead_without_page_id_is_skipped_not_raised():
    out = normalize_seed_events([{"name": "No Id", "status": "Lost"}], IMPORT_TS)
    assert out == []
```

- [ ] **Step 3: Run to verify it fails**

Run: `python3 -m pytest tests/test_deal_backfill.py -v`
Expected: FAIL (`ModuleNotFoundError: lib.deal_backfill`).

- [ ] **Step 4: Implement**

```python
# lib/deal_backfill.py
"""Transform a pipeline_cache.json snapshot into `seed` DealEvents.

One-shot Notion backfill: each cache lead becomes one seed event carrying its
imported stage/outcome + provenance. Pure and total; keyed on the Notion
page_id so re-runs are idempotent on the fold."""
from __future__ import annotations

from lib.deal_events import DealEvent, make_event_id
from lib.deal_status_map import map_notion_status
from lib.email_norm import normalize_email


def normalize_seed_events(leads: list[dict], import_ts: str) -> list[DealEvent]:
    events: list[DealEvent] = []
    for lead in leads:
        page_id = lead.get("page_id")
        if not page_id:
            continue  # no stable id -> can't key or dedup; skip (caller counts)
        email = normalize_email(lead.get("email"))
        key = email or f"notion:{page_id}"
        stage, outcome = map_notion_status(lead.get("status"))
        last_contacted = lead.get("last_contacted") or None
        events.append(DealEvent(
            event_id=make_event_id("seed", str(page_id), key),
            email=key,
            email_raw=lead.get("email") or "",
            kind="seed",
            timestamp=last_contacted or import_ts,
            account_name=lead.get("name") or "",
            rep="",
            source="notion-backfill",
            payload={
                "stage": stage,
                "outcome": outcome,
                "import_ts": import_ts,
                "estimated_value": lead.get("estimated_value"),
                "source": lead.get("source"),
                "priority": lead.get("priority"),
                "contact": lead.get("contact") or "",
                "page_id": page_id,
                "last_contacted": last_contacted,
            },
        ))
    return events
```

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m pytest tests/test_deal_backfill.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 6: Commit**

```bash
git add lib/deal_backfill.py lib/deal_events.py tests/test_deal_backfill.py
git commit -m "feat(deals): normalize_seed_events (Notion cache -> seed events)"
```

---

## Task 3: Fold seed events in `build_deals`

**Files:**
- Modify: `lib/deal_fold.py`
- Test: `tests/test_deal_fold.py` (add a `_seed` fixture + new tests; DO NOT modify existing tests)

**Interfaces:**
- Consumes: `DealEvent` with `kind="seed"` and `payload = {stage, outcome, import_ts, estimated_value, ...}`.
- Produces: `build_deals` now folds seed-only components using the seed's stage/outcome; real demo/trial/sale events supersede; open seeds anchor the stale clock to `import_ts`; terminal `won`/`lost` never surface for review.

**Context:** Read `lib/deal_fold.py:172-300` (`build_deals`) first. You are adding one loop branch + a few locals, restructuring the post-loop stage/outcome derivation (currently `lib/deal_fold.py:236-242`), extending `effective_start`, and adding an `outcome=="open"` guard to the stale review branch (currently `lib/deal_fold.py:265`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_deal_fold.py` (append; reuse the module's existing `_demo` fixture and `TODAY`):

```python
def _seed(uuid, email, ts, stage, outcome, import_ts, account="", value=None):
    from lib.deal_events import DealEvent
    return DealEvent(event_id=uuid, email=email, email_raw="", kind="seed", timestamp=ts,
                     account_name=account, source="notion-backfill",
                     payload={"stage": stage, "outcome": outcome, "import_ts": import_ts,
                              "estimated_value": value})


def test_seed_only_deal_takes_seed_stage_and_outcome():
    # import today so the clean-slate clock keeps it off the stale queue
    d = build_deals([_seed("s1", "notion:p1", "2026-05-01", "in_trial", "open",
                            TODAY, account="Kim Johnston")], {}, TODAY)["notion:p1"]
    assert d.stage == "in_trial" and d.outcome == "open"
    assert d.account_name == "Kim Johnston"          # seed_account for a notion: key
    assert d.last_event_at == "2026-05-01"           # real last_contacted shown
    assert d.review["needs"] is False                # clean slate: not stale at import


def test_seed_won_and_lost_are_terminal_and_off_review():
    won = build_deals([_seed("s1", "notion:p1", "2025-01-01", "won", "won", TODAY)], {}, TODAY)["notion:p1"]
    lost = build_deals([_seed("s2", "notion:p2", "2025-01-01", "lost", "lost", TODAY)], {}, TODAY)["notion:p2"]
    assert won.outcome == "won" and won.stage == "won" and won.review["needs"] is False
    assert lost.outcome == "lost" and lost.stage == "lost" and lost.review["needs"] is False


def test_seed_clean_slate_goes_stale_after_import_plus_45d():
    # import_ts 60 days before today -> now stale (post-import inactivity)
    d = build_deals([_seed("s1", "notion:p1", "2026-01-01", "demoed", "open",
                            "2026-06-20")], {}, TODAY, stale_days=45)["notion:p1"]
    assert d.review["needs"] is True and d.review["kind"] == "stale_check"


def test_real_demo_supersedes_seed_stage_on_same_email():
    seed = _seed("s1", "jane@acme.com", "2026-05-01", "won", "won", TODAY, account="Old Name")
    demo = _demo("d1", "jane@acme.com", "2026-08-15T00:00:00Z", ["jane@acme.com"])
    d = build_deals([seed, demo], {}, TODAY)["jane@acme.com"]
    assert d.stage == "demoed" and d.outcome == "open"   # real demo wins
    assert d.demo_date == "2026-08-15T00:00:00Z"


def test_seed_value_fills_deal_value():
    d = build_deals([_seed("s1", "notion:p1", "2026-08-01", "demoed", "open", TODAY, value=2000)], {}, TODAY)["notion:p1"]
    assert d.deal_value == 2000


def test_seed_fold_is_order_independent():
    a = _seed("s1", "notion:p1", "2026-05-01", "in_trial", "open", TODAY)
    b = _seed("s2", "notion:p2", "2025-01-01", "lost", "lost", TODAY)
    fwd = build_deals([a, b], {}, TODAY)
    bwd = build_deals([b, a], {}, TODAY)
    assert {k: fwd[k].stage for k in fwd} == {k: bwd[k].stage for k in bwd}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_deal_fold.py -k seed -v`
Expected: FAIL (seed events currently ignored — stage defaults to `demoed`, `deal_value` None, stale logic wrong).

- [ ] **Step 3: Add seed-tracking locals**

In `build_deals`, after the line `dropped = False` (currently `lib/deal_fold.py:187`), add:

```python
        seed_stage = ""
        seed_outcome = ""
        seed_import_ts = None
        seed_value = None
        seed_account = ""
```

- [ ] **Step 4: Add the seed branch in the event loop**

Inside the `for e in evs:` loop, after the `if e.kind == "manual":` block and BEFORE the `if e.timestamp and ...last_event_at` line (currently `lib/deal_fold.py:227`), add:

```python
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
```

- [ ] **Step 5: Restructure the post-loop stage/outcome derivation**

Replace the current block (currently `lib/deal_fold.py:234-242`):

```python
        d.contact_emails = contacts
        d.cycle_start = d.demo_date  # min(trial, demo) == demo in Phase 1a
        if d.outcome == "lost":
            d.stage = "lost"
            d.lost_reason = lost_reason
        else:
            d.outcome = "open"
            d.stage = "demoed"
        d.account_name = "" if email.startswith("unresolved:") else (crosswalk.get(email) or domain_to_name(email))
```

with:

```python
        d.contact_emails = contacts
        d.cycle_start = d.demo_date  # min(trial, demo) == demo in Phase 1a
        has_real = any(e.kind in ("demo", "trial", "sale") for e in evs)
        if d.outcome == "lost":                 # explicit status=lost event — terminal
            d.stage = "lost"
            d.lost_reason = lost_reason
        elif has_real:                          # real demo/trial/sale drives stage
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
```

- [ ] **Step 6: Anchor the clean-slate stale clock + guard the stale branch on `outcome=="open"`**

Replace the current block (currently `lib/deal_fold.py:255-256`):

```python
        snoozed = isinstance(check_back, str) and bool(check_back) and check_back > today[:10]
        effective_start = max([s for s in (d.cycle_start, last_active_at) if s], default=None)
```

with:

```python
        # A seed-only OPEN deal anchors its 45-day clock to the import date
        # (clean slate: nothing stale on import day; ages in after import+45d).
        seed_anchor = seed_import_ts if (not has_real and (seed_stage or seed_outcome)) else None
        snoozed = isinstance(check_back, str) and bool(check_back) and check_back > today[:10]
        effective_start = max([s for s in (d.cycle_start, last_active_at, seed_anchor) if s], default=None)
```

Then change the stale review branch (currently `lib/deal_fold.py:265`) from:

```python
        elif effective_start and _days_since(effective_start, today) >= stale_days:
```

to:

```python
        elif d.outcome == "open" and effective_start and _days_since(effective_start, today) >= stale_days:
```

- [ ] **Step 7: Run to verify seed tests pass AND nothing regressed**

Run: `python3 -m pytest tests/test_deal_fold.py -v`
Expected: PASS — all pre-existing fold tests plus the 6 new seed tests. (The `outcome=="open"` guard is behavior-preserving for existing tests: every existing deal is `open` or `lost`, and `lost` is already handled by the earlier branch.)

- [ ] **Step 8: Commit**

```bash
git add lib/deal_fold.py tests/test_deal_fold.py
git commit -m "feat(deals): fold seed events (imported stage ground-truth + clean-slate clock)"
```

---

## Task 4: `scripts/backfill_deals.py` — one-shot orchestrator

**Files:**
- Create: `scripts/backfill_deals.py`
- Test: `tests/test_backfill_script.py`

**Interfaces:**
- Consumes: `registry_storage` (`lib/storage.py`), `normalize_seed_events` (Task 2), `append_events`/`load_events` (`lib/deal_events.py`).
- Produces: a `run_backfill(storage, import_ts, dry_run=False) -> dict` returning `{"leads": n, "events": n, "appended": n, "by_stage": {...}, "notion_keyed": n, "email_keyed": n, "skipped_no_page_id": n}`; a `__main__` guard with `--dry-run`.

**Context:** Bootstrap pattern (see `scripts/avoma_sync.py`): `config = json.load(open("config.json"))`, `storage = registry_storage(config)`. `registry_storage` is a `LocalStorage` rooted at `data/`, so it reads `pipeline_cache.json` → `data/pipeline_cache.json` and appends to `deal_events.jsonl` → `data/deal_events.jsonl`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backfill_script.py
import importlib
from lib.storage import LocalStorage
from lib.deal_events import load_events


def _storage(tmp_path):
    (tmp_path / "pipeline_cache.json").write_text(
        '{"leads": ['
        '{"page_id":"p1","name":"Acme","email":"jane@acme.com","status":"In-Trial / Post Demo","last_contacted":"2026-06-24","estimated_value":2000},'
        '{"page_id":"p2","name":"Baxter","email":null,"status":"Lost","last_contacted":"2026-05-21"}'
        ']}')
    return LocalStorage(base_dir=str(tmp_path))


def test_dry_run_appends_nothing_but_reports(tmp_path):
    mod = importlib.import_module("scripts.backfill_deals")
    st = _storage(tmp_path)
    summary = mod.run_backfill(st, "2026-08-19T12:00:00Z", dry_run=True)
    assert summary["leads"] == 2 and summary["events"] == 2
    assert summary["appended"] == 0                       # dry run
    assert summary["email_keyed"] == 1 and summary["notion_keyed"] == 1
    assert load_events(st) == []                          # nothing written


def test_real_run_appends_and_is_idempotent(tmp_path):
    mod = importlib.import_module("scripts.backfill_deals")
    st = _storage(tmp_path)
    first = mod.run_backfill(st, "2026-08-19T12:00:00Z", dry_run=False)
    assert first["appended"] == 2
    assert len(load_events(st)) == 2
    second = mod.run_backfill(st, "2026-08-19T12:00:00Z", dry_run=False)
    assert second["appended"] == 0                        # idempotent
    assert len(load_events(st)) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_backfill_script.py -v`
Expected: FAIL (`ModuleNotFoundError: scripts.backfill_deals`).

- [ ] **Step 3: Implement**

```python
# scripts/backfill_deals.py
#!/usr/bin/env python3
"""One-shot: import Notion pipeline_cache.json records as `seed` DealEvents.

Reads the pipeline_cache.json snapshot (produced via the normal sync path),
transforms each lead into a seed event, and appends unseen ones to
data/deal_events.jsonl. Idempotent (keyed on Notion page_id). Run --dry-run
first; commit deal_events.jsonl to origin/main after a real run."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone

from lib.deal_backfill import normalize_seed_events
from lib.deal_events import append_events
from lib.storage import registry_storage


def run_backfill(storage, import_ts: str, dry_run: bool = False,
                 cache_key: str = "pipeline_cache.json") -> dict:
    cache = storage.read_json(cache_key, default={}) or {}
    leads = cache.get("leads", []) or []
    events = normalize_seed_events(leads, import_ts)
    by_stage = Counter(e.payload.get("stage", "") for e in events)
    notion_keyed = sum(1 for e in events if e.email.startswith("notion:"))
    appended = 0 if dry_run else append_events(storage, events)
    return {
        "leads": len(leads),
        "events": len(events),
        "appended": appended,
        "by_stage": dict(by_stage),
        "notion_keyed": notion_keyed,
        "email_keyed": len(events) - notion_keyed,
        "skipped_no_page_id": len(leads) - len(events),
        "dry_run": dry_run,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="One-shot Notion pipeline backfill.")
    ap.add_argument("--dry-run", action="store_true", help="compute + report, append nothing")
    ap.add_argument("--config", default="config.json")
    args = ap.parse_args()
    with open(args.config) as f:
        config = json.load(f)
    storage = registry_storage(config)
    import_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = run_backfill(storage, import_ts, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        print("\n[dry-run] nothing appended. Re-run without --dry-run to write, "
              "then commit data/deal_events.jsonl to origin/main.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_backfill_script.py -v`
Expected: PASS (dry-run writes nothing; real run appends 2 then 0).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `python3 -m pytest tests/test_deal_fold.py tests/test_deal_backfill.py tests/test_deal_status_map.py tests/test_backfill_script.py tests/test_deal_projection.py -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_deals.py tests/test_backfill_script.py
git commit -m "feat(deals): one-shot backfill_deals script (dry-run + idempotent)"
```

---

## Task 5: Validate against the real cache (no commit) + rollout

**Files:** none committed — this is the inspection gate before the real import.

- [ ] **Step 1: Dry-run against the live 111-lead cache**

Run:
```bash
python3 scripts/backfill_deals.py --dry-run
```
Expected summary: `leads: 111`, `events: 111`, `appended: 0`, `email_keyed: 91`, `notion_keyed: 20`, `skipped_no_page_id: 0`, and `by_stage` ≈ `{"lost": 48, "won": 36, "in_trial": 14, "demoed": 13}`.

- [ ] **Step 2: Real run + fold inspection**

```bash
python3 scripts/backfill_deals.py
python3 -c "
from lib.storage import registry_storage
from lib.deal_events import load_events
from lib.deal_crosswalk import load_crosswalk
from lib.deal_fold import build_deals, build_deals_to_review
import json, datetime
s = registry_storage({})
today = datetime.date.today().isoformat()
deals = build_deals(load_events(s), load_crosswalk(s), today)
from collections import Counter
print('stages:', dict(Counter(d.stage for d in deals.values())))
print('review:', build_deals_to_review(deals)['counts'])
"
```
Expected: ~111 deals; stage counts matching the dry-run; the review `identity`/`stale` counts small (identity for any name-only ambiguity, stale ~0 on import day due to clean slate — plus any pre-existing demo-sourced flags).

- [ ] **Step 3: Confirm idempotency**

Run: `python3 scripts/backfill_deals.py --dry-run`
Expected: `appended: 0` on a second pass (all `event_id`s already present).

- [ ] **Step 4: Commit the imported events to origin/main**

```bash
git add data/deal_events.jsonl
git commit -m "data: backfill 111 Notion pipeline records as seed events"
git pull --rebase && git push
```

- [ ] **Step 5: Eyeball the board**

Launch the Registry UI (`registry-ui` skill or `python3 tools/server.py`), open the **Pipeline** tab, confirm the columns populate (Lost/Won/In-Trial/Demoed) with the imported deals, and the review queue is not flooded.

---

## Self-Review

- **Spec coverage:** status map (§3.1 → Task 1); `normalize_seed_events` + keying + idempotency (§3.2 → Task 2); fold seed handling incl. real-supersedes-seed, account precedence, clean-slate anchor, `outcome=="open"` stale guard (§3.3/§3.4 → Task 3); orchestration + dry-run (§3.5 → Task 4); rollout + validation (§6 → Task 5). Non-goals (seam-swap, OMS ingest, add-deal UI) intentionally absent.
- **Placeholder scan:** none — every step carries real code and exact commands.
- **Type consistency:** `map_notion_status(status) -> (stage, outcome)` (Task 1) consumed in Task 2; `normalize_seed_events(leads, import_ts) -> list[DealEvent]` (Task 2) consumed in Task 4; seed payload keys (`stage`, `outcome`, `import_ts`, `estimated_value`) produced in Task 2 and read identically in Task 3's fold branch and Task 4's `by_stage`. `event_id = make_event_id("seed", page_id, key)` defined once (Task 2), relied on for idempotency in Tasks 4–5.
- **Order-independence & totality:** seed branch uses last-write-wins over the existing `(timestamp, event_id)` sort; payloads read via `_payload`/`.get`; a lead with no `page_id` is skipped, never raises.
