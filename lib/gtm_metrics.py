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
            if d is not None and d > _today:
                d = _parse_month_day(entry.get("date", ""), _today.year - 1)
            if d is None or d < window_start or d > _today:
                continue
            r_raw = (entry.get("reason") or "").strip()
            r = r_raw.lower()
            if r:
                counts[r] = counts.get(r, 0) + 1
        repeated = [(r, c) for r, c in counts.items() if c >= reason_threshold]
        if repeated:
            repeated.sort(key=lambda x: -x[1])
            details = "; ".join(f'"{r}" ×{c}' for r, c in repeated)
            return True, f"repeated churn reasons (last {window_days}d): {details}"
        return False, ""

    return False, ""
