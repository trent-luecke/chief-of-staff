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


# --- Data loading tests ---

def test_load_observations_window_filters_by_days(tmp_path):
    from processors.pattern_detector import _load_observations_window
    storage = LocalStorage(base_dir=str(tmp_path))
    run_date = date(2026, 5, 4)
    _write_obs(storage, [
        {"date": "2026-05-02", "type": "pipeline_stale", "entity": "acme", "content": "stale"},
        {"date": "2026-04-01", "type": "pipeline_stale", "entity": "old", "content": "old"},
    ])
    result = _load_observations_window(storage, run_date, days=28)
    assert len(result) == 1
    assert result[0]["entity"] == "acme"


def test_load_prior_weekly_patterns_returns_sorted_descending(tmp_path):
    from processors.pattern_detector import _load_prior_weekly_patterns
    storage = LocalStorage(base_dir=str(tmp_path))
    run_date = date(2026, 5, 4)
    storage.write("weekly/2026-04-27.md", "## Patterns\n- Pattern A\n")
    storage.write("weekly/2026-04-20.md", "## Patterns\n- Pattern B\n")
    storage.write("weekly/2026-05-04.md", "## Patterns\n- Current\n")  # excluded (not before run_date)
    result = _load_prior_weekly_patterns(storage, run_date, lookback_weeks=4)
    assert len(result) == 2
    assert result[0]["date"] == "2026-04-27"
    assert result[0]["patterns"] == ["Pattern A"]
    assert result[1]["date"] == "2026-04-20"


def test_load_prior_weekly_patterns_insufficient_history(tmp_path):
    from processors.pattern_detector import _load_prior_weekly_patterns
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write("weekly/2026-04-27.md", "## Patterns\n- Only one\n")
    result = _load_prior_weekly_patterns(storage, date(2026, 5, 4), lookback_weeks=4)
    assert len(result) == 1


# --- Delta computation tests ---

def test_compute_weekly_metrics_counts_stale_entities(tmp_path):
    from processors.pattern_detector import _compute_weekly_metrics
    run_date = date(2026, 5, 4)
    obs = [
        {"date": "2026-05-01", "type": "pipeline_stale", "entity": "acme", "content": ""},
        {"date": "2026-05-02", "type": "pipeline_stale", "entity": "acme", "content": ""},  # same entity, deduped
        {"date": "2026-05-03", "type": "pipeline_stale", "entity": "globo-gym", "content": ""},
    ]
    result = _compute_weekly_metrics(obs, run_date)
    # Bucket 0 = current week
    assert result[0]["pipeline_stale_count"] == 2  # acme + globo-gym (unique entities)


def test_compute_weekly_metrics_counts_issues_by_channel(tmp_path):
    from processors.pattern_detector import _compute_weekly_metrics
    run_date = date(2026, 5, 4)
    obs = [
        {"date": "2026-05-01", "type": "issue_pattern", "entity": "gmail", "content": "", "context": "source: gmail#gmail"},
        {"date": "2026-05-01", "type": "issue_pattern", "entity": "slack", "content": "", "context": "source: slack#support"},
    ]
    result = _compute_weekly_metrics(obs, run_date)
    assert result[0]["issue_email_count"] == 1
    assert result[0]["issue_slack_count"] == 1


def test_compute_weekly_metrics_extracts_kpi_snapshot(tmp_path):
    from processors.pattern_detector import _compute_weekly_metrics
    run_date = date(2026, 5, 4)
    obs = [
        {
            "date": "2026-05-01",
            "type": "kpi_snapshot",
            "entity": "daily",
            "content": "",
            "context": "sales_revenue=12000 bugs_high=3 cancellations_mtd=2 demos=8",
        }
    ]
    result = _compute_weekly_metrics(obs, run_date)
    assert result[0]["bugs_high"] == 3
    assert result[0]["cancellations_mtd"] == 2


def test_compute_demo_trend_last_snapshot_per_month():
    from processors.pattern_detector import _compute_demo_trend
    run_date = date(2026, 5, 4)
    obs = [
        {"date": "2026-04-15", "type": "kpi_snapshot", "entity": "daily", "content": "", "context": "demos=5"},
        {"date": "2026-04-28", "type": "kpi_snapshot", "entity": "daily", "content": "", "context": "demos=9"},  # latest April
        {"date": "2026-03-31", "type": "kpi_snapshot", "entity": "daily", "content": "", "context": "demos=7"},
    ]
    result = _compute_demo_trend(obs, run_date)
    assert len(result) == 2
    april = next(m for m in result if m["month"] == "2026-04")
    assert april["demos"] == 9  # latest entry wins


def test_compute_demo_trend_empty_returns_empty():
    from processors.pattern_detector import _compute_demo_trend
    assert _compute_demo_trend([], date(2026, 5, 4)) == []


from unittest.mock import MagicMock, patch
import json


def test_detect_anomalies_returns_empty_with_insufficient_history(tmp_path):
    from processors.pattern_detector import detect_anomalies, AnomalyReport
    from processors.weekly_synthesizer import WeeklySynthesis
    storage = LocalStorage(base_dir=str(tmp_path))
    # Only one prior weekly file — below the 2-file minimum
    storage.write("weekly/2026-04-27.md", "## Patterns\n- Pattern A\n")
    synthesis = WeeklySynthesis(executive_summary="ok", patterns=["P1"])
    result = detect_anomalies(storage, synthesis, date(2026, 5, 4), "key", "claude-sonnet-4-6")
    assert isinstance(result, AnomalyReport)
    assert result.anomalies == []


def test_detect_anomalies_returns_anomalies_from_claude(tmp_path):
    from processors.pattern_detector import detect_anomalies, PatternAnomaly
    from processors.weekly_synthesizer import WeeklySynthesis
    storage = LocalStorage(base_dir=str(tmp_path))
    run_date = date(2026, 5, 4)
    storage.write("weekly/2026-04-27.md", "## Patterns\n- Pattern A\n")
    storage.write("weekly/2026-04-20.md", "## Patterns\n- Pattern B\n")
    synthesis = WeeklySynthesis(executive_summary="ok", patterns=["Stale leads spiking"])
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "anomalies": [{
            "type": "worsening",
            "title": "Stale leads spike",
            "description": "5 stale leads this week vs avg of 1.5.",
            "weeks_seen": 1,
        }]
    }))]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
    with patch("processors.pattern_detector.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = detect_anomalies(storage, synthesis, run_date, "key", "claude-sonnet-4-6")
    assert len(result.anomalies) == 1
    assert result.anomalies[0].type == "worsening"
    assert result.anomalies[0].title == "Stale leads spike"


def test_detect_anomalies_handles_invalid_json_from_claude(tmp_path):
    from processors.pattern_detector import detect_anomalies, AnomalyReport
    from processors.weekly_synthesizer import WeeklySynthesis
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write("weekly/2026-04-27.md", "## Patterns\n- A\n")
    storage.write("weekly/2026-04-20.md", "## Patterns\n- B\n")
    synthesis = WeeklySynthesis(executive_summary="ok", patterns=[])
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not json at all")]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
    with patch("processors.pattern_detector.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = detect_anomalies(storage, synthesis, date(2026, 5, 4), "key", "claude-sonnet-4-6")
    assert isinstance(result, AnomalyReport)
    assert result.anomalies == []


def test_build_anomaly_prompt_includes_metrics_and_patterns():
    from processors.pattern_detector import _build_anomaly_prompt
    from processors.weekly_synthesizer import WeeklySynthesis
    synthesis = WeeklySynthesis(executive_summary="ok", patterns=["Lead follow-ups high"])
    weekly_metrics = [
        {"label": "current week", "week_start": "2026-04-27", "week_end": "2026-05-04",
         "pipeline_stale_count": 4, "issue_email_count": 2, "issue_slack_count": 1,
         "bugs_high": 3, "cancellations_mtd": 1},
    ]
    demo_trend = [{"month": "2026-04", "demos": 8}, {"month": "2026-03", "demos": 10}]
    prior_patterns = [{"date": "2026-04-27", "patterns": ["Pattern A"]}]
    prompt = _build_anomaly_prompt(synthesis, date(2026, 5, 4), weekly_metrics, demo_trend, prior_patterns)
    assert "Lead follow-ups high" in prompt
    assert "pipeline_stale_count" not in prompt  # should be formatted, not raw key names
    assert "2026-04" in prompt
    assert "Pattern A" in prompt
