import json
from datetime import date, timedelta

import pytest

from lib.storage import LocalStorage


def _write_obs(storage, entries):
    content = "\n".join(json.dumps(e) for e in entries) + "\n"
    storage.write("memory/observations.jsonl", content)


# --- Pure helper tests ---

def test_parse_kpi_context_extracts_integers():
    from processors.pattern_detector import _parse_kpi_context
    ctx = "sales_revenue=12000 sales_count=3 demos=8 open_bugs=5 bugs_high=2 cancellations_mtd=1"
    result = _parse_kpi_context(ctx)
    assert result["demos"] == 8
    assert result["bugs_high"] == 2
    assert result["cancellations_mtd"] == 1


def test_parse_kpi_context_empty_string():
    from processors.pattern_detector import _parse_kpi_context
    assert _parse_kpi_context("") == {}


def test_parse_kpi_context_ignores_non_integer_values():
    from processors.pattern_detector import _parse_kpi_context
    result = _parse_kpi_context("demos=8 label=foo bugs_high=2")
    assert result["demos"] == 8
    assert result["bugs_high"] == 2
    assert "label" not in result


def test_extract_patterns_section_parses_bullets():
    from processors.pattern_detector import _extract_patterns_section
    content = "# Weekly Synthesis\n\nSome text.\n\n## Patterns\n- Pattern one\n- Pattern two\n\n## Resolved\n- Done thing\n"
    result = _extract_patterns_section(content)
    assert result == ["Pattern one", "Pattern two"]


def test_extract_patterns_section_no_patterns():
    from processors.pattern_detector import _extract_patterns_section
    content = "# Weekly Synthesis\n\nNo patterns section here.\n"
    assert _extract_patterns_section(content) == []


def test_extract_patterns_section_empty_section():
    from processors.pattern_detector import _extract_patterns_section
    content = "## Patterns\n\n## Resolved\n"
    assert _extract_patterns_section(content) == []


def test_week_bucket_current_week():
    from processors.pattern_detector import _week_bucket
    run_date = date(2026, 5, 4)
    assert _week_bucket(date(2026, 5, 4), run_date) == 0
    assert _week_bucket(date(2026, 4, 28), run_date) == 0


def test_week_bucket_prior_weeks():
    from processors.pattern_detector import _week_bucket
    run_date = date(2026, 5, 4)
    assert _week_bucket(date(2026, 4, 27), run_date) == 1
    assert _week_bucket(date(2026, 4, 20), run_date) == 2
    assert _week_bucket(date(2026, 4, 13), run_date) == 3


def test_week_bucket_outside_window_returns_none():
    from processors.pattern_detector import _week_bucket
    run_date = date(2026, 5, 4)
    assert _week_bucket(date(2026, 4, 5), run_date) is None
    assert _week_bucket(date(2026, 5, 5), run_date) is None
