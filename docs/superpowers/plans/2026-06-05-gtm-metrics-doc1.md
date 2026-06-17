# GTM Metrics Doc 1 — Metric Definitions + Breach Logic + Dashboard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `lib/gtm_metrics.py` — the single source of truth for six GTM metric definitions, two breach functions, and an `evaluate_metrics()` orchestrator — plus an HTML dashboard renderer in `scripts/gtm_dashboard.py`.

**Architecture:** `lib/gtm_metrics.py` is a pure-computation module: takes collected data in, emits `MetricResult` objects out. It sits beside kpi_snapshot (which is a historical observation); these are breach evaluations for forward use by the brief (doc 2). The dashboard renders from a `data/gtm_snapshot.json` raw-data snapshot (same format as the collectors return) so it always calls `evaluate_metrics()` — the metric defs stay the single source of truth. All breach thresholds and targets live in a new `"gtm"` config block.

**Tech Stack:** Python 3.11+, stdlib only (`datetime`, `calendar`), pytest

---

## Resolved open items

| Question | Decision |
|---|---|
| Onboarding stage threshold for coverage count | `config["onboarding"]["active_statuses"]` — already `["In Progress", "Awaiting Customer", "Ready to Go Live"]`. The caller calls `load_onboarding_active(cache_path, active_statuses)` and passes the pre-filtered list to `evaluate_metrics`. |
| Early-month guard cutoff | `pace_early_month_guard_pct = 0.25` in config (25% of total business days elapsed ≈ ~5 biz days). Exposed in config so it can be tuned. |
| Metric defs extend kpi_snapshot or sit beside it? | Beside. kpi_snapshot is a historical memory observation. `evaluate_metrics()` is a breach-detection pass that the brief calls with freshly fetched data. They consume the same raw inputs but serve different purposes. |

---

## File map

| Action | File | Responsibility |
|---|---|---|
| Create | `lib/gtm_metrics.py` | `MetricDef`, `MetricResult`, `METRIC_DEFS`, `pace_breach`, `redflag_breach`, `evaluate_metrics` |
| Create | `scripts/gtm_dashboard.py` | `render_html(results, generated_at) -> str`, `main()` reads `data/gtm_snapshot.json` → writes `output/gtm_dashboard.html` |
| Modify | `config.json` | Add `"gtm"` block with all targets/thresholds |
| Create | `tests/test_gtm_metrics.py` | Unit tests for biz day utils, breach functions, evaluate_metrics, METRIC_DEFS |
| Create | `tests/test_gtm_dashboard.py` | Tests for `render_html` |

`data/gtm_snapshot.json` (populated by doc 2 daily run; snapshot = raw collector outputs, not evaluated results). Format documented in Task 5.

---

## Six metrics

| id | label | source | horizon | breach fn |
|---|---|---|---|---|
| `leads_mtd` | Leads MTD | `fetch_leads_mtd` | next-month | `pace_breach` |
| `demos_mtd` | Demos MTD | `fetch_demos_mtd` | next-month | `pace_breach` |
| `sales_mtd` | Sales MTD (Closes) | `fetch_sales_mtd` | this-month | `pace_breach` |
| `onboarding_coverage` | Onboarding Coverage | `load_onboarding_active` | this-month | `redflag_breach` |
| `churn_count` | Churn Count MTD | `fetch_cancellations_mtd` count | this-month | `redflag_breach` |
| `churn_reasons` | Churn Reason Cluster | `fetch_cancellations_mtd` entries[].reason | this-month | `redflag_breach` |

---

## Task 1: Add `"gtm"` block to `config.json`

**Files:**
- Modify: `config.json`

- [ ] **Step 1.1: Add the `"gtm"` block**

Insert after the `"avoma"` block (before `"demo_scan"`):

```json
"gtm": {
  "leads_mtd_target": 20,
  "demos_mtd_target": 30,
  "sales_mtd_target": 15,
  "onboarding_coverage_threshold": 5,
  "churn_count_threshold": 2,
  "churn_reason_cluster_threshold": 2,
  "churn_reason_window_days": 30,
  "pace_early_month_guard_pct": 0.25,
  "leads_stale_days": 3
},
```

- [ ] **Step 1.2: Verify JSON is valid**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python3 -c "import json; json.load(open('config.json')); print('valid')"
```
Expected: `valid`

- [ ] **Step 1.3: Commit**

```bash
git add config.json
git commit -m "feat: add gtm config block with metric targets and breach thresholds"
```

---

## Task 2: `MetricDef` + `MetricResult` dataclasses + `METRIC_DEFS` registry + business day utils

**Files:**
- Create: `lib/gtm_metrics.py` (skeleton through business day utils)
- Create: `tests/test_gtm_metrics.py`

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/test_gtm_metrics.py
from datetime import date
import pytest
from lib.gtm_metrics import (
    MetricDef,
    MetricResult,
    METRIC_DEFS,
    _count_business_days,
    _month_business_days,
)


class TestCountBusinessDays:
    def test_single_monday(self):
        d = date(2026, 6, 1)  # Monday
        assert _count_business_days(d, d) == 1

    def test_single_saturday_returns_zero(self):
        d = date(2026, 6, 6)  # Saturday
        assert _count_business_days(d, d) == 0

    def test_full_week_mon_to_fri(self):
        assert _count_business_days(date(2026, 6, 1), date(2026, 6, 5)) == 5

    def test_week_spanning_weekend(self):
        # Mon Jun 1 to Sun Jun 7 = 5 biz days
        assert _count_business_days(date(2026, 6, 1), date(2026, 6, 7)) == 5

    def test_sat_to_mon(self):
        assert _count_business_days(date(2026, 6, 6), date(2026, 6, 8)) == 1


class TestMonthBusinessDays:
    def test_june_2026_total_is_22(self):
        _, total = _month_business_days(date(2026, 6, 15))
        assert total == 22

    def test_elapsed_june_5_is_5(self):
        elapsed, _ = _month_business_days(date(2026, 6, 5))
        assert elapsed == 5

    def test_elapsed_june_15_is_11(self):
        # Jun 1,2,3,4,5,8,9,10,11,12,15 = 11 days
        elapsed, _ = _month_business_days(date(2026, 6, 15))
        assert elapsed == 11

    def test_elapsed_equals_total_on_last_biz_day(self):
        last = date(2026, 6, 30)  # Tuesday = biz day
        elapsed, total = _month_business_days(last)
        assert elapsed == total


class TestMetricDefs:
    def test_six_metrics(self):
        assert len(METRIC_DEFS) == 6

    def test_all_ids_unique(self):
        ids = [m.id for m in METRIC_DEFS]
        assert len(ids) == len(set(ids))

    def test_horizons_are_valid(self):
        for m in METRIC_DEFS:
            assert m.horizon in ("this-month", "next-month"), m.id

    def test_breach_fns_are_valid(self):
        for m in METRIC_DEFS:
            assert m.breach_fn in ("pace_breach", "redflag_breach"), m.id

    def test_leads_and_demos_are_next_month(self):
        h = {m.id: m.horizon for m in METRIC_DEFS}
        assert h["leads_mtd"] == "next-month"
        assert h["demos_mtd"] == "next-month"

    def test_sales_onboarding_churn_are_this_month(self):
        h = {m.id: m.horizon for m in METRIC_DEFS}
        assert h["sales_mtd"] == "this-month"
        assert h["onboarding_coverage"] == "this-month"
        assert h["churn_count"] == "this-month"
        assert h["churn_reasons"] == "this-month"


class TestMetricResult:
    def test_defaults(self):
        r = MetricResult(
            id="leads_mtd", label="Leads MTD",
            current=5, target=20,
            breach=False, breach_reason="",
            horizon="next-month",
        )
        assert r.stale is False
        assert r.stale_reason == ""
```

- [ ] **Step 2.2: Run to verify it fails**

```bash
pytest tests/test_gtm_metrics.py -v --tb=short
```
Expected: `ImportError: No module named 'lib.gtm_metrics'`

- [ ] **Step 2.3: Create `lib/gtm_metrics.py`** (skeleton — dataclasses, METRIC_DEFS, biz day utils only)

```python
"""GTM metric definitions, breach logic, and evaluation."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetricDef:
    id: str
    label: str
    source: str
    horizon: str    # "this-month" | "next-month"
    breach_fn: str  # "pace_breach" | "redflag_breach"


@dataclass
class MetricResult:
    id: str
    label: str
    current: Optional[float]
    target: Optional[float]
    breach: bool
    breach_reason: str
    horizon: str
    stale: bool = False
    stale_reason: str = ""


# ── Metric registry ───────────────────────────────────────────────────────────

METRIC_DEFS: list[MetricDef] = [
    MetricDef(
        id="leads_mtd", label="Leads MTD",
        source="fetch_leads_mtd (Dept Heads KPI sheet)",
        horizon="next-month", breach_fn="pace_breach",
    ),
    MetricDef(
        id="demos_mtd", label="Demos MTD",
        source="fetch_demos_mtd (Dept Heads KPI sheet)",
        horizon="next-month", breach_fn="pace_breach",
    ),
    MetricDef(
        id="sales_mtd", label="Sales MTD (Closes)",
        source="fetch_sales_mtd (Dept Heads KPI sheet)",
        horizon="this-month", breach_fn="pace_breach",
    ),
    MetricDef(
        id="onboarding_coverage", label="Onboarding Coverage",
        source="load_onboarding_active (Notion onboarding tracker)",
        horizon="this-month", breach_fn="redflag_breach",
    ),
    MetricDef(
        id="churn_count", label="Churn Count MTD",
        source="fetch_cancellations_mtd (MONTHLY Cancellations sheet)",
        horizon="this-month", breach_fn="redflag_breach",
    ),
    MetricDef(
        id="churn_reasons", label="Churn Reason Cluster",
        source="fetch_cancellations_mtd entries[].reason",
        horizon="this-month", breach_fn="redflag_breach",
    ),
]


# ── Business day utilities ────────────────────────────────────────────────────


def _count_business_days(start: date, end: date) -> int:
    """Count Mon–Fri days from start through end, inclusive."""
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def _month_business_days(today: date) -> tuple[int, int]:
    """Return (elapsed_biz_days, total_biz_days) for today's month."""
    first = date(today.year, today.month, 1)
    last_day_num = calendar.monthrange(today.year, today.month)[1]
    last = date(today.year, today.month, last_day_num)
    elapsed = _count_business_days(first, today)
    total = _count_business_days(first, last)
    return elapsed, total
```

- [ ] **Step 2.4: Run to verify tests pass**

```bash
pytest tests/test_gtm_metrics.py -v --tb=short
```
Expected: 15 tests PASS

- [ ] **Step 2.5: Commit**

```bash
git add lib/gtm_metrics.py tests/test_gtm_metrics.py
git commit -m "feat: add MetricDef/MetricResult dataclasses, METRIC_DEFS registry, business day utils"
```

---

## Task 3: `pace_breach` and `redflag_breach`

**Files:**
- Modify: `lib/gtm_metrics.py` (append both functions + `_parse_month_day` helper)
- Modify: `tests/test_gtm_metrics.py` (append new test classes)

- [ ] **Step 3.1: Append failing tests to `tests/test_gtm_metrics.py`**

Add after the existing test classes:

```python
from lib.gtm_metrics import pace_breach, redflag_breach


class TestPaceBreach:
    MID = date(2026, 6, 15)   # 50% of month elapsed, past guard
    EARLY = date(2026, 6, 2)  # ~9% elapsed, below 25% guard

    def test_no_breach_when_on_pace(self):
        # projected = 12 * (22/11) = 24 >= 20
        breach, reason = pace_breach(12, 20, self.MID, early_guard_pct=0.25)
        assert breach is False
        assert reason == ""

    def test_breach_when_behind_pace(self):
        # projected = 5 * (22/11) = 10 < 20
        breach, reason = pace_breach(5, 20, self.MID, early_guard_pct=0.25)
        assert breach is True
        assert "10" in reason
        assert "20" in reason

    def test_early_guard_suppresses_breach(self):
        breach, reason = pace_breach(0, 20, self.EARLY, early_guard_pct=0.25)
        assert breach is False
        assert reason == ""

    def test_sales_frame_mentions_pipeline(self):
        breach, reason = pace_breach(5, 20, self.MID, early_guard_pct=0.25, sales_frame=True)
        assert breach is True
        assert "pipeline" in reason.lower()

    def test_non_sales_frame_does_not_mention_pipeline(self):
        breach, reason = pace_breach(5, 20, self.MID, early_guard_pct=0.25, sales_frame=False)
        assert breach is True
        assert "pipeline" not in reason.lower()

    def test_exactly_on_target_no_breach(self):
        # projected = 11 * (22/11) = 22 >= 22
        breach, _ = pace_breach(11, 22, self.MID, early_guard_pct=0.25)
        assert breach is False

    def test_zero_current_above_guard_is_breach(self):
        breach, _ = pace_breach(0, 20, self.MID, early_guard_pct=0.25)
        assert breach is True


class TestRedflagOnboarding:
    def test_breach_below_threshold(self):
        breach, reason = redflag_breach("onboarding_coverage", current=4, threshold=5)
        assert breach is True
        assert "4" in reason
        assert "5" in reason

    def test_no_breach_at_threshold(self):
        breach, _ = redflag_breach("onboarding_coverage", current=5, threshold=5)
        assert breach is False

    def test_no_breach_above_threshold(self):
        breach, _ = redflag_breach("onboarding_coverage", current=7, threshold=5)
        assert breach is False


class TestRedflagChurnCount:
    def test_breach_above_threshold(self):
        breach, reason = redflag_breach("churn_count", current=3, threshold=2)
        assert breach is True
        assert "3" in reason

    def test_no_breach_at_threshold(self):
        breach, _ = redflag_breach("churn_count", current=2, threshold=2)
        assert breach is False

    def test_no_breach_below_threshold(self):
        breach, _ = redflag_breach("churn_count", current=1, threshold=2)
        assert breach is False


class TestRedflagChurnReasons:
    TODAY = date(2026, 6, 15)

    def _e(self, date_str: str, reason: str) -> dict:
        return {"date": date_str, "reason": reason, "account_name": "Test"}

    def test_breach_on_repeated_reason(self):
        entries = [
            self._e("6/5", "Business Changes"),
            self._e("6/8", "Business Changes"),
            self._e("6/10", "Price"),
        ]
        breach, reason = redflag_breach(
            "churn_reasons", entries=entries,
            window_days=30, reason_threshold=2, today=self.TODAY,
        )
        assert breach is True
        assert "Business Changes" in reason

    def test_no_breach_all_different_reasons(self):
        entries = [
            self._e("6/5", "Business Changes"),
            self._e("6/8", "Price"),
            self._e("6/10", "Feature Gap"),
        ]
        breach, _ = redflag_breach(
            "churn_reasons", entries=entries,
            window_days=30, reason_threshold=2, today=self.TODAY,
        )
        assert breach is False

    def test_entries_outside_window_excluded(self):
        # window=10d from June 15 → starts June 5; May entries excluded
        entries = [
            self._e("5/20", "Business Changes"),
            self._e("5/25", "Business Changes"),
        ]
        breach, _ = redflag_breach(
            "churn_reasons", entries=entries,
            window_days=10, reason_threshold=2, today=self.TODAY,
        )
        assert breach is False

    def test_empty_entries_no_breach(self):
        breach, _ = redflag_breach(
            "churn_reasons", entries=[],
            window_days=30, reason_threshold=2, today=self.TODAY,
        )
        assert breach is False

    def test_none_entries_no_breach(self):
        breach, _ = redflag_breach(
            "churn_reasons", entries=None,
            window_days=30, reason_threshold=2, today=self.TODAY,
        )
        assert breach is False

    def test_reason_count_shown_in_message(self):
        entries = [self._e("6/5", "BC"), self._e("6/6", "BC"), self._e("6/7", "BC")]
        breach, reason = redflag_breach(
            "churn_reasons", entries=entries,
            window_days=30, reason_threshold=2, today=self.TODAY,
        )
        assert breach is True
        assert "×3" in reason or "x3" in reason.lower() or "3" in reason
```

- [ ] **Step 3.2: Run to verify these tests fail**

```bash
pytest tests/test_gtm_metrics.py::TestPaceBreach tests/test_gtm_metrics.py::TestRedflagOnboarding tests/test_gtm_metrics.py::TestRedflagChurnCount tests/test_gtm_metrics.py::TestRedflagChurnReasons -v --tb=short
```
Expected: `ImportError: cannot import name 'pace_breach' from 'lib.gtm_metrics'`

- [ ] **Step 3.3: Append breach functions to `lib/gtm_metrics.py`**

Add after `_month_business_days`:

```python
# ── Breach functions ──────────────────────────────────────────────────────────


def pace_breach(
    current: int,
    target: int,
    today: date,
    early_guard_pct: float,
    sales_frame: bool = False,
) -> tuple[bool, str]:
    """Linear month-pace breach. Returns (is_breach, reason).

    No breach emitted before early_guard_pct of the month's business days have elapsed.
    sales_frame=True reframes the reason to point at the demo pipeline, not today's closes.
    """
    elapsed, total = _month_business_days(today)
    if total == 0 or elapsed == 0:
        return False, ""

    pct_elapsed = elapsed / total
    if pct_elapsed < early_guard_pct:
        return False, ""

    projected = current * (total / elapsed)
    if projected < target:
        pct_str = f"{pct_elapsed:.0%}"
        if sales_frame:
            reason = (
                f"on pace for {projected:.0f} closes vs {target} target "
                f"({pct_str} of month) — pipeline is the lever"
            )
        else:
            reason = (
                f"on pace for {projected:.0f} vs target {target} "
                f"({pct_str} of month)"
            )
        return True, reason

    return False, ""


def _parse_month_day(date_str: str, year: int) -> date | None:
    """Parse 'M/D' string to a date using the given year. Returns None on failure."""
    try:
        parts = (date_str or "").strip().split("/")
        if len(parts) < 2:
            return None
        return date(year, int(parts[0]), int(parts[1]))
    except (ValueError, TypeError):
        return None


def redflag_breach(
    metric_id: str,
    current: int = 0,
    threshold: int = 0,
    entries: list[dict] | None = None,
    window_days: int = 30,
    reason_threshold: int = 2,
    today: date | None = None,
) -> tuple[bool, str]:
    """State-condition breach. Returns (is_breach, reason).

    onboarding_coverage: breach if current < threshold.
    churn_count: breach if current > threshold.
    churn_reasons: breach if same reason appears >= reason_threshold times
        within window_days of today in entries[].reason.
    """
    _today = today or date.today()

    if metric_id == "onboarding_coverage":
        if current < threshold:
            return True, f"{current} customers in onboarding (minimum: {threshold})"
        return False, ""

    if metric_id == "churn_count":
        if current > threshold:
            return True, f"{current} cancellations this month (threshold: {threshold})"
        return False, ""

    if metric_id == "churn_reasons":
        if not entries:
            return False, ""
        window_start = _today - timedelta(days=window_days)
        counts: dict[str, int] = {}
        for entry in entries:
            d = _parse_month_day(entry.get("date", ""), _today.year)
            if d is None or d < window_start or d > _today:
                continue
            r = (entry.get("reason") or "").strip()
            if r:
                counts[r] = counts.get(r, 0) + 1
        repeated = [(r, c) for r, c in counts.items() if c >= reason_threshold]
        if repeated:
            repeated.sort(key=lambda x: -x[1])
            details = "; ".join(f'"{r}" ×{c}' for r, c in repeated)
            return True, f"repeated churn reasons (last {window_days}d): {details}"
        return False, ""

    return False, ""
```

- [ ] **Step 3.4: Run to verify tests pass**

```bash
pytest tests/test_gtm_metrics.py -v --tb=short
```
Expected: all tests PASS

- [ ] **Step 3.5: Commit**

```bash
git add lib/gtm_metrics.py tests/test_gtm_metrics.py
git commit -m "feat: add pace_breach and redflag_breach functions"
```

---

## Task 4: `evaluate_metrics` orchestrator

**Files:**
- Modify: `lib/gtm_metrics.py` (append `_leads_last_updated` helper + `evaluate_metrics`)
- Modify: `tests/test_gtm_metrics.py` (append TestEvaluateMetrics class)

- [ ] **Step 4.1: Append failing tests to `tests/test_gtm_metrics.py`**

Add after the existing test classes:

```python
from lib.gtm_metrics import evaluate_metrics

_CFG = {
    "leads_mtd_target": 20,
    "demos_mtd_target": 30,
    "sales_mtd_target": 15,
    "onboarding_coverage_threshold": 5,
    "churn_count_threshold": 2,
    "churn_reason_cluster_threshold": 2,
    "churn_reason_window_days": 30,
    "pace_early_month_guard_pct": 0.25,
    "leads_stale_days": 3,
}
_MID = date(2026, 6, 15)


def _healthy_inputs():
    """All-green inputs evaluated at June 15. No metric should breach."""
    return dict(
        leads_data={"count": 12, "entries": [{"date": "6/14", "name": "A", "source": "B"}]},
        demos_data={"count": 20, "entries": []},
        sales_data={"count": 10, "entries": []},
        onboarding_active=[{} for _ in range(6)],
        cancellations={"count": 1, "entries": [{"date": "6/5", "reason": "Price"}]},
        cfg=_CFG,
        today=_MID,
    )


class TestEvaluateMetrics:
    def test_returns_six_results(self):
        results = evaluate_metrics(**_healthy_inputs())
        assert len(results) == 6

    def test_result_ids_match_metric_def_order(self):
        results = evaluate_metrics(**_healthy_inputs())
        assert [r.id for r in results] == [m.id for m in METRIC_DEFS]

    def test_no_breach_when_all_healthy(self):
        # leads projected 24>=20; demos 40>=30; sales 20>=15; cov 6>=5; churn 1<=2
        results = evaluate_metrics(**_healthy_inputs())
        for r in results:
            assert r.breach is False, f"{r.id} unexpectedly breached: {r.breach_reason}"

    def test_leads_none_shows_not_configured(self):
        inputs = _healthy_inputs()
        inputs["leads_data"] = None
        leads = next(r for r in evaluate_metrics(**inputs) if r.id == "leads_mtd")
        assert leads.current is None
        assert "not configured" in leads.breach_reason

    def test_leads_zero_count_shows_no_data(self):
        inputs = _healthy_inputs()
        inputs["leads_data"] = {"count": 0, "entries": []}
        leads = next(r for r in evaluate_metrics(**inputs) if r.id == "leads_mtd")
        assert leads.current is None
        assert "no data" in leads.breach_reason

    def test_leads_stale_suppresses_breach(self):
        # last entry June 10 = 5 days before June 15; stale_days=3
        inputs = _healthy_inputs()
        inputs["leads_data"] = {
            "count": 4,
            "entries": [{"date": "6/10", "name": "Old Lead", "source": "Web"}],
        }
        leads = next(r for r in evaluate_metrics(**inputs) if r.id == "leads_mtd")
        assert leads.stale is True
        assert leads.breach is False

    def test_leads_pace_breach_when_fresh(self):
        # last entry June 14 (1 day ago, not stale); count=4 → projected 8 < 20
        inputs = _healthy_inputs()
        inputs["leads_data"] = {
            "count": 4,
            "entries": [{"date": "6/14", "name": "A", "source": "B"}],
        }
        leads = next(r for r in evaluate_metrics(**inputs) if r.id == "leads_mtd")
        assert leads.breach is True
        assert leads.stale is False

    def test_onboarding_coverage_breach(self):
        inputs = _healthy_inputs()
        inputs["onboarding_active"] = [{} for _ in range(4)]  # 4 < 5
        cov = next(r for r in evaluate_metrics(**inputs) if r.id == "onboarding_coverage")
        assert cov.breach is True

    def test_churn_count_breach(self):
        inputs = _healthy_inputs()
        inputs["cancellations"] = {"count": 3, "entries": [
            {"date": "6/5", "reason": "A"},
            {"date": "6/6", "reason": "B"},
            {"date": "6/7", "reason": "C"},
        ]}
        churn = next(r for r in evaluate_metrics(**inputs) if r.id == "churn_count")
        assert churn.breach is True

    def test_churn_reason_cluster_breach(self):
        inputs = _healthy_inputs()
        inputs["cancellations"] = {"count": 3, "entries": [
            {"date": "6/5", "reason": "Business Changes"},
            {"date": "6/8", "reason": "Business Changes"},
            {"date": "6/10", "reason": "Price"},
        ]}
        reasons = next(r for r in evaluate_metrics(**inputs) if r.id == "churn_reasons")
        assert reasons.breach is True
        assert "Business Changes" in reasons.breach_reason

    def test_sales_breach_reason_mentions_pipeline(self):
        inputs = _healthy_inputs()
        inputs["sales_data"] = {"count": 2, "entries": []}
        sales = next(r for r in evaluate_metrics(**inputs) if r.id == "sales_mtd")
        assert sales.breach is True
        assert "pipeline" in sales.breach_reason.lower()

    def test_horizons_correct(self):
        results = evaluate_metrics(**_healthy_inputs())
        h = {r.id: r.horizon for r in results}
        assert h["leads_mtd"] == "next-month"
        assert h["demos_mtd"] == "next-month"
        assert h["sales_mtd"] == "this-month"
        assert h["onboarding_coverage"] == "this-month"
        assert h["churn_count"] == "this-month"
        assert h["churn_reasons"] == "this-month"

    def test_cancellations_none_no_crash(self):
        inputs = _healthy_inputs()
        inputs["cancellations"] = None
        results = evaluate_metrics(**inputs)
        churn = next(r for r in results if r.id == "churn_count")
        assert churn.current == 0
        assert churn.breach is False
```

- [ ] **Step 4.2: Run to verify these tests fail**

```bash
pytest tests/test_gtm_metrics.py::TestEvaluateMetrics -v --tb=short
```
Expected: `ImportError: cannot import name 'evaluate_metrics' from 'lib.gtm_metrics'`

- [ ] **Step 4.3: Append `_leads_last_updated` + `evaluate_metrics` to `lib/gtm_metrics.py`**

Add after `redflag_breach`:

```python
# ── Leads staleness helper ────────────────────────────────────────────────────


def _leads_last_updated(entries: list[dict], year: int) -> date | None:
    """Return date of most recent entry in leads data, or None."""
    latest: date | None = None
    for e in entries:
        d = _parse_month_day(e.get("date", ""), year)
        if d is not None and (latest is None or d > latest):
            latest = d
    return latest


# ── Main evaluation ───────────────────────────────────────────────────────────


def evaluate_metrics(
    leads_data: dict | None,
    demos_data: dict | None,
    sales_data: dict | None,
    onboarding_active: list[dict],
    cancellations: dict | None,
    cfg: dict,
    today: date | None = None,
) -> list[MetricResult]:
    """Evaluate all six GTM metrics and return MetricResult objects.

    Args:
        leads_data: from fetch_leads_mtd; None if collector not configured.
        demos_data: from fetch_demos_mtd; None if collector not configured.
        sales_data: from fetch_sales_mtd; None if collector not configured.
        onboarding_active: pre-filtered list from load_onboarding_active.
        cancellations: from fetch_cancellations_mtd; None if not configured.
        cfg: the "gtm" sub-block from config.json.
        today: override date for testing.

    Returns list of six MetricResult objects in METRIC_DEFS order.
    """
    _today = today or date.today()
    guard = cfg.get("pace_early_month_guard_pct", 0.25)
    stale_days = cfg.get("leads_stale_days", 3)
    results: list[MetricResult] = []

    # ── 1. Leads MTD ──────────────────────────────────────────────────────────
    leads_target = cfg.get("leads_mtd_target")
    if leads_data is None:
        results.append(MetricResult(
            id="leads_mtd", label="Leads MTD",
            current=None, target=leads_target,
            breach=False, breach_reason="collector not configured",
            horizon="next-month",
        ))
    else:
        entries = leads_data.get("entries", [])
        count = leads_data.get("count", len(entries))
        if count == 0:
            results.append(MetricResult(
                id="leads_mtd", label="Leads MTD",
                current=None, target=leads_target,
                breach=False, breach_reason="no data",
                horizon="next-month",
            ))
        else:
            last_updated = _leads_last_updated(entries, _today.year)
            is_stale = (
                last_updated is not None
                and (_today - last_updated).days > stale_days
            )
            if is_stale:
                results.append(MetricResult(
                    id="leads_mtd", label="Leads MTD",
                    current=count, target=leads_target,
                    breach=False, breach_reason="",
                    horizon="next-month",
                    stale=True,
                    stale_reason=(
                        f"last entry {(_today - last_updated).days}d ago "
                        f"(threshold: {stale_days}d) — pace flag suppressed"
                    ),
                ))
            elif leads_target is not None:
                breach, reason = pace_breach(count, leads_target, _today, guard)
                results.append(MetricResult(
                    id="leads_mtd", label="Leads MTD",
                    current=count, target=leads_target,
                    breach=breach, breach_reason=reason,
                    horizon="next-month",
                ))
            else:
                results.append(MetricResult(
                    id="leads_mtd", label="Leads MTD",
                    current=count, target=None,
                    breach=False, breach_reason="no target configured",
                    horizon="next-month",
                ))

    # ── 2. Demos MTD ──────────────────────────────────────────────────────────
    demos_target = cfg.get("demos_mtd_target")
    if demos_data is None:
        results.append(MetricResult(
            id="demos_mtd", label="Demos MTD",
            current=None, target=demos_target,
            breach=False, breach_reason="collector not configured",
            horizon="next-month",
        ))
    else:
        count = demos_data.get("count", 0)
        if demos_target is not None:
            breach, reason = pace_breach(count, demos_target, _today, guard)
        else:
            breach, reason = False, "no target configured"
        results.append(MetricResult(
            id="demos_mtd", label="Demos MTD",
            current=count, target=demos_target,
            breach=breach, breach_reason=reason,
            horizon="next-month",
        ))

    # ── 3. Sales MTD (Closes) ─────────────────────────────────────────────────
    sales_target = cfg.get("sales_mtd_target")
    if sales_data is None:
        results.append(MetricResult(
            id="sales_mtd", label="Sales MTD (Closes)",
            current=None, target=sales_target,
            breach=False, breach_reason="collector not configured",
            horizon="this-month",
        ))
    else:
        count = sales_data.get("count", 0)
        if sales_target is not None:
            breach, reason = pace_breach(count, sales_target, _today, guard, sales_frame=True)
        else:
            breach, reason = False, "no target configured"
        results.append(MetricResult(
            id="sales_mtd", label="Sales MTD (Closes)",
            current=count, target=sales_target,
            breach=breach, breach_reason=reason,
            horizon="this-month",
        ))

    # ── 4. Onboarding Coverage ────────────────────────────────────────────────
    cov_threshold = cfg.get("onboarding_coverage_threshold", 5)
    cov_count = len(onboarding_active)
    breach, reason = redflag_breach(
        "onboarding_coverage", current=cov_count, threshold=cov_threshold, today=_today,
    )
    results.append(MetricResult(
        id="onboarding_coverage", label="Onboarding Coverage",
        current=cov_count, target=cov_threshold,
        breach=breach, breach_reason=reason,
        horizon="this-month",
    ))

    # ── 5. Churn Count MTD ────────────────────────────────────────────────────
    churn_threshold = cfg.get("churn_count_threshold", 2)
    cancel_count = (cancellations or {}).get("count", 0)
    breach, reason = redflag_breach(
        "churn_count", current=cancel_count, threshold=churn_threshold, today=_today,
    )
    results.append(MetricResult(
        id="churn_count", label="Churn Count MTD",
        current=cancel_count, target=churn_threshold,
        breach=breach, breach_reason=reason,
        horizon="this-month",
    ))

    # ── 6. Churn Reason Cluster ───────────────────────────────────────────────
    reason_threshold = cfg.get("churn_reason_cluster_threshold", 2)
    window_days = cfg.get("churn_reason_window_days", 30)
    cancel_entries = (cancellations or {}).get("entries", [])
    breach, reason = redflag_breach(
        "churn_reasons",
        entries=cancel_entries,
        window_days=window_days,
        reason_threshold=reason_threshold,
        today=_today,
    )
    results.append(MetricResult(
        id="churn_reasons", label="Churn Reason Cluster",
        current=None, target=reason_threshold,
        breach=breach, breach_reason=reason,
        horizon="this-month",
    ))

    return results
```

- [ ] **Step 4.4: Run to verify all tests pass**

```bash
pytest tests/test_gtm_metrics.py -v --tb=short
```
Expected: all tests PASS

- [ ] **Step 4.5: Commit**

```bash
git add lib/gtm_metrics.py tests/test_gtm_metrics.py
git commit -m "feat: add evaluate_metrics orchestrator"
```

---

## Task 5: `scripts/gtm_dashboard.py` + dashboard tests

The dashboard reads `data/gtm_snapshot.json` (raw collector outputs), calls `evaluate_metrics()`, and writes `output/gtm_dashboard.html`. The snapshot format is:

```json
{
  "generated_at": "2026-06-05T10:00:00Z",
  "leads": {"count": 12, "entries": [{"date": "6/14", "name": "A", "source": "B"}]},
  "demos": {"count": 8, "entries": []},
  "sales": {"count": 5, "revenue": 7500.0, "entries": []},
  "onboarding_active": [{"customer_name": "Acme", "status": "In Progress"}],
  "cancellations": {"count": 1, "entries": [{"date": "6/5", "reason": "Price"}]}
}
```

**Files:**
- Create: `scripts/gtm_dashboard.py`
- Create: `tests/test_gtm_dashboard.py`

- [ ] **Step 5.1: Write failing tests**

```python
# tests/test_gtm_dashboard.py
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Allow import from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.gtm_metrics import MetricResult
from scripts.gtm_dashboard import render_html


_RESULTS = [
    MetricResult(id="leads_mtd", label="Leads MTD", current=12, target=20,
                 breach=False, breach_reason="", horizon="next-month"),
    MetricResult(id="demos_mtd", label="Demos MTD", current=8, target=30,
                 breach=True, breach_reason="on pace for 16 vs target 30 (50% of month)",
                 horizon="next-month"),
    MetricResult(id="sales_mtd", label="Sales MTD (Closes)", current=5, target=15,
                 breach=False, breach_reason="", horizon="this-month"),
    MetricResult(id="onboarding_coverage", label="Onboarding Coverage", current=6, target=5,
                 breach=False, breach_reason="", horizon="this-month"),
    MetricResult(id="churn_count", label="Churn Count MTD", current=1, target=2,
                 breach=False, breach_reason="", horizon="this-month"),
    MetricResult(id="churn_reasons", label="Churn Reason Cluster", current=None, target=2,
                 breach=False, breach_reason="", horizon="this-month"),
]


def test_render_returns_html_string():
    html = render_html(_RESULTS, "2026-06-15T10:00:00Z")
    assert isinstance(html, str)
    assert "<!DOCTYPE html>" in html


def test_render_contains_all_metric_ids():
    html = render_html(_RESULTS, "2026-06-15T10:00:00Z")
    for r in _RESULTS:
        assert r.id in html, f"metric id {r.id!r} missing from HTML"


def test_render_shows_breach_badge_and_reason():
    html = render_html(_RESULTS, "2026-06-15")
    assert "BREACH" in html
    assert "on pace for 16" in html


def test_render_shows_ok_badge():
    results = [MetricResult(id="leads_mtd", label="Leads MTD", current=15, target=20,
                             breach=False, breach_reason="", horizon="next-month")]
    html = render_html(results, "2026-06-15")
    assert "OK" in html


def test_render_shows_stale_badge_and_reason():
    results = [MetricResult(id="leads_mtd", label="Leads MTD", current=5, target=20,
                             breach=False, breach_reason="", horizon="next-month",
                             stale=True, stale_reason="last entry 5d ago")]
    html = render_html(results, "2026-06-15")
    assert "STALE" in html
    assert "last entry 5d ago" in html


def test_render_handles_none_current():
    results = [MetricResult(id="churn_reasons", label="Churn Reason Cluster",
                             current=None, target=2, breach=False, breach_reason="",
                             horizon="this-month")]
    html = render_html(results, "2026-06-15")
    assert "—" in html  # em-dash for None


def test_render_contains_generated_at():
    html = render_html(_RESULTS, "2026-06-15T10:00:00Z")
    assert "2026-06-15T10:00:00Z" in html


def test_render_no_data_badge():
    results = [MetricResult(id="leads_mtd", label="Leads MTD", current=None, target=20,
                             breach=False, breach_reason="no data", horizon="next-month")]
    html = render_html(results, "2026-06-15")
    assert "NO DATA" in html
```

- [ ] **Step 5.2: Run to verify they fail**

```bash
pytest tests/test_gtm_dashboard.py -v --tb=short
```
Expected: `ImportError: No module named 'scripts.gtm_dashboard'` or similar

- [ ] **Step 5.3: Create `scripts/gtm_dashboard.py`**

```python
#!/usr/bin/env python3
"""GTM metrics dashboard — reads data/gtm_snapshot.json, writes output/gtm_dashboard.html."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from lib.gtm_metrics import MetricResult, evaluate_metrics  # noqa: E402

_SNAPSHOT = _ROOT / "data" / "gtm_snapshot.json"
_OUTPUT = _ROOT / "output" / "gtm_dashboard.html"
_CONFIG = _ROOT / "config.json"


def render_html(results: list[MetricResult], generated_at: str) -> str:
    """Return a full HTML string from evaluated MetricResult objects."""

    def _badge(r: MetricResult) -> str:
        if r.stale:
            return '<span class="badge stale">STALE</span>'
        if r.current is None:
            return '<span class="badge no-data">NO DATA</span>'
        if r.breach:
            return '<span class="badge breach">BREACH</span>'
        return '<span class="badge ok">OK</span>'

    def _val(v) -> str:
        if v is None:
            return "—"
        return str(int(v)) if isinstance(v, float) and v == int(v) else str(v)

    def _horizon(h: str) -> str:
        return "Next-Month Signal" if h == "next-month" else "This Month"

    def _row(r: MetricResult) -> str:
        detail = ""
        if r.stale and r.stale_reason:
            detail = f'<div class="det stale-det">⚠ {r.stale_reason}</div>'
        elif r.breach and r.breach_reason:
            detail = f'<div class="det breach-det">▲ {r.breach_reason}</div>'
        row = (
            f'<tr class="{"breach-row" if r.breach else "stale-row" if r.stale else ""}">'
            f'<td class="lbl" data-metric-id="{r.id}">{r.label}</td>'
            f'<td>{_val(r.current)}</td>'
            f'<td>{_val(r.target)}</td>'
            f'<td>{_badge(r)}</td>'
            f'<td class="hz">{_horizon(r.horizon)}</td>'
            f'</tr>'
        )
        if detail:
            row += f'<tr class="det-row"><td colspan="5">{detail}</td></tr>'
        return row

    rows = "\n".join(_row(r) for r in results)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>GTM Metrics</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;color:#1a1a1a;background:#f9f9f9}}
  .hdr{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:28px 32px;border-radius:8px 8px 0 0}}
  .hdr h1{{margin:0;font-size:22px;font-weight:600}}
  .hdr .ts{{margin:4px 0 0;font-size:14px;opacity:.75}}
  .bdy{{background:#fff;padding:28px 32px;border-radius:0 0 8px 8px;border:1px solid #e5e5e5;border-top:none}}
  table{{width:100%;border-collapse:collapse}}
  th{{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#888;text-align:left;padding:0 8px 8px}}
  td{{padding:10px 8px;border-bottom:1px solid #f0f0f0;font-size:14px}}
  .lbl{{font-weight:600}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600}}
  .ok{{background:#e8f5e9;color:#2e7d32}}
  .breach{{background:#fce4e4;color:#c62828}}
  .stale{{background:#fff3e0;color:#e65100}}
  .no-data{{background:#f5f5f5;color:#888}}
  .breach-row td{{background:#fff8f8}}
  .stale-row td{{background:#fffdf0}}
  .det-row td{{padding:2px 8px 10px;font-size:13px;color:#666}}
  .breach-det{{color:#c62828}}
  .stale-det{{color:#e65100}}
  .hz{{font-size:12px;color:#888}}
  .footer{{text-align:center;padding:16px;font-size:12px;color:#aaa}}
</style>
</head>
<body>
<div class="hdr"><h1>GTM Metrics</h1><div class="ts">Generated {generated_at}</div></div>
<div class="bdy">
<table>
<thead><tr><th>Metric</th><th>Current</th><th>Target</th><th>Status</th><th>Horizon</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<div class="footer">Chief of Staff · GTM Dashboard</div>
</body>
</html>"""


def main() -> None:
    snapshot_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _SNAPSHOT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _OUTPUT

    cfg_gtm = json.loads(_CONFIG.read_text()).get("gtm", {})

    if not snapshot_path.exists():
        print(f"Snapshot not found: {snapshot_path}", file=sys.stderr)
        print("Populate data/gtm_snapshot.json first (see doc 2 for daily-run wiring).", file=sys.stderr)
        sys.exit(1)

    snap = json.loads(snapshot_path.read_text())
    results = evaluate_metrics(
        leads_data=snap.get("leads"),
        demos_data=snap.get("demos"),
        sales_data=snap.get("sales"),
        onboarding_active=snap.get("onboarding_active", []),
        cancellations=snap.get("cancellations"),
        cfg=cfg_gtm,
    )
    html = render_html(results, snap.get("generated_at", "unknown"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.4: Run to verify tests pass**

```bash
pytest tests/test_gtm_dashboard.py -v --tb=short
```
Expected: all tests PASS

- [ ] **Step 5.5: Commit**

```bash
git add scripts/gtm_dashboard.py tests/test_gtm_dashboard.py
git commit -m "feat: add gtm_dashboard.py with render_html and main runner"
```

---

## Task 6: Full regression check

- [ ] **Step 6.1: Run the full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -40
```
Expected: all pre-existing tests still pass; no new failures.

- [ ] **Step 6.2: Spot-check: verify JSON is still valid**

```bash
python3 -c "import json; json.load(open('config.json')); print('config valid')"
```
Expected: `config valid`

- [ ] **Step 6.3: Final commit if any stray changes**

If `git status` shows unstaged files from this work, stage and commit them. Otherwise skip.

---

## Self-review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| One place for six metric defs (id, label, source, current-value, target, cadence, breach rule) | Task 2 — `METRIC_DEFS` + `evaluate_metrics` |
| `pace_breach` — linear month-pace, early-month guard, closes framed at demo lever | Task 3 |
| `redflag_breach` — onboarding < 5, churn > 2, same reason ≥ 2 in window | Task 3 |
| Two horizons tagged per metric | Tasks 2, 4 |
| Leads staleness — suppress pace flag, surface staleness | Task 4 |
| Targets + thresholds in config | Task 1 |
| Dashboard renders all six with current/target/breach | Task 5 |
| Single source of truth (dashboard calls `evaluate_metrics`, not serialized results) | Task 5 — `main()` reads raw snapshot, calls `evaluate_metrics` |
| Out of scope: brief overhaul | Not in this plan |

**Placeholder scan:** None found — all steps contain complete code.

**Type consistency:**
- `_count_business_days`, `_month_business_days` defined Task 2, used in `pace_breach` Task 3 ✓
- `_parse_month_day` defined Task 3, used in `redflag_breach` Task 3 and `_leads_last_updated` Task 4 ✓
- `MetricResult` fields (`id`, `label`, `current`, `target`, `breach`, `breach_reason`, `horizon`, `stale`, `stale_reason`) defined Task 2, used consistently in Task 4 ✓
- `render_html(results: list[MetricResult], generated_at: str)` defined and tested Task 5 ✓
