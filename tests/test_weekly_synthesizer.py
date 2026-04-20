import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from processors.weekly_synthesizer import (
    _load_week_observations,
    _load_week_state_delta,
    WeeklySynthesis,
)


def _write_obs(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_load_week_observations_filters_to_7_days(tmp_path):
    obs_file = str(tmp_path / "obs.jsonl")
    today = date.today()
    in_range = (today - timedelta(days=3)).isoformat()
    out_of_range = (today - timedelta(days=10)).isoformat()
    _write_obs(obs_file, [
        {"date": in_range, "type": "top_priority", "entity": "e", "content": "recent"},
        {"date": out_of_range, "type": "top_priority", "entity": "e", "content": "old"},
    ])
    result = _load_week_observations(obs_file, run_date=today)
    assert len(result) == 1
    assert result[0]["content"] == "recent"


def test_load_week_observations_empty_file(tmp_path):
    obs_file = str(tmp_path / "missing.jsonl")
    result = _load_week_observations(obs_file, run_date=date.today())
    assert result == []


def test_load_week_state_delta_counts_resolved_and_open(tmp_path):
    state_dir = str(tmp_path)
    today = date.today()
    week_ago = today - timedelta(days=7)

    start = {"date": week_ago.isoformat(), "open_email_thread_ids": ["a", "b", "c"], "open_notion_item_ids": []}
    with open(os.path.join(state_dir, f"state_{week_ago.isoformat()}.json"), "w") as f:
        json.dump(start, f)

    end = {"date": today.isoformat(), "open_email_thread_ids": ["b", "c", "d"], "open_notion_item_ids": []}
    with open(os.path.join(state_dir, f"state_{today.isoformat()}.json"), "w") as f:
        json.dump(end, f)

    resolved_count, still_open_count = _load_week_state_delta(state_dir, run_date=today)
    assert resolved_count == 1
    assert still_open_count == 2


def test_load_week_state_delta_no_snapshots(tmp_path):
    resolved, still_open = _load_week_state_delta(str(tmp_path), run_date=date.today())
    assert resolved == 0
    assert still_open == 0


def test_load_week_state_delta_corrupt_snapshot_returns_zero(tmp_path):
    state_dir = str(tmp_path)
    today = date.today()
    week_ago = today - timedelta(days=7)
    # write a corrupt end snapshot
    with open(os.path.join(state_dir, f"state_{today.isoformat()}.json"), "w") as f:
        f.write("not valid json{{{")
    # valid start snapshot
    start = {"date": week_ago.isoformat(), "open_email_thread_ids": ["a"], "open_notion_item_ids": []}
    with open(os.path.join(state_dir, f"state_{week_ago.isoformat()}.json"), "w") as f:
        json.dump(start, f)
    resolved, still_open = _load_week_state_delta(state_dir, run_date=today)
    assert resolved == 0
    assert still_open == 0


from unittest.mock import MagicMock, patch
from processors.weekly_synthesizer import _build_prompt, synthesize_week


def test_build_prompt_includes_observation_content():
    observations = [
        {"date": "2026-04-18", "type": "top_priority", "entity": "apex", "content": "Follow up Apex"},
        {"date": "2026-04-18", "type": "pipeline_stale", "entity": "acme", "content": "Acme stale 14 days"},
    ]
    prompt = _build_prompt(
        observations=observations,
        resolved_count=3,
        still_open_count=5,
        open_issue_titles=["Slack outage 2d"],
        captures_text="- flag: check Apex contract",
        run_date=date(2026, 4, 20),
    )
    assert "Follow up Apex" in prompt
    assert "Acme stale 14 days" in prompt
    assert "resolved: 3" in prompt.lower()
    assert "still open: 5" in prompt.lower()
    assert "Slack outage 2d" in prompt
    assert "check Apex contract" in prompt


def test_build_prompt_handles_empty_inputs():
    prompt = _build_prompt(
        observations=[],
        resolved_count=0,
        still_open_count=0,
        open_issue_titles=[],
        captures_text="",
        run_date=date(2026, 4, 20),
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 50


def test_synthesize_week_returns_weekly_synthesis(tmp_path):
    obs_file = str(tmp_path / "obs.jsonl")
    state_dir = str(tmp_path)
    _write_obs(obs_file, [
        {"date": date.today().isoformat(), "type": "top_priority", "entity": "e", "content": "finish contracts"},
    ])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "executive_summary": "Solid week with steady pipeline progress.",
        "patterns": ["Pipeline follow-ups dominating priorities"],
        "resolved_this_week": ["Apex contract sent"],
        "carry_forwards": ["Trial conversion for ACME"],
        "meta_observation": "Most priorities were carry-overs from prior week.",
    }))]

    with patch("processors.weekly_synthesizer.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = synthesize_week(
            api_key="test",
            model="claude-sonnet-4-6",
            obs_file=obs_file,
            state_dir=state_dir,
            issues_file=str(tmp_path / "issues.json"),
            captures_file=str(tmp_path / "captures.md"),
            run_date=date.today(),
        )

    assert result.executive_summary == "Solid week with steady pipeline progress."
    assert result.patterns == ["Pipeline follow-ups dominating priorities"]
    assert result.resolved_this_week == ["Apex contract sent"]
    assert result.carry_forwards == ["Trial conversion for ACME"]
    assert result.meta_observation == "Most priorities were carry-overs from prior week."


def test_synthesize_week_raises_on_non_json_response(tmp_path):
    obs_file = str(tmp_path / "obs.jsonl")
    _write_obs(obs_file, [])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not json at all")]

    with patch("processors.weekly_synthesizer.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        with pytest.raises(ValueError):
            synthesize_week(
                api_key="test",
                model="claude-sonnet-4-6",
                obs_file=obs_file,
                state_dir=str(tmp_path),
                issues_file=str(tmp_path / "issues.json"),
                captures_file=str(tmp_path / "captures.md"),
                run_date=date.today(),
            )


def test_load_week_costs_sums_7_days(tmp_path):
    import json
    from datetime import date
    from processors.weekly_synthesizer import _load_week_costs

    log_file = tmp_path / "run_log.jsonl"
    run_date = date(2026, 4, 20)
    entries = [
        {"timestamp": "2026-04-12T07:00:00Z", "estimated_cost_usd": 0.01},  # day 8 — excluded
        {"timestamp": "2026-04-13T07:00:00Z", "estimated_cost_usd": 0.02},  # day 7 — included
        {"timestamp": "2026-04-18T07:00:00Z", "estimated_cost_usd": 0.03},  # included
        {"timestamp": "2026-04-20T07:00:00Z", "estimated_cost_usd": 0.04},  # run_date — included
    ]
    with open(log_file, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    result = _load_week_costs(str(log_file), run_date)
    assert result["call_count"] == 3
    assert abs(result["total_cost_usd"] - 0.09) < 1e-6


def test_load_week_costs_missing_file(tmp_path):
    from datetime import date
    from processors.weekly_synthesizer import _load_week_costs

    result = _load_week_costs(str(tmp_path / "nonexistent.jsonl"), date(2026, 4, 20))
    assert result == {"call_count": 0, "total_cost_usd": 0.0}


def test_load_week_costs_corrupt_lines(tmp_path):
    import json
    from datetime import date
    from processors.weekly_synthesizer import _load_week_costs

    log_file = tmp_path / "run_log.jsonl"
    with open(log_file, "w") as f:
        f.write("not json at all\n")
        f.write(json.dumps({"timestamp": "2026-04-20T07:00:00Z", "estimated_cost_usd": 0.05}) + "\n")
        f.write("{corrupt\n")

    result = _load_week_costs(str(log_file), date(2026, 4, 20))
    assert result["call_count"] == 1
    assert abs(result["total_cost_usd"] - 0.05) < 1e-6
