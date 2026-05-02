import pytest
from lib.storage import LocalStorage
from lib.captures import (
    append_capture,
    load_recent_captures,
    complete_capture,
    load_brief_feedback,
    complete_project_next,
)


def test_append_capture_creates_line_with_type_and_content(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    append_capture(storage, "todo", "Marcus", "Call back re: contract")
    content = storage.read("captures.md")
    assert "[todo]" in content
    assert "Marcus" in content
    assert "Call back re: contract" in content


def test_append_capture_no_target(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    append_capture(storage, "idea", None, "Write a blog post")
    content = storage.read("captures.md")
    assert "[idea]" in content
    assert "Write a blog post" in content


def test_append_capture_multiple_entries_accumulate(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    append_capture(storage, "todo", None, "First capture")
    append_capture(storage, "flag", "Apex", "Second capture")
    lines = [l for l in storage.read("captures.md").splitlines() if l.strip()]
    assert len(lines) == 2


def test_load_recent_captures_returns_empty_when_file_missing(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    result = load_recent_captures(storage)
    assert result == ""


def test_load_brief_feedback_returns_empty_when_file_missing(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    result = load_brief_feedback(storage)
    assert result == ""


def test_load_brief_feedback_truncates_to_token_budget(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write("brief_feedback.md", "x" * 10000)
    result = load_brief_feedback(storage, token_budget=100)
    assert len(result) <= 400 + 50  # 100 tokens * 4 chars + small buffer


def test_complete_capture_removes_matching_line(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    append_capture(storage, "todo", "Marcus", "Call back re: contract")
    append_capture(storage, "flag", "Apex", "Elevate")
    removed = complete_capture(storage, "Marcus")
    assert removed is True
    content = storage.read("captures.md")
    assert "Marcus" not in content
    assert "Apex" in content


def test_complete_capture_returns_false_when_no_match(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    append_capture(storage, "todo", None, "Some task")
    result = complete_capture(storage, "nonexistent")
    assert result is False


def test_complete_capture_returns_false_when_file_missing(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    result = complete_capture(storage, "anything")
    assert result is False


def test_complete_project_next_marks_done(tmp_path):
    projects_file = str(tmp_path / "projects.md")
    with open(projects_file, "w") as f:
        f.write("## Project: Alpha\n**Next:** Finish proposal\n")
    result = complete_project_next(projects_file, "Finish proposal")
    assert result is True
    with open(projects_file) as f:
        content = f.read()
    assert "~~Finish proposal~~" in content


def test_complete_project_next_returns_false_when_no_match(tmp_path):
    projects_file = str(tmp_path / "projects.md")
    with open(projects_file, "w") as f:
        f.write("## Project: Alpha\n**Next:** Other task\n")
    result = complete_project_next(projects_file, "nonexistent")
    assert result is False


def test_complete_project_next_returns_false_when_file_missing(tmp_path):
    result = complete_project_next(str(tmp_path / "missing.md"), "anything")
    assert result is False
