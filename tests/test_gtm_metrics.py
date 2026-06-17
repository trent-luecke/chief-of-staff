# tests/test_gtm_metrics.py
from datetime import date
import pytest
from lib.gtm_metrics import (
    MetricDef,
    MetricResult,
    METRIC_DEFS,
    _count_business_days,
    _month_business_days,
    pace_breach,
    redflag_breach,
    evaluate_metrics,
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
    def test_five_metrics(self):
        assert len(METRIC_DEFS) == 5

    def test_all_ids_unique(self):
        ids = [m.id for m in METRIC_DEFS]
        assert len(ids) == len(set(ids))

    def test_horizons_are_valid(self):
        for m in METRIC_DEFS:
            assert m.horizon in ("this-month", "next-month"), m.id

    def test_breach_fns_are_valid(self):
        for m in METRIC_DEFS:
            assert m.breach_fn in ("pace_breach", "redflag_breach"), m.id

    def test_demos_is_next_month(self):
        h = {m.id: m.horizon for m in METRIC_DEFS}
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
            id="demos_mtd", label="Demos MTD",
            current=5, target=20,
            breach=False, breach_reason="",
            horizon="next-month",
        )
        assert r.stale is False
        assert r.stale_reason == ""


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
        assert "business changes" in reason.lower()

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

    def test_year_boundary_december_entry_counted_in_january(self):
        # January 15 with 30-day window → window starts Dec 16
        # Entry "12/20" should be counted (Dec 20 of prior year is in window)
        jan_today = date(2026, 1, 15)
        entries = [
            self._e("12/20", "Business Changes"),
            self._e("12/22", "Business Changes"),
        ]
        breach, reason = redflag_breach(
            "churn_reasons", entries=entries,
            window_days=30, reason_threshold=2, today=jan_today,
        )
        assert breach is True
        assert "business changes" in reason.lower()

    def test_case_insensitive_reason_matching(self):
        entries = [
            self._e("6/5", "Business Changes"),
            self._e("6/8", "business changes"),
        ]
        breach, reason = redflag_breach(
            "churn_reasons", entries=entries,
            window_days=30, reason_threshold=2, today=self.TODAY,
        )
        assert breach is True


_CFG = {
    "demos_mtd_target": 30,
    "sales_mtd_target": 15,
    "onboarding_coverage_threshold": 5,
    "churn_count_threshold": 2,
    "churn_reason_cluster_threshold": 2,
    "churn_reason_window_days": 30,
    "pace_early_month_guard_pct": 0.25,
}
_MID = date(2026, 6, 15)


def _healthy_inputs():
    """All-green inputs evaluated at June 15. No metric should breach."""
    return dict(
        demos_data={"count": 20, "entries": []},
        sales_data={"count": 10, "entries": []},
        onboarding_active=[{} for _ in range(6)],
        cancellations={"count": 1, "entries": [{"date": "6/5", "reason": "Price"}]},
        cfg=_CFG,
        today=_MID,
    )


class TestEvaluateMetrics:
    def test_returns_five_results(self):
        results = evaluate_metrics(**_healthy_inputs())
        assert len(results) == 5

    def test_result_ids_match_metric_def_order(self):
        results = evaluate_metrics(**_healthy_inputs())
        assert [r.id for r in results] == [m.id for m in METRIC_DEFS]

    def test_no_breach_when_all_healthy(self):
        # demos 40>=30; sales 20>=15; cov 6>=5; churn 1<=2
        results = evaluate_metrics(**_healthy_inputs())
        for r in results:
            assert r.breach is False, f"{r.id} unexpectedly breached: {r.breach_reason}"

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
        assert "business changes" in reasons.breach_reason.lower()

    def test_sales_breach_reason_mentions_pipeline(self):
        inputs = _healthy_inputs()
        inputs["sales_data"] = {"count": 2, "entries": []}
        sales = next(r for r in evaluate_metrics(**inputs) if r.id == "sales_mtd")
        assert sales.breach is True
        assert "pipeline" in sales.breach_reason.lower()

    def test_horizons_correct(self):
        results = evaluate_metrics(**_healthy_inputs())
        h = {r.id: r.horizon for r in results}
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

    def test_onboarding_active_none_no_crash(self):
        inputs = _healthy_inputs()
        inputs["onboarding_active"] = None
        results = evaluate_metrics(**inputs)
        cov = next(r for r in results if r.id == "onboarding_coverage")
        assert cov.current == 0
        assert cov.breach is True  # 0 < threshold=5



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
