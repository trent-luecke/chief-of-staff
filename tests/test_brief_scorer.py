import json
import os

from processors.brief_scorer import parse_score_command, handle_score_command, save_score


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
    scores_file = str(tmp_path / "scores.jsonl")
    response = handle_score_command("/brief score 4", scores_file=scores_file)
    assert "4/5" in response
    with open(scores_file) as f:
        entry = json.loads(f.readline())
    assert entry["score"] == 4
    assert entry["note"] is None


def test_handle_score_with_note(tmp_path):
    scores_file = str(tmp_path / "scores.jsonl")
    response = handle_score_command("/brief score 2 missed Apex", scores_file=scores_file)
    assert "2/5" in response
    assert "missed Apex" in response
    with open(scores_file) as f:
        entry = json.loads(f.readline())
    assert entry["note"] == "missed Apex"


def test_handle_out_of_range(tmp_path):
    scores_file = str(tmp_path / "scores.jsonl")
    response = handle_score_command("/brief score 7", scores_file=scores_file)
    assert "must be 1-5" in response
    assert not os.path.exists(scores_file)


def test_handle_not_a_command():
    assert handle_score_command("what's on my calendar?") is None


def test_multiple_scores_same_day(tmp_path):
    scores_file = str(tmp_path / "scores.jsonl")
    handle_score_command("/brief score 3", scores_file=scores_file)
    handle_score_command("/brief score 5 actually great", scores_file=scores_file)
    with open(scores_file) as f:
        lines = f.readlines()
    assert len(lines) == 2
    last = json.loads(lines[-1])
    assert last["score"] == 5
    assert last["note"] == "actually great"


def test_save_score_creates_dir(tmp_path):
    scores_file = str(tmp_path / "nested" / "scores.jsonl")
    save_score(4, scores_file=scores_file)
    assert os.path.exists(scores_file)


def test_score_zero_rejected(tmp_path):
    scores_file = str(tmp_path / "scores.jsonl")
    response = handle_score_command("/brief score 0", scores_file=scores_file)
    assert "must be 1-5" in response
    assert not os.path.exists(scores_file)
