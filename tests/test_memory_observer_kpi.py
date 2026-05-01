import json
import tempfile
import os
from datetime import date

import pytest

from processors.memory_observer import observe, _kpi_snapshot_exists_today


def _make_obs_file(tmp_path, lines=None):
    path = tmp_path / "observations.jsonl"
    if lines:
        with open(path, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
    else:
        path.touch()
    return str(path)


def _make_decisions_file(tmp_path):
    path = tmp_path / "decisions.md"
    path.touch()
    return str(path)


def test_kpi_snapshot_written_when_sales_data_provided(tmp_path):
    obs_file = _make_obs_file(tmp_path)
    decisions_file = _make_decisions_file(tmp_path)

    from collectors.gmail import EmailThread
    from collectors.pipeline import PipelineLead
    from processors.brief import BriefContent
    from processors.issues import Issue

    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(executive_summary="test", top_3_priorities=[]),
        issues=[],
        sales_data={"count": 8, "revenue": 1200.0, "entries": []},
        demos_data={"count": 3, "entries": []},
        bugs=[],
        cancellations={"count": 1, "entries": []},
    )

    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 1
    assert "Sales MTD" in snapshots[0]["content"]
    assert "1200" in snapshots[0]["content"] or "1,200" in snapshots[0]["content"]
    assert "Demos MTD: 3" in snapshots[0]["content"]
    assert "Cancellations MTD: 1" in snapshots[0]["content"]
    assert snapshots[0]["date"] == date.today().isoformat()


def test_kpi_snapshot_not_duplicated_on_rerun(tmp_path):
    today = date.today().isoformat()
    existing = {"date": today, "type": "kpi_snapshot", "entity": "daily",
                "content": "KPI snapshot already written", "source": "kpi"}
    obs_file = _make_obs_file(tmp_path, lines=[existing])
    decisions_file = _make_decisions_file(tmp_path)

    from collectors.gmail import EmailThread
    from processors.brief import BriefContent

    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(executive_summary="test", top_3_priorities=[]),
        issues=[],
        sales_data={"count": 5, "revenue": 800.0, "entries": []},
        demos_data={"count": 2, "entries": []},
        bugs=[],
        cancellations={"count": 0, "entries": []},
    )

    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 1  # still only one


def test_kpi_snapshot_not_written_when_no_kpi_data(tmp_path):
    obs_file = _make_obs_file(tmp_path)
    decisions_file = _make_decisions_file(tmp_path)

    from processors.brief import BriefContent

    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(executive_summary="test", top_3_priorities=[]),
        issues=[],
    )

    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 0


def test_kpi_snapshot_exists_today_detects_existing(tmp_path):
    today = date.today().isoformat()
    obs_file = _make_obs_file(tmp_path, lines=[
        {"date": today, "type": "kpi_snapshot", "entity": "daily", "content": "x", "source": "kpi"},
    ])
    assert _kpi_snapshot_exists_today(obs_file) is True


def test_kpi_snapshot_exists_today_returns_false_when_absent(tmp_path):
    obs_file = _make_obs_file(tmp_path)
    assert _kpi_snapshot_exists_today(obs_file) is False
