import json
from datetime import date

import pytest

from processors.memory_observer import observe, _kpi_snapshot_exists_today
from lib.storage import LocalStorage


def _make_storage(tmp_path, lines=None):
    """Return a LocalStorage rooted at tmp_path, optionally seeding observations."""
    storage = LocalStorage(base_dir=str(tmp_path))
    if lines:
        for line in lines:
            storage.append_line("memory/observations.jsonl", json.dumps(line))
    return storage


def _make_decisions_file(tmp_path):
    path = tmp_path / "decisions.md"
    path.touch()
    return str(path)


def _read_obs(tmp_path):
    obs_path = tmp_path / "memory" / "observations.jsonl"
    if not obs_path.exists():
        return []
    return [json.loads(l) for l in obs_path.read_text().splitlines() if l.strip()]


def test_kpi_snapshot_written_when_sales_data_provided(tmp_path):
    storage = _make_storage(tmp_path)
    decisions_file = _make_decisions_file(tmp_path)

    from processors.brief import BriefContent

    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(act_today=[]),
        issues=[],
        sales_data={"count": 8, "revenue": 1200.0, "entries": []},
        demos_data={"count": 3, "entries": []},
        bugs=[],
        cancellations={"count": 1, "entries": []},
    )

    lines = _read_obs(tmp_path)

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
    storage = _make_storage(tmp_path, lines=[existing])
    decisions_file = _make_decisions_file(tmp_path)

    from processors.brief import BriefContent

    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(act_today=[]),
        issues=[],
        sales_data={"count": 5, "revenue": 800.0, "entries": []},
        demos_data={"count": 2, "entries": []},
        bugs=[],
        cancellations={"count": 0, "entries": []},
    )

    lines = _read_obs(tmp_path)

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 1  # still only one


def test_kpi_snapshot_not_written_when_no_kpi_data(tmp_path):
    storage = _make_storage(tmp_path)
    decisions_file = _make_decisions_file(tmp_path)

    from processors.brief import BriefContent

    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(act_today=[]),
        issues=[],
    )

    lines = _read_obs(tmp_path)

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 0


def test_kpi_snapshot_exists_today_detects_existing(tmp_path):
    today = date.today().isoformat()
    storage = _make_storage(tmp_path, lines=[
        {"date": today, "type": "kpi_snapshot", "entity": "daily", "content": "x", "source": "kpi"},
    ])
    assert _kpi_snapshot_exists_today(storage) is True


def test_kpi_snapshot_exists_today_returns_false_when_absent(tmp_path):
    storage = _make_storage(tmp_path)
    assert _kpi_snapshot_exists_today(storage) is False


def test_kpi_snapshot_yesterday_does_not_block_today(tmp_path):
    from datetime import timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    storage = _make_storage(tmp_path, lines=[
        {"date": yesterday, "type": "kpi_snapshot", "entity": "daily",
         "content": "yesterday's snapshot", "source": "kpi"},
    ])
    decisions_file = _make_decisions_file(tmp_path)

    from processors.brief import BriefContent

    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(act_today=[]),
        issues=[],
        sales_data={"count": 2, "revenue": 300.0, "entries": []},
        demos_data={"count": 1, "entries": []},
        bugs=[],
        cancellations={"count": 0, "entries": []},
    )

    lines = _read_obs(tmp_path)

    today_snapshots = [l for l in lines if l["type"] == "kpi_snapshot" and l["date"] == date.today().isoformat()]
    assert len(today_snapshots) == 1


def test_kpi_snapshot_empty_list_bugs_triggers_snapshot(tmp_path):
    storage = _make_storage(tmp_path)
    decisions_file = _make_decisions_file(tmp_path)

    from processors.brief import BriefContent

    # bugs=[] (not None) should still trigger a snapshot
    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(act_today=[]),
        issues=[],
        bugs=[],
    )

    lines = _read_obs(tmp_path)

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 1
    assert "Open bugs: 0" in snapshots[0]["content"]
