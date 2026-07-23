# tests/test_decisions.py
from lib.storage import LocalStorage
from lib.decisions import append_decision


def test_append_decision_appends_dated_line(tmp_path):
    storage = LocalStorage(str(tmp_path))
    # seed an existing decisions file (no trailing newline) to prove append behavior
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "decisions.md").write_text("2026-01-01: existing decision", encoding="utf-8")

    line = append_decision(storage, "Ship parse-internal-meeting skill", "2026-07-23")

    assert line == "2026-07-23: Ship parse-internal-meeting skill"
    content = (tmp_path / "memory" / "decisions.md").read_text(encoding="utf-8")
    assert content.splitlines()[-1] == "2026-07-23: Ship parse-internal-meeting skill"
    # existing content preserved
    assert content.splitlines()[0] == "2026-01-01: existing decision"


def test_append_decision_creates_file_when_missing(tmp_path):
    storage = LocalStorage(str(tmp_path))
    line = append_decision(storage, "First decision", "2026-07-23")
    assert line == "2026-07-23: First decision"
    content = (tmp_path / "memory" / "decisions.md").read_text(encoding="utf-8")
    assert "2026-07-23: First decision" in content
