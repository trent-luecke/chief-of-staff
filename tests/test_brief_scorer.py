import json
import os

from processors.brief_scorer import parse_score_command, handle_score_command, save_score
from lib.storage import LocalStorage


def test_parse_valid_score():
    assert parse_score_command("/brief score 4") == (4, None)


def test_parse_score_with_note():
    score, note = parse_score_command("/brief score 2 missed Apex deadline")
    assert score == 2
    assert note == "missed Apex deadline"


def test_parse_not_a_score_command():
    assert parse_score_command("what's on my calendar?") is None
    assert parse_score_command("/brief") is None
    assert parse_score_command("/brief something else") is None


def test_parse_case_insensitive():
    assert parse_score_command("/Brief Score 3") == (3, None)


def test_handle_valid_score(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    response = handle_score_command("/brief score 4", storage=storage)
    assert "4/5" in response
    content = (tmp_path / "state" / "brief_scores.jsonl").read_text()
    entry = json.loads(content.strip().splitlines()[0])
    assert entry["score"] == 4
    assert entry["note"] is None


def test_handle_score_with_note(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    response = handle_score_command("/brief score 2 missed Apex", storage=storage)
    assert "2/5" in response
    assert "missed Apex" in response
    content = (tmp_path / "state" / "brief_scores.jsonl").read_text()
    entry = json.loads(content.strip().splitlines()[0])
    assert entry["note"] == "missed Apex"


def test_handle_out_of_range(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    response = handle_score_command("/brief score 7", storage=storage)
    assert "1" in response and "5" in response
    assert not (tmp_path / "state" / "brief_scores.jsonl").exists()


def test_handle_not_a_command():
    assert handle_score_command("what's on my calendar?") is None


def test_multiple_scores_same_day(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    handle_score_command("/brief score 3", storage=storage)
    handle_score_command("/brief score 5 actually great", storage=storage)
    content = (tmp_path / "state" / "brief_scores.jsonl").read_text()
    lines = [l for l in content.strip().splitlines() if l]
    assert len(lines) == 2
    last = json.loads(lines[-1])
    assert last["score"] == 5
    assert last["note"] == "actually great"


def test_save_score_no_op_without_storage():
    # save_score with storage=None is a no-op (no error)
    save_score(4, storage=None)


def test_score_zero_rejected(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    response = handle_score_command("/brief score 0", storage=storage)
    assert "1" in response and "5" in response
    assert not (tmp_path / "state" / "brief_scores.jsonl").exists()
