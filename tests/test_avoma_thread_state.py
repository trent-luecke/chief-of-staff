import pytest
from lib.storage import LocalStorage


def _s(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return s


def test_is_processed_false_for_new_thread(tmp_path):
    from processors.avoma_thread_state import is_processed
    assert is_processed(_s(tmp_path), "1234.5678") is False


def test_set_phase1_complete_marks_processed(tmp_path):
    from processors.avoma_thread_state import is_processed, set_phase1_complete
    s = _s(tmp_path)
    set_phase1_complete(s, "1234.5678", "uuid-abc", "1234.9999", "output text", {"uuid": "uuid-abc"})
    assert is_processed(s, "1234.5678") is True


def test_get_thread_record_returns_correct_fields(tmp_path):
    from processors.avoma_thread_state import set_phase1_complete, get_thread_record
    s = _s(tmp_path)
    set_phase1_complete(s, "1234.5678", "uuid-abc", "1234.9999", "output text", {"uuid": "uuid-abc"})
    rec = get_thread_record(s, "1234.5678")
    assert rec["phase"] == 2
    assert rec["avoma_uuid"] == "uuid-abc"
    assert rec["output_ts"] == "1234.9999"
    assert rec["phase1_output"] == "output text"
    assert rec["pending_correction"] is None
    assert "processed_at" in rec


def test_get_thread_record_returns_none_for_unknown(tmp_path):
    from processors.avoma_thread_state import get_thread_record
    assert get_thread_record(_s(tmp_path), "no-such-thread") is None


def test_set_pending_correction_stores_data(tmp_path):
    from processors.avoma_thread_state import set_phase1_complete, set_pending_correction, get_thread_record
    s = _s(tmp_path)
    set_phase1_complete(s, "1234.5678", None, None, "", {})
    correction = {"description": "fix name", "writes": [], "confirmation_prompt": "Reply yes", "notion_payload": None}
    set_pending_correction(s, "1234.5678", correction)
    rec = get_thread_record(s, "1234.5678")
    assert rec["pending_correction"]["description"] == "fix name"


def test_clear_pending_correction_sets_none(tmp_path):
    from processors.avoma_thread_state import set_phase1_complete, set_pending_correction, clear_pending_correction, get_thread_record
    s = _s(tmp_path)
    set_phase1_complete(s, "1234.5678", None, None, "", {})
    set_pending_correction(s, "1234.5678", {"description": "x", "writes": [], "confirmation_prompt": "y", "notion_payload": None})
    clear_pending_correction(s, "1234.5678")
    assert get_thread_record(s, "1234.5678")["pending_correction"] is None


def test_set_pending_correction_noop_for_unknown_thread(tmp_path):
    from processors.avoma_thread_state import set_pending_correction
    # must not raise
    set_pending_correction(_s(tmp_path), "no-such", {"description": "x", "writes": [], "confirmation_prompt": "y", "notion_payload": None})


def test_multiple_threads_tracked_independently(tmp_path):
    from processors.avoma_thread_state import set_phase1_complete, is_processed
    s = _s(tmp_path)
    set_phase1_complete(s, "thread-A", "uuid-1", None, "", {})
    assert is_processed(s, "thread-A") is True
    assert is_processed(s, "thread-B") is False
