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
