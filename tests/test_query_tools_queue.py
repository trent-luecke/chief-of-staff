import json
from processors.query_tools import _tool_queue_notion_update
from lib.notion_queue import read_queue


def test_queue_tool_appends_jsonl_line(tmp_path):
    q = tmp_path / "q.jsonl"
    cfg = {"notion_queue_path": str(q)}
    _tool_queue_notion_update("Jane Doe", "add_note", cfg, note="Called, left VM")
    entries = read_queue(str(q))
    assert len(entries) == 1
    e = entries[0]
    assert e["source"] == "manual" and e["target"] == "pipeline"
    assert e["name"] == "Jane Doe" and e["action"] == "add_note"
    assert e["note"] == "Called, left VM"
    assert e["id"] and e["timestamp"]


def test_queue_tool_two_calls_dont_clobber(tmp_path):
    q = tmp_path / "q.jsonl"
    cfg = {"notion_queue_path": str(q)}
    _tool_queue_notion_update("A Corp", "update_stage", cfg, stage="Trial")
    _tool_queue_notion_update("B Corp", "add_note", cfg, note="hi")
    assert [e["name"] for e in read_queue(str(q))] == ["A Corp", "B Corp"]


def test_queue_tool_delete_requires_reason(tmp_path):
    q = tmp_path / "q.jsonl"
    cfg = {"notion_queue_path": str(q)}
    msg = _tool_queue_notion_update("X", "delete_record", cfg)
    assert "reason is required" in msg
    assert read_queue(str(q)) == []


def test_queue_tool_rejects_bad_action(tmp_path):
    cfg = {"notion_queue_path": str(tmp_path / "q.jsonl")}
    msg = _tool_queue_notion_update("X", "frobnicate", cfg)
    assert "Invalid action" in msg
