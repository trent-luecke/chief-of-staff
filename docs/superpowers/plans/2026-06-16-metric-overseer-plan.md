# Metric Overseer (Plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Prerequisite:** Plan A (`OS-Metric-Sync/docs/superpowers/plans/2026-06-16-metric-sync-engine-plan.md`) must be deployed and its `GET /api/metrics/snapshot` verified live. This plan builds against that contract.

**Goal:** Turn chief-of-staff into the metric overseer: it drives the OS-Metric-Sync refresh, consumes the canonical snapshot (replacing all of its own raw-sheet metric pulls), keeps applying its breach/pace narration brain, caches the last-good snapshot for graceful degradation, and surfaces sync failures + staleness into the brief and Telegram.

**Architecture:** A new `lib/metrics_client.py` is the only code that talks to OS-Metric-Sync (`trigger_sync()` + `fetch_snapshot()` with a git/R2-cached fallback). The collect stage in `pipeline.py` replaces its `collectors/sheets.py` block with a single snapshot fetch that populates `collected.sales_data`, `demos_data`, and `cancellations` — which already feed three consumers (the GTM brain, the What-Moved diff, and the memory/vector pipeline). `lib/gtm_metrics.py` drops the dead `leads_mtd` metric and takes its targets from the snapshot instead of `config.json`. **Onboarding stays computed locally** — chief-of-staff's nightly Notion onboarding sync is the reliable one, so `onboarding_coverage` keeps using `load_onboarding_active` and is merged with the snapshot-derived metrics.

**Tech Stack:** Python 3, `requests` (already a dependency), pytest. Storage via the existing `storage` abstraction (`read_json`/`write_json`).

## Global Constraints

- Repo: `/Users/trentluecke/dev/Claude-Projects/chief-of-staff`. Run commands from there.
- Tests: `python -m pytest tests/ -v`. Match existing test style in `tests/test_gtm_metrics.py`.
- New env/secrets: `METRICS_BASE_URL` (deployed OS-Metric-Sync base URL) and `METRICS_PASSWORD` (the `DASHBOARD_PASSWORD` value). Add both as GitHub Secrets for the brief workflow. Locally they go in `.env`.
- HTTP auth is Basic with empty username: `requests.get(url, auth=("", METRICS_PASSWORD))`.
- **Non-fatal everywhere:** a metrics failure must never crash the brief. The client returns a cached snapshot with `stale=True`, or `None` if no cache exists; callers degrade gracefully.
- Onboarding is NOT in the snapshot. Keep `collectors/onboarding.load_onboarding_active` and the nightly onboarding sync exactly as they are.
- The `gtm` target block is removed from `config.json` only in Task 6 (after the snapshot is proven to carry targets) — not before.
- `origin/main` is a live datastore; push promptly, rebase onto fresh `origin/main` before merging (see CLAUDE.md).

---

### Task 1: `lib/metrics_client.py` — the only thing that talks to the engine

**Files:**
- Create: `lib/metrics_client.py`
- Test: `tests/test_metrics_client.py`

**Interfaces:**
- Produces:
  - `trigger_sync(base_url: str, password: str, timeout: int = 120) -> dict` — POSTs `/api/sync-all`; returns the parsed report dict, or `{"status": "error", "error": str, "report": []}` on failure (never raises).
  - `fetch_snapshot(base_url: str, password: str, storage, timeout: int = 30) -> dict | None` — GETs `/api/metrics/snapshot`. On success, writes the body to cache `state/metrics_snapshot.json` via `storage.write_json` and returns it with `stale=False` added. On failure, returns the cached snapshot (if any) with `stale=True` and `stale_reason` set, else `None`.
  - Cache key constant: `SNAPSHOT_CACHE_KEY = "state/metrics_snapshot.json"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_metrics_client.py
import lib.metrics_client as mc


class FakeStorage:
    def __init__(self, initial=None):
        self.store = dict(initial or {})
    def read_json(self, key):
        return self.store.get(key)
    def write_json(self, key, value):
        self.store[key] = value


def test_fetch_snapshot_happy(monkeypatch):
    payload = {"schema_version": 1, "sales_data": {"count": 2}, "targets": {}}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return payload

    monkeypatch.setattr(mc.requests, "get", lambda *a, **k: Resp())
    storage = FakeStorage()
    snap = mc.fetch_snapshot("http://x", "pw", storage)

    assert snap["stale"] is False
    assert snap["sales_data"]["count"] == 2
    # Cached for next time.
    assert storage.store[mc.SNAPSHOT_CACHE_KEY]["sales_data"]["count"] == 2


def test_fetch_snapshot_down_returns_cached_stale(monkeypatch):
    def boom(*a, **k):
        raise mc.requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(mc.requests, "get", boom)
    cached = {"schema_version": 1, "sales_data": {"count": 9}, "targets": {}}
    storage = FakeStorage({mc.SNAPSHOT_CACHE_KEY: cached})

    snap = mc.fetch_snapshot("http://x", "pw", storage)
    assert snap["stale"] is True
    assert "stale_reason" in snap
    assert snap["sales_data"]["count"] == 9


def test_fetch_snapshot_down_no_cache_returns_none(monkeypatch):
    def boom(*a, **k):
        raise mc.requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(mc.requests, "get", boom)
    assert mc.fetch_snapshot("http://x", "pw", FakeStorage()) is None


def test_trigger_sync_failure_is_non_fatal(monkeypatch):
    def boom(*a, **k):
        raise mc.requests.exceptions.Timeout("slow")
    monkeypatch.setattr(mc.requests, "post", boom)
    out = mc.trigger_sync("http://x", "pw")
    assert out["status"] == "error"
    assert "report" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.metrics_client'`.

- [ ] **Step 3: Create `lib/metrics_client.py`**

```python
# lib/metrics_client.py
"""Client for the OS-Metric-Sync engine — the only module that talks to it.

trigger_sync() drives a refresh; fetch_snapshot() reads the canonical contract
with a last-good cache fallback so the brief never hard-fails on engine downtime.
"""

from __future__ import annotations

import sys
import requests

SNAPSHOT_CACHE_KEY = "state/metrics_snapshot.json"


def trigger_sync(base_url: str, password: str, timeout: int = 120) -> dict:
    """POST /api/sync-all. Returns the report dict; never raises."""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/sync-all",
            auth=("", password),
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️  Metrics sync trigger failed (non-fatal): {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)[:200], "report": []}


def fetch_snapshot(base_url: str, password: str, storage, timeout: int = 30) -> dict | None:
    """GET /api/metrics/snapshot with last-good cache fallback.

    Returns the snapshot dict with a `stale` flag, or None if the engine is
    unreachable and no cached snapshot exists.
    """
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/api/metrics/snapshot",
            auth=("", password),
            timeout=timeout,
        )
        resp.raise_for_status()
        snap = resp.json()
        snap["stale"] = False
        storage.write_json(SNAPSHOT_CACHE_KEY, snap)
        return snap
    except Exception as e:
        print(f"⚠️  Metrics snapshot fetch failed (non-fatal): {e}", file=sys.stderr)
        cached = storage.read_json(SNAPSHOT_CACHE_KEY)
        if cached:
            cached["stale"] = True
            cached["stale_reason"] = f"live fetch failed ({str(e)[:80]}); using last-good snapshot"
            return cached
        return None
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_metrics_client.py -v`
Expected: PASS (all four).

- [ ] **Step 5: Commit**

```bash
git add lib/metrics_client.py tests/test_metrics_client.py
git commit -m "feat(metrics): client for OS-Metric-Sync engine with cached fallback"
```

---

### Task 2: Drop the dead `leads_mtd` metric from `lib/gtm_metrics.py`

There is no lead counting; demos is the top of funnel. Remove `leads_mtd` from the registry, the `evaluate_metrics` signature, and its evaluation block. The remaining five metrics are unchanged.

**Files:**
- Modify: `lib/gtm_metrics.py` (remove `MetricDef(id="leads_mtd", ...)` ~lines 39-43; remove the `leads_data` parameter and the "1. Leads MTD" block ~lines 247-298; remove `_leads_last_updated` ~lines 204-212 and the now-unused `stale_days`)
- Test: `tests/test_gtm_metrics.py` (update calls to drop `leads_data`)

**Interfaces:**
- Produces: `evaluate_metrics(demos_data, sales_data, onboarding_active, cancellations, cfg, today=None) -> list[MetricResult]` — five results in order: `demos_mtd`, `sales_mtd`, `onboarding_coverage`, `churn_count`, `churn_reasons`. (Note: `leads_data` parameter is gone.)

- [ ] **Step 1: Write/adjust the failing test**

```python
# tests/test_gtm_metrics.py — add this test
from datetime import date
from lib.gtm_metrics import evaluate_metrics


def test_no_leads_metric_and_five_results():
    cfg = {"demos_mtd_target": 30, "sales_mtd_target": 15,
           "onboarding_coverage_threshold": 5, "churn_count_threshold": 2,
           "churn_reason_cluster_threshold": 2, "churn_reason_window_days": 30,
           "pace_early_month_guard_pct": 0.25}
    results = evaluate_metrics(
        demos_data={"count": 8},
        sales_data={"count": 5},
        onboarding_active=[{"status": "In Progress"}] * 6,
        cancellations={"count": 1, "entries": []},
        cfg=cfg,
        today=date(2026, 6, 16),
    )
    ids = [r.id for r in results]
    assert ids == ["demos_mtd", "sales_mtd", "onboarding_coverage", "churn_count", "churn_reasons"]
    assert "leads_mtd" not in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gtm_metrics.py::test_no_leads_metric_and_five_results -v`
Expected: FAIL — `TypeError: evaluate_metrics() missing ... 'leads_data'` (current signature still requires it).

- [ ] **Step 3: Edit `lib/gtm_metrics.py`**

1. Delete the `leads_mtd` `MetricDef` (lines 39-43).
2. Delete the `_leads_last_updated` helper (lines 201-212).
3. Change the signature from `def evaluate_metrics(leads_data, demos_data, ...)` to drop `leads_data` (new first param is `demos_data`).
4. Delete the entire "── 1. Leads MTD ──" block (lines 247-298).
5. Delete the now-unused `stale_days = cfg.get("leads_stale_days", 3)` line.
6. Update the docstring to remove the `leads_data` arg and say "five GTM metrics".

The remaining blocks (Demos, Sales, Onboarding, Churn count, Churn reasons) are unchanged.

- [ ] **Step 4: Update existing callers in the test file**

In `tests/test_gtm_metrics.py`, remove the `leads_data=...` keyword argument from every `evaluate_metrics(...)` call (it no longer accepts it). Delete any test that asserted on `leads_mtd` results.

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/test_gtm_metrics.py -v`
Expected: PASS — the new test and all retained tests.

- [ ] **Step 6: Commit**

```bash
git add lib/gtm_metrics.py tests/test_gtm_metrics.py
git commit -m "refactor(gtm): drop dead leads_mtd metric — demos is top of funnel"
```

---

### Task 3: Snapshot → `evaluate_metrics` adapter

A pure helper that maps a snapshot dict + locally-loaded onboarding into the `evaluate_metrics` kwargs. Keeps the wiring in `pipeline.py` thin and unit-testable.

**Files:**
- Modify: `lib/metrics_client.py` (add `metrics_from_snapshot`)
- Test: `tests/test_metrics_client.py` (add cases)

**Interfaces:**
- Consumes: a snapshot dict (Task 1 shape) + `onboarding_active: list[dict]` (from `load_onboarding_active`).
- Produces: `metrics_from_snapshot(snapshot, onboarding_active, today=None) -> list[MetricResult]` — calls `evaluate_metrics` with `demos_data=snapshot["demos_data"]`, `sales_data=snapshot["sales_data"]`, `cancellations=snapshot["cancellations"] if count>0 else None`, `cfg=snapshot["targets"]`, and the passed `onboarding_active`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_client.py — add
from datetime import date
import lib.metrics_client as mc


def test_metrics_from_snapshot_maps_inputs():
    snapshot = {
        "demos_data": {"count": 8},
        "sales_data": {"count": 5, "revenue": 1000.0},
        "cancellations": {"count": 1, "entries": [{"date": "6/3/2026", "reason": "price"}]},
        "targets": {"demos_mtd_target": 30, "sales_mtd_target": 15,
                    "onboarding_coverage_threshold": 5, "churn_count_threshold": 2,
                    "churn_reason_cluster_threshold": 2, "churn_reason_window_days": 30,
                    "pace_early_month_guard_pct": 0.25},
    }
    results = mc.metrics_from_snapshot(
        snapshot, onboarding_active=[{"status": "In Progress"}] * 6, today=date(2026, 6, 16),
    )
    by_id = {r.id: r for r in results}
    assert by_id["demos_mtd"].current == 8
    assert by_id["sales_mtd"].current == 5
    assert by_id["onboarding_coverage"].current == 6
    assert by_id["churn_count"].current == 1


def test_metrics_from_snapshot_zero_cancellations_passes_none():
    snapshot = {
        "demos_data": {"count": 0}, "sales_data": {"count": 0},
        "cancellations": {"count": 0, "entries": []},
        "targets": {"demos_mtd_target": 30, "sales_mtd_target": 15,
                    "onboarding_coverage_threshold": 5, "churn_count_threshold": 2,
                    "churn_reason_cluster_threshold": 2, "churn_reason_window_days": 30,
                    "pace_early_month_guard_pct": 0.25},
    }
    results = mc.metrics_from_snapshot(snapshot, onboarding_active=[], today=date(2026, 6, 16))
    assert {r.id for r in results} == {
        "demos_mtd", "sales_mtd", "onboarding_coverage", "churn_count", "churn_reasons"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics_client.py::test_metrics_from_snapshot_maps_inputs -v`
Expected: FAIL — `AttributeError: module 'lib.metrics_client' has no attribute 'metrics_from_snapshot'`.

- [ ] **Step 3: Add `metrics_from_snapshot` to `lib/metrics_client.py`**

```python
from lib.gtm_metrics import evaluate_metrics, MetricResult  # add at top


def metrics_from_snapshot(snapshot: dict, onboarding_active: list[dict], today=None) -> list[MetricResult]:
    """Map a canonical snapshot + local onboarding into MetricResult objects."""
    cancellations = snapshot.get("cancellations") or {}
    return evaluate_metrics(
        demos_data=snapshot.get("demos_data"),
        sales_data=snapshot.get("sales_data"),
        onboarding_active=onboarding_active,
        cancellations=cancellations if cancellations.get("count", 0) > 0 else None,
        cfg=snapshot.get("targets", {}),
        today=today,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_metrics_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/metrics_client.py tests/test_metrics_client.py
git commit -m "feat(metrics): snapshot -> evaluate_metrics adapter"
```

---

### Task 4: Wire the collect stage to the snapshot (parallel-run: keep sheets too)

Add the snapshot fetch alongside the existing sheets block so both run during the parallel-run period (spec Phase 2). The snapshot populates new fields; the brief still uses the sheets-derived values until Task 5 flips the switch. This lets you diff the two before deleting anything.

**Files:**
- Modify: `pipeline.py` — add a `snapshot` field to the collected dataclass (near line 88-90) and a snapshot-fetch block in the collect stage (after the sheets block, ~line 505)
- Test: manual diff (Step 4)

**Interfaces:**
- Consumes: `metrics_client.trigger_sync`, `metrics_client.fetch_snapshot`, `os.environ["METRICS_BASE_URL"]`, `os.environ["METRICS_PASSWORD"]`, `storage`.
- Produces: `collected.metrics_snapshot: dict | None`.

- [ ] **Step 1: Add the dataclass field**

In the collected-data dataclass (where `sales_data`, `demos_data`, `leads_data` are declared, ~line 88), add:

```python
    metrics_snapshot: dict | None = None
```

Remove the `leads_data: dict | None = None` line (the metric is gone; nothing reads it after Task 5, and removing it now surfaces any stragglers).

- [ ] **Step 2: Add the snapshot-fetch block in the collect stage**

After the existing sheets `stage.collectors.append(...)` block (~line 504), add:

```python
        # Metrics engine: drive the sync, then pull the canonical snapshot.
        _metrics_err = None
        with timed() as t:
            try:
                from lib import metrics_client
                base_url = os.environ.get("METRICS_BASE_URL", "")
                password = os.environ.get("METRICS_PASSWORD", "")
                if base_url:
                    metrics_client.trigger_sync(base_url, password)
                    data.metrics_snapshot = metrics_client.fetch_snapshot(base_url, password, storage)
                    if data.metrics_snapshot:
                        print(f"   Metrics snapshot: sales={data.metrics_snapshot['sales_data']['count']} "
                              f"demos={data.metrics_snapshot['demos_data']['count']} "
                              f"(stale={data.metrics_snapshot.get('stale')})")
            except Exception as e:
                _metrics_err = str(e)[:200]
                print(f"⚠️  Metrics snapshot error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="metrics_snapshot",
            status="error" if _metrics_err else "ok",
            error=_metrics_err,
            duration_ms=t.elapsed_ms,
        ))
```

- [ ] **Step 3: Run the suite + a real `--no-email` run**

Run: `python -m pytest tests/ -v` → expect PASS (no behavior change to the brief yet).
Run (with `METRICS_BASE_URL`/`METRICS_PASSWORD` in `.env`): `python main.py --no-email`
Expected: log line `Metrics snapshot: sales=… demos=… (stale=False)`.

- [ ] **Step 4: Diff snapshot vs sheets (the safety gate)**

In the run output, compare the snapshot's `sales`/`demos`/cancellation counts against the sheets-derived `Sales MTD` / `Demos MTD` / `cancellation(s) this month` log lines. They should match. Investigate any mismatch before Task 5 — a mismatch means a definition difference to reconcile, which is exactly what this gate is for.

- [ ] **Step 5: Commit**

```bash
git add pipeline.py
git commit -m "feat(metrics): fetch engine snapshot in collect stage (parallel-run)"
```

---

### Task 5: Cut over — snapshot becomes the source; remove sheet metric pulls

Flip the consumers to the snapshot and delete the `collectors/sheets.py` metric block. `onboarding_coverage` stays local. Surface staleness + sync failures.

**Files:**
- Modify: `pipeline.py` — populate `sales_data`/`demos_data`/`cancellations` from the snapshot; repoint the GTM-metrics evaluation; add staleness + sync-failure flags; delete the sheets block
- Test: `tests/test_gtm_metrics.py` already covers `evaluate_metrics`; add a format test for the new flag helper

**Interfaces:**
- Consumes: `collected.metrics_snapshot`, `metrics_client.metrics_from_snapshot`, `load_onboarding_active`.
- Produces: `pipeline._format_engine_flags(snapshot) -> list[str]` (staleness + per-source sync errors).

- [ ] **Step 1: Populate the legacy fields from the snapshot in the collect stage**

Replace the sheets block (lines 472-504, the `if not (... ) ... else: ... fetch_*_mtd ...`) with population from the snapshot. Put this *after* the snapshot-fetch block from Task 4:

```python
        # The snapshot is now the single source for these three consumers
        # (GTM metrics, What-Moved diff, memory/vector pipeline).
        if data.metrics_snapshot:
            data.sales_data = data.metrics_snapshot.get("sales_data")
            data.demos_data = data.metrics_snapshot.get("demos_data")
            data.cancellations = data.metrics_snapshot.get("cancellations") or {"count": 0, "entries": []}
```

Delete the entire old sheets block (the `sheets_cfg`/`fetch_cancellations_mtd`/`fetch_sales_mtd`/`fetch_demos_mtd`/`fetch_leads_mtd` collect code, ~lines 466-504).

- [ ] **Step 2: Repoint the GTM-metrics evaluation in `generate_and_deliver`**

Replace the `evaluate_metrics(...)` call (lines 744-751) so it uses the adapter and the snapshot's targets, while onboarding stays local:

```python
            from lib.metrics_client import metrics_from_snapshot
            from collectors.onboarding import load_onboarding_active
            onboarding_cfg = config.get("onboarding", {})
            active_statuses = onboarding_cfg.get("active_statuses", ["In Progress", "Awaiting Customer", "Ready to Go Live"])
            onboarding_cache_path = onboarding_cfg.get("cache_path", "data/onboarding_cache.json")
            onboarding_active = load_onboarding_active(onboarding_cache_path, active_statuses)
            snapshot = collected.metrics_snapshot
            if snapshot:
                _metric_results = metrics_from_snapshot(snapshot, onboarding_active)
                _metric_flags = _format_metric_flags(_metric_results, config.get("dashboard_path", "output/dashboard.html"))
                _metric_flags = _format_engine_flags(snapshot) + _metric_flags
```

(The `from lib.gtm_metrics import evaluate_metrics` import on line 737 can be removed here — `metrics_from_snapshot` wraps it.)

- [ ] **Step 3: Add the `_format_engine_flags` helper + its test**

Add near `_format_metric_flags` in `pipeline.py`:

```python
def _format_engine_flags(snapshot: dict) -> list[str]:
    """Staleness banner + per-source sync-failure flags from the engine snapshot."""
    flags = []
    if snapshot.get("stale"):
        flags.append(f"⚠️ Metrics: {snapshot.get('stale_reason', 'using last-good snapshot')}")
    for src, info in (snapshot.get("freshness") or {}).items():
        if not info.get("ok"):
            flags.append(f"⚠️ {src} metrics never synced — check OS-Metric-Sync")
    return flags
```

Test:

```python
# tests/test_engine_flags.py
from pipeline import _format_engine_flags


def test_stale_snapshot_flagged():
    flags = _format_engine_flags({"stale": True, "stale_reason": "engine down", "freshness": {}})
    assert any("engine down" in f for f in flags)


def test_unsynced_source_flagged():
    flags = _format_engine_flags({"stale": False, "freshness": {"revenue": {"ok": False}}})
    assert any("revenue" in f for f in flags)


def test_healthy_snapshot_no_flags():
    flags = _format_engine_flags({"stale": False, "freshness": {"revenue": {"ok": True}}})
    assert flags == []
```

- [ ] **Step 4: Run tests + a real run**

Run: `python -m pytest tests/test_engine_flags.py tests/test_gtm_metrics.py tests/test_metrics_client.py -v` → PASS.
Run: `python main.py --no-email` → brief generates; metric flags come from the snapshot; onboarding coverage still populated.

- [ ] **Step 5: Commit**

```bash
git add pipeline.py tests/test_engine_flags.py
git commit -m "feat(metrics): cut over to engine snapshot; local onboarding; staleness flags"
```

---

### Task 6: Telegram sync-failure alert

Beyond the brief, push a Telegram alert when the engine reports a failed sync, so a broken pull is loud, not silent.

**Files:**
- Modify: `pipeline.py` (after the snapshot fetch in collect stage) or the nudger path — send a Telegram message when `trigger_sync` reports failures.
- Test: `tests/test_metrics_client.py` (add `sync_failures` helper test)

**Interfaces:**
- Produces: `metrics_client.sync_failures(report: dict) -> list[str]` — names of sources with `status != "ok"` in a `sync-all` report.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_client.py — add
import lib.metrics_client as mc


def test_sync_failures_extracts_bad_sources():
    report = {"status": "partial", "report": [
        {"source": "revenue", "status": "ok"},
        {"source": "retention", "status": "failed", "error": "sheet 404"},
    ]}
    assert mc.sync_failures(report) == ["retention"]


def test_sync_failures_empty_when_all_ok():
    report = {"status": "ok", "report": [{"source": "revenue", "status": "ok"}]}
    assert mc.sync_failures(report) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics_client.py::test_sync_failures_extracts_bad_sources -v`
Expected: FAIL — no attribute `sync_failures`.

- [ ] **Step 3: Add `sync_failures` to `lib/metrics_client.py`**

```python
def sync_failures(report: dict) -> list[str]:
    """Return source names that did not sync OK in a /api/sync-all report."""
    return [r["source"] for r in report.get("report", []) if r.get("status") != "ok"]
```

- [ ] **Step 4: Wire the alert in `pipeline.py`**

Capture the `trigger_sync` return in the collect stage (Task 4 block) and, on failures, send Telegram via the existing helper. Locate the Telegram send function first:

Run: `grep -rn "def send_telegram\|telegram" lib/ processors/ | grep -i "def \|send" | head`

Then, in the collect-stage metrics block, replace `metrics_client.trigger_sync(base_url, password)` with:

```python
                    _sync_report = metrics_client.trigger_sync(base_url, password)
                    _failed = metrics_client.sync_failures(_sync_report)
                    if _failed:
                        try:
                            from lib.telegram import send_telegram_message  # adjust to the real path found above
                            send_telegram_message(f"⚠️ Metric sync failed: {', '.join(_failed)}")
                        except Exception as _te:
                            print(f"⚠️  Telegram sync-failure alert failed (non-fatal): {_te}", file=sys.stderr)
```

(Adjust the import to the actual Telegram-send function name/path from the grep.)

- [ ] **Step 5: Run tests + commit**

Run: `python -m pytest tests/test_metrics_client.py -v` → PASS.

```bash
git add lib/metrics_client.py tests/test_metrics_client.py pipeline.py
git commit -m "feat(metrics): Telegram alert on engine sync failure"
```

---

### Task 7: Delete dead code + retire the duplicate config

Now that the snapshot is the source and proven in the parallel-run, remove the duplicate pulls and the orphaned dashboard path.

**Files:**
- Delete: `scripts/gtm_dashboard.py` (orphaned — read a `gtm_snapshot.json` nothing writes)
- Modify: `collectors/sheets.py` — remove `fetch_leads_mtd`, `fetch_demos_mtd`, `fetch_sales_mtd`, `fetch_cancellations_mtd` (the snapshot replaces them). Keep `month_label`/`_parse_dollar` only if still imported elsewhere (grep first).
- Modify: `config.json` — remove the `gtm` target block (targets now come from the snapshot). Keep `onboarding` and `sheets.cancellations_*` only if still referenced (grep).
- Modify: `lib/gtm_metrics.py` — `cfg.get(...)` for thresholds now reads snapshot `targets`; no code change needed, but confirm no `leads_*` keys remain.

- [ ] **Step 1: Confirm nothing else imports the soon-to-be-deleted symbols**

```bash
grep -rn "gtm_dashboard\|fetch_leads_mtd\|fetch_sales_mtd\|fetch_demos_mtd\|fetch_cancellations_mtd\|gtm_snapshot\|leads_data\|leads_mtd" --include="*.py" . | grep -v tests/
```
Expected after Tasks 1-6: only definitions in `collectors/sheets.py` and the `scripts/gtm_dashboard.py` file itself. If anything else appears, it's a straggler consumer — fix it before deleting.

- [ ] **Step 2: Delete `scripts/gtm_dashboard.py` and the sheet fetchers**

```bash
git rm scripts/gtm_dashboard.py
```
Edit `collectors/sheets.py` to remove the four `fetch_*_mtd` functions. Run the grep from Step 1 for `month_label`/`_parse_dollar`; if unused elsewhere, remove them too; if used, keep them.

- [ ] **Step 3: Remove the `gtm` block from `config.json`**

Delete the top-level `"gtm": { ... }` object. Targets now ride in the snapshot. Run:
```bash
python -c "import json; json.load(open('config.json'))"
```
Expected: no error (valid JSON).

- [ ] **Step 4: Full suite + real run**

Run: `python -m pytest tests/ -v` → PASS.
Run: `python main.py --no-email` → brief generates end-to-end with snapshot-driven metrics, local onboarding, staleness/failure flags. Confirm no `ImportError` from removed symbols.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(metrics): retire duplicate sheet pulls, orphaned dashboard, gtm config block"
```

- [ ] **Step 6: Add the GitHub Secrets + verify the scheduled brief**

Add `METRICS_BASE_URL` and `METRICS_PASSWORD` as repo secrets for the brief workflow. Trigger the brief workflow via `workflow_dispatch` and confirm the run logs show the snapshot fetch and the brief contains snapshot-derived metric flags.

---

## Self-Review

- **Spec coverage:** `metrics_client` with cached fallback ✓ (Task 1); drop `leads_mtd` ✓ (Task 2); snapshot→evaluate adapter ✓ (Task 3); collect-stage wiring + parallel-run diff gate ✓ (Tasks 4-5); staleness + sync-failure surfacing in brief ✓ (Task 5) and Telegram ✓ (Task 6); delete duplicate pulls / orphaned dashboard / gtm config ✓ (Task 7). **Deviation from spec Phase 3 (documented):** onboarding read stays in chief-of-staff (its sync is reliable; the engine's is not), so onboarding is excluded from the snapshot and `onboarding_coverage` is computed locally and merged.
- **Placeholders:** none — all steps have runnable code/commands. The one "adjust to the real path" note (Task 6 Telegram import) is paired with the exact grep to resolve it.
- **Type consistency:** `evaluate_metrics` new signature (no `leads_data`) defined in Task 2 matches `metrics_from_snapshot`'s call in Task 3 and the test calls. Snapshot keys (`sales_data`, `demos_data`, `cancellations`, `targets`, `freshness`, `stale`) match Plan A's produced contract and are consumed identically in Tasks 3-5. `SNAPSHOT_CACHE_KEY` defined once and reused. `sync_failures` reads the `report[].status`/`source` keys Plan A's `/api/sync-all` produces.
