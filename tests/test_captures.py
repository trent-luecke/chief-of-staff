import os
import tempfile
from lib.captures import append_capture, load_recent_captures, load_brief_feedback


def test_append_capture_creates_line_with_type_and_content():
    with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
        path = f.name
    try:
        append_capture(path, "todo", "Marcus", "Call back re: contract")
        content = open(path).read()
        assert "[todo]" in content
        assert "Marcus" in content
        assert "Call back re: contract" in content
    finally:
        os.unlink(path)


def test_append_capture_no_target():
    with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
        path = f.name
    try:
        append_capture(path, "idea", None, "Write a blog post")
        content = open(path).read()
        assert "[idea]" in content
        assert "Write a blog post" in content
    finally:
        os.unlink(path)


def test_append_capture_multiple_entries_accumulate():
    with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
        path = f.name
    try:
        append_capture(path, "todo", None, "First capture")
        append_capture(path, "flag", "Apex", "Second capture")
        lines = [l for l in open(path).read().splitlines() if l.strip()]
        assert len(lines) == 2
    finally:
        os.unlink(path)


def test_load_recent_captures_returns_empty_when_file_missing():
    result = load_recent_captures("/tmp/nonexistent_captures_xyz.md")
    assert result == ""


def test_load_brief_feedback_returns_empty_when_file_missing():
    result = load_brief_feedback("/tmp/nonexistent_feedback_xyz.md")
    assert result == ""


def test_load_brief_feedback_truncates_to_token_budget():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        path = f.name
        f.write("x" * 10000)
    try:
        result = load_brief_feedback(path, token_budget=100)
        assert len(result) <= 400 + 50  # 100 tokens * 4 chars + small buffer
    finally:
        os.unlink(path)
