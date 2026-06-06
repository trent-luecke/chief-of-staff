# tests/test_gtm_dashboard.py
import sys
from pathlib import Path

import pytest

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


def test_render_escapes_html_in_reason():
    results = [MetricResult(id="demos_mtd", label="Demos MTD", current=5, target=30,
                             breach=True,
                             breach_reason='<script>alert("xss")</script>',
                             horizon="next-month")]
    html = render_html(results, "2026-06-15")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
