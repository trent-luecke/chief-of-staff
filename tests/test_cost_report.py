import json
from datetime import date

from lib.cost_report import summarize, parse_log


TODAY = date(2026, 9, 8)


def _entry(day, run_type, model, cost, inp=1000, out=200):
    return {
        "timestamp": f"{day}T12:00:00Z",
        "run_type": run_type,
        "caller": run_type,
        "model": model,
        "input_tokens": inp,
        "output_tokens": out,
        "estimated_cost_usd": cost,
    }


def test_parse_log_skips_blank_and_malformed():
    raw = "\n".join([
        json.dumps(_entry("2026-09-08", "brief", "claude-sonnet-4-6", 0.05)),
        "",
        "{not valid json",
        json.dumps(_entry("2026-09-07", "ask", "claude-sonnet-4-6", 0.02)),
    ])
    entries = parse_log(raw)
    assert len(entries) == 2


def test_summarize_totals():
    entries = [
        _entry("2026-09-08", "brief", "claude-sonnet-4-6", 0.05),
        _entry("2026-09-08", "market_intel", "claude-sonnet-4", 0.10),
        _entry("2026-09-07", "market_intel", "claude-sonnet-4", 0.10),
    ]
    s = summarize(entries, today=TODAY)
    assert s["total_calls"] == 3
    assert abs(s["totals"]["cost_usd"] - 0.25) < 1e-9


def test_by_job_sorted_desc_within_window():
    entries = [
        _entry("2026-09-08", "brief", "claude-sonnet-4-6", 0.05),
        _entry("2026-09-08", "market_intel", "claude-sonnet-4", 0.30),
        _entry("2026-09-06", "market_intel", "claude-sonnet-4", 0.30),
    ]
    s = summarize(entries, today=TODAY)
    by_job = s["by_job"]
    assert by_job[0]["run_type"] == "market_intel"
    assert abs(by_job[0]["cost_usd"] - 0.60) < 1e-9
    assert by_job[0]["calls"] == 2
    assert by_job[1]["run_type"] == "brief"


def test_by_model_aggregation():
    entries = [
        _entry("2026-09-08", "brief", "claude-sonnet-4-6", 0.05),
        _entry("2026-09-08", "scout", "claude-opus-4-8", 0.40),
    ]
    s = summarize(entries, today=TODAY)
    by_model = {m["model"]: m for m in s["by_model"]}
    assert abs(by_model["claude-opus-4-8"]["cost_usd"] - 0.40) < 1e-9
    assert abs(by_model["claude-sonnet-4-6"]["cost_usd"] - 0.05) < 1e-9


def test_window_excludes_old_entries():
    entries = [
        _entry("2026-09-08", "brief", "claude-sonnet-4-6", 0.05),   # in 7d
        _entry("2026-08-01", "brief", "claude-sonnet-4-6", 1.00),   # outside 30d
    ]
    s = summarize(entries, today=TODAY)
    assert abs(s["windows"]["last_7d"]["cost_usd"] - 0.05) < 1e-9
    assert abs(s["windows"]["last_30d"]["cost_usd"] - 0.05) < 1e-9
    # all_time still counts everything
    assert abs(s["windows"]["all_time"]["cost_usd"] - 1.05) < 1e-9


def test_by_job_window_is_30d():
    # by_job reflects the trailing 30 days, not all time.
    entries = [
        _entry("2026-09-08", "brief", "claude-sonnet-4-6", 0.05),
        _entry("2026-06-01", "brief", "claude-sonnet-4-6", 9.99),  # ancient
    ]
    s = summarize(entries, today=TODAY)
    brief = next(j for j in s["by_job"] if j["run_type"] == "brief")
    assert abs(brief["cost_usd"] - 0.05) < 1e-9


def test_handles_missing_cost_field_gracefully():
    entries = [{"timestamp": "2026-09-08T00:00:00Z", "run_type": "x", "model": "m"}]
    s = summarize(entries, today=TODAY)
    assert s["totals"]["cost_usd"] == 0.0
