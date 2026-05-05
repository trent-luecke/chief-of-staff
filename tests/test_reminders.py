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
