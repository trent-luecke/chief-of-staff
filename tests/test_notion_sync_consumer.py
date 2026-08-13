import json
import scripts.notion_sync_consumer as c


def test_fresh_entries_subtracts_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "SEEN_PATH", tmp_path / "seen.json")
    (tmp_path / "seen.json").write_text(json.dumps(["avoma:seen"]))
    queue_text = (
        json.dumps({"id": "avoma:seen", "target": "pipeline"}) + "\n"
        + json.dumps({"id": "avoma:fresh", "target": "onboarding"}) + "\n"
    )
    monkeypatch.setattr(c, "fetch_main_ref", lambda: True)
    monkeypatch.setattr(c, "read_main_queue", lambda: queue_text)
    fresh = c.fresh_entries()
    assert [e["id"] for e in fresh] == ["avoma:fresh"]


def test_mark_seen_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "SEEN_PATH", tmp_path / "seen.json")
    assert c.mark_seen(["a", "b"]) == 2
    assert c.mark_seen(["b", "c"]) == 1  # only c is new
    assert c._load_seen() == {"a", "b", "c"}


def test_record_pending_appends_with_status(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "PENDING_PATH", tmp_path / "pending.jsonl")
    c.record_pending({"id": "avoma:x", "name": "Alina", "target": "onboarding"})
    lines = (tmp_path / "pending.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["name"] == "Alina" and row["status"] == "pending"


def test_build_summary_silent_when_nothing_synced():
    assert c.build_summary({"applied": [], "flagged": [], "pending": []}, "2026-08-13") == ""


def test_build_summary_lists_flagged_and_pending():
    payload = {
        "applied": ["Acme Corp", "Beta LLC"],
        "flagged": ["Created new pipeline record: Beta LLC"],
        "pending": [{"name": "Alina Bushma"}],
    }
    text = c.build_summary(payload, "2026-08-13")
    assert "Notion Sync — 2026-08-13" in text
    assert "Created new pipeline record: Beta LLC" in text
    assert "Alina Bushma" in text
    assert "Synced 2 update(s)" in text
