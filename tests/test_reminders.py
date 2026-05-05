import json
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from lib.storage import LocalStorage
from processors.reminders import set_reminder


def _storage():
    tmp = tempfile.mkdtemp()
    return LocalStorage(tmp)


_CONFIG = {"timezone": "America/Chicago"}

# A known UTC datetime on a 15-min boundary, well in the future
_FUTURE_15 = "2099-01-01T21:00:00Z"
# Same time but NOT on a boundary
_FUTURE_OFF = "2099-01-01T21:07:00Z"
# Clearly in the past
_PAST = "2020-01-01T00:00:00Z"


def test_set_reminder_valid_stores_entry():
    s = _storage()
    result = set_reminder(s, "cook dinner", _FUTURE_15, _CONFIG)
    assert "cook dinner" in result
    assert "reminder set" in result.lower() or "9:00" in result
    reminders = s.read_json("reminders.json")
    assert len(reminders) == 1
    assert reminders[0]["message"] == "cook dinner"
    assert reminders[0]["fired"] is False
    assert reminders[0]["fire_at"] == "2099-01-01T21:00:00Z"


def test_set_reminder_rejects_non_aligned_minute():
    s = _storage()
    result = set_reminder(s, "cook dinner", _FUTURE_OFF, _CONFIG)
    assert "boundary" in result.lower() or ":07" in result
    assert s.read_json("reminders.json") is None  # nothing written


def test_set_reminder_rejects_past_time():
    s = _storage()
    result = set_reminder(s, "cook dinner", _PAST, _CONFIG)
    assert "past" in result.lower()
    assert s.read_json("reminders.json") is None


def test_set_reminder_rejects_unparseable_time():
    s = _storage()
    result = set_reminder(s, "cook dinner", "not-a-date", _CONFIG)
    assert "parse" in result.lower() or "couldn't" in result.lower()
    assert s.read_json("reminders.json") is None


def test_set_reminder_multiple_entries_appended():
    s = _storage()
    set_reminder(s, "first task", _FUTURE_15, _CONFIG)
    set_reminder(s, "second task", "2099-01-01T21:15:00Z", _CONFIG)
    reminders = s.read_json("reminders.json")
    assert len(reminders) == 2
    assert reminders[1]["message"] == "second task"
