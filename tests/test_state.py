import json
import os
from datetime import date
import pytest
from processors.state import StateSnapshot, save_snapshot, load_snapshot, diff_snapshots


def make_snapshot(date_str: str, email_thread_ids: list, notion_item_ids: list) -> StateSnapshot:
    return StateSnapshot(
        date=date_str,
        open_email_thread_ids=email_thread_ids,
        open_notion_item_ids=notion_item_ids,
    )


def test_save_and_load_snapshot(tmp_path):
    snap = make_snapshot("2026-04-16", ["thread_001", "thread_002"], ["notion_abc"])
    save_snapshot(snap, state_dir=str(tmp_path))
    loaded = load_snapshot(date(2026, 4, 16), state_dir=str(tmp_path))
    assert loaded is not None
    assert loaded.open_email_thread_ids == ["thread_001", "thread_002"]
    assert loaded.open_notion_item_ids == ["notion_abc"]


def test_load_snapshot_missing_returns_none(tmp_path):
    result = load_snapshot(date(2026, 4, 1), state_dir=str(tmp_path))
    assert result is None


def test_diff_snapshots_identifies_resolved_emails():
    yesterday = make_snapshot("2026-04-16", ["thread_001", "thread_002"], [])
    today_ids = ["thread_002"]  # thread_001 disappeared = was replied to
    resolved, still_open = diff_snapshots(yesterday, today_email_ids=today_ids, today_notion_ids=[])
    assert "thread_001" in resolved["email"]
    assert "thread_002" in still_open["email"]


def test_diff_snapshots_identifies_resolved_notion():
    yesterday = make_snapshot("2026-04-16", [], ["notion_abc", "notion_xyz"])
    resolved, still_open = diff_snapshots(yesterday, today_email_ids=[], today_notion_ids=["notion_xyz"])
    assert "notion_abc" in resolved["notion"]
    assert "notion_xyz" in still_open["notion"]


def test_diff_snapshots_all_new_no_previous():
    yesterday = make_snapshot("2026-04-16", [], [])
    resolved, still_open = diff_snapshots(yesterday, today_email_ids=["new_001"], today_notion_ids=[])
    assert resolved == {"email": [], "notion": []}
    assert still_open == {"email": [], "notion": []}


def test_snapshot_file_is_valid_json(tmp_path):
    snap = make_snapshot("2026-04-17", ["t1"], ["n1"])
    save_snapshot(snap, state_dir=str(tmp_path))
    path = os.path.join(str(tmp_path), "state_2026-04-17.json")
    assert os.path.exists(path)
    with open(path) as f:
        data = json.load(f)
    assert data["date"] == "2026-04-17"
    assert data["open_email_thread_ids"] == ["t1"]
