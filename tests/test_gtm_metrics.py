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
