import json
from datetime import datetime, timezone, timedelta
from lib.notion_queue import (
    append_entries, parse_jsonl, read_queue, prune_text, prune_file, DEFAULT_QUEUE_PATH,
)


def test_default_path_is_jsonl():
    assert DEFAULT_QUEUE_PATH == "data/notion_updates_queue.jsonl"


def test_append_entries_writes_one_line_each(tmp_path):
    p = tmp_path / "q.jsonl"
    n = append_entries(str(p), [{"id": "a"}, {"id": "b"}])
    assert n == 2
    lines = p.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "a"


def test_append_entries_appends_not_overwrites(tmp_path):
    p = tmp_path / "q.jsonl"
    append_entries(str(p), [{"id": "a"}])
    append_entries(str(p), [{"id": "b"}])
    assert [e["id"] for e in read_queue(str(p))] == ["a", "b"]


def test_append_entries_empty_is_noop(tmp_path):
    p = tmp_path / "q.jsonl"
    assert append_entries(str(p), []) == 0
    assert not p.exists()


def test_parse_jsonl_skips_blank_and_corrupt():
    text = '{"id": "a"}\n\n  \nnot json\n{"id": "b"}\n'
    assert [e["id"] for e in parse_jsonl(text)] == ["a", "b"]


def test_read_queue_missing_file_is_empty(tmp_path):
    assert read_queue(str(tmp_path / "nope.jsonl")) == []


def test_prune_text_drops_old_keeps_recent_and_undated():
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    old = (now - timedelta(days=40)).isoformat()
    recent = (now - timedelta(days=5)).isoformat()
    text = (
        json.dumps({"id": "old", "timestamp": old}) + "\n"
        + json.dumps({"id": "recent", "timestamp": recent}) + "\n"
        + json.dumps({"id": "undated"}) + "\n"
    )
    kept = [e["id"] for e in parse_jsonl(prune_text(text, 30, now))]
    assert "old" not in kept
    assert "recent" in kept and "undated" in kept


def test_prune_text_naive_timestamp_treated_as_utc_not_crash():
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    old_naive = "2026-06-01T00:00:00"      # 40+ days old, NO tz offset
    recent_naive = (now - timedelta(days=3)).replace(tzinfo=None).isoformat()  # naive, recent
    text = (
        json.dumps({"id": "old", "timestamp": old_naive}) + "\n"
        + json.dumps({"id": "recent", "timestamp": recent_naive}) + "\n"
    )
    kept = [e["id"] for e in parse_jsonl(prune_text(text, 30, now))]   # must not raise
    assert "old" not in kept and "recent" in kept


def test_prune_file_rewrites_and_returns_removed(tmp_path):
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    old = (now - timedelta(days=40)).isoformat()
    p = tmp_path / "q.jsonl"
    append_entries(str(p), [{"id": "old", "timestamp": old}, {"id": "keep"}])
    removed = prune_file(str(p), 30, now)
    assert removed == 1
    assert [e["id"] for e in read_queue(str(p))] == ["keep"]
