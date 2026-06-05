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
    # count=0 is a valid value (automated sheet); unlike leads (manual), zero here means no activity this month.
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
    # count=0 is a valid value (automated sheet); zero means no closes yet this month.
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
    cov_count = len(onboarding_active or [])
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
