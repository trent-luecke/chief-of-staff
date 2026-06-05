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
