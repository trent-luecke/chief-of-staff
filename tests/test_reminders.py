import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from lib.storage import LocalStorage
from processors.reminders import set_reminder


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(str(tmp_path))


_CONFIG = {"timezone": "America/Chicago"}

# A known UTC datetime on a 15-min boundary, well in the future
_FUTURE_15 = "2099-01-01T21:00:00Z"
# Same time but NOT on a boundary
_FUTURE_OFF = "2099-01-01T21:07:00Z"
# Clearly in the past
_PAST = "2020-01-01T00:00:00Z"


def test_set_reminder_valid_stores_entry(storage):
    result = set_reminder(storage, "cook dinner", _FUTURE_15, _CONFIG)
    assert "Reminder set for" in result
    assert "cook dinner" in result
    reminders = storage.read_json("reminders.json")
    assert len(reminders) == 1
    assert reminders[0]["message"] == "cook dinner"
    assert reminders[0]["fired"] is False
    assert reminders[0]["fire_at"] == "2099-01-01T21:00:00Z"


def test_set_reminder_rejects_non_aligned_minute(storage):
    result = set_reminder(storage, "cook dinner", _FUTURE_OFF, _CONFIG)
    assert "boundary" in result.lower() or ":07" in result
    assert storage.read_json("reminders.json") is None  # nothing written


def test_set_reminder_rejects_past_time(storage):
    result = set_reminder(storage, "cook dinner", _PAST, _CONFIG)
    assert "past" in result.lower()
    assert storage.read_json("reminders.json") is None


def test_set_reminder_rejects_unparseable_time(storage):
    result = set_reminder(storage, "cook dinner", "not-a-date", _CONFIG)
    assert "parse" in result.lower() or "couldn't" in result.lower()
    assert storage.read_json("reminders.json") is None


def test_set_reminder_default_config_uses_chicago_timezone(storage):
    # No config passed — should default to America/Chicago without error
    result = set_reminder(storage, "cook dinner", _FUTURE_15)
    assert "cook dinner" in result
    reminders = storage.read_json("reminders.json")
    assert len(reminders) == 1


def test_set_reminder_entry_has_id_and_created_at(storage):
    set_reminder(storage, "cook dinner", _FUTURE_15, _CONFIG)
    entry = storage.read_json("reminders.json")[0]
    assert "id" in entry and len(entry["id"]) > 0
    assert "created_at" in entry and len(entry["created_at"]) > 0


def test_set_reminder_append_does_not_clobber_existing(storage):
    set_reminder(storage, "first task", _FUTURE_15, _CONFIG)
    set_reminder(storage, "second task", "2099-01-01T21:15:00Z", _CONFIG)
    reminders = storage.read_json("reminders.json")
    assert len(reminders) == 2
    assert reminders[0]["message"] == "first task"  # original not clobbered
    assert reminders[1]["message"] == "second task"


from processors.reminders import fire_due_reminders


def _make_entry(message: str, fire_at: datetime, fired: bool = False) -> dict:
    return {
        "id": "test-id",
        "message": message,
        "fire_at": fire_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_at": "2026-05-05T18:00:00Z",
        "fired": fired,
    }


def test_fire_due_reminders_sends_due_reminder(storage):
    fire_at = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    storage.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    mock_send.assert_called_once()
    text = mock_send.call_args[0][2]
    assert "email Ted" in text
    assert "⏰" in text
    assert storage.read_json("reminders.json")[0]["fired"] is True


def test_fire_due_reminders_skips_future_reminder(storage):
    fire_at = datetime(2099, 1, 1, 21, 0, 0, tzinfo=timezone.utc)
    storage.write_json("reminders.json", [_make_entry("future task", fire_at)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    mock_send.assert_not_called()
    assert storage.read_json("reminders.json")[0]["fired"] is False


def test_fire_due_reminders_skips_already_fired(storage):
    fire_at = datetime(2026, 5, 5, 21, 0, 0, tzinfo=timezone.utc)
    storage.write_json("reminders.json", [_make_entry("email Ted", fire_at, fired=True)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    mock_send.assert_not_called()


def test_fire_due_reminders_adds_late_note_when_delayed(storage):
    fire_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    fire_at = fire_at.replace(second=0, microsecond=0)
    storage.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    text = mock_send.call_args[0][2]
    assert "delayed run" in text


def test_fire_due_reminders_no_late_note_when_on_time(storage):
    fire_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    fire_at = fire_at.replace(second=0, microsecond=0)
    storage.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message") as mock_send:
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    text = mock_send.call_args[0][2]
    assert "delayed run" not in text


def test_fire_due_reminders_appends_to_history(storage):
    fire_at = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    storage.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message"):
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    import json as _json
    raw = storage.read("reminder_history.jsonl")
    assert raw is not None
    lines = [line for line in raw.strip().splitlines() if line]
    entry = _json.loads(lines[0])
    assert entry["message"] == "email Ted"
    assert "fired_at" in entry


def test_fire_due_reminders_prunes_old_fired_entries(storage):
    old_fire_at = datetime.now(timezone.utc) - timedelta(days=8)
    old_fire_at = old_fire_at.replace(second=0, microsecond=0)
    storage.write_json("reminders.json", [_make_entry("old task", old_fire_at, fired=True)])

    with patch("processors.reminders.send_message"):
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    assert storage.read_json("reminders.json") == []


def test_fire_due_reminders_keeps_recent_fired_entries(storage):
    recent_fire_at = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_fire_at = recent_fire_at.replace(second=0, microsecond=0)
    storage.write_json("reminders.json", [_make_entry("recent task", recent_fire_at, fired=True)])

    with patch("processors.reminders.send_message"):
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    assert len(storage.read_json("reminders.json")) == 1


def test_fire_due_reminders_retries_on_send_failure(storage):
    fire_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    fire_at = fire_at.replace(second=0, microsecond=0)
    storage.write_json("reminders.json", [_make_entry("email Ted", fire_at)])

    with patch("processors.reminders.send_message", side_effect=Exception("network error")):
        fire_due_reminders(storage, "tok", "chat", "America/Chicago")

    updated = storage.read_json("reminders.json")
    assert len(updated) == 1
    assert updated[0]["fired"] is False


def test_fire_due_reminders_drops_expired_unsent_reminder(storage):
    fire_at = datetime.now(timezone.utc) - timedelta(hours=25)
    fire_at = fire_at.replace(second=0, microsecond=0)
    storage.write_json("reminders.json", [_make_entry("stale task", fire_at)])

    with patch("processors.reminders.send_message", side_effect=Exception("fail")):
        fire_due_reminders(storage, "tok", "chat", "America/Chicago", max_age_hours=24)

    assert storage.read_json("reminders.json") == []
