# tests/test_git_sync.py
from lib.git_sync import _union_merge_lines


def test_union_merge_appends_only_new_lines():
    existing = '{"id":"a"}\n{"id":"b"}\n'
    incoming = '{"id":"a"}\n{"id":"b"}\n{"id":"c"}\n'
    merged = _union_merge_lines(existing, incoming)
    assert merged == '{"id":"a"}\n{"id":"b"}\n{"id":"c"}\n'


def test_union_merge_preserves_concurrent_remote_lines():
    # `existing` simulates origin/main having a line our buffer never saw
    existing = '{"id":"a"}\n{"id":"remote"}\n'
    incoming = '{"id":"a"}\n{"id":"mine"}\n'
    merged = _union_merge_lines(existing, incoming)
    assert merged == '{"id":"a"}\n{"id":"remote"}\n{"id":"mine"}\n'


def test_union_merge_empty_existing():
    assert _union_merge_lines("", '{"id":"a"}\n') == '{"id":"a"}\n'


def test_union_merge_empty_incoming():
    assert _union_merge_lines('{"id":"a"}\n', "") == '{"id":"a"}\n'


# append to tests/test_git_sync.py
import subprocess
from unittest.mock import patch
import lib.git_sync as gs


def test_fetch_main_true_on_success():
    with patch("lib.git_sync.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        assert gs.fetch_main() is True


def test_fetch_main_false_on_timeout():
    with patch("lib.git_sync.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 8)):
        assert gs.fetch_main() is False


def test_fetch_main_false_on_nonzero():
    with patch("lib.git_sync.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 128, b"", b"fatal")
        assert gs.fetch_main() is False


def test_show_main_returns_stdout():
    with patch("lib.git_sync.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, '{"id":"a"}\n', "")
        assert gs.show_main("data/tasks.jsonl") == '{"id":"a"}\n'


def test_show_main_none_when_absent():
    with patch("lib.git_sync.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 128, "", "does not exist")
        assert gs.show_main("data/missing.jsonl") is None
