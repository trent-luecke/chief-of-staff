import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.slack_add_task import format_confirmation, parse_due_date


def test_parse_due_date_empty_returns_none():
    assert parse_due_date("") is None


def test_parse_due_date_whitespace_returns_none():
    assert parse_due_date("   ") is None


def test_parse_due_date_garbage_returns_none():
    assert parse_due_date("zzzzgarbage12345") is None


def test_parse_due_date_iso_passthrough():
    assert parse_due_date("2026-12-31") == "2026-12-31"


def test_parse_due_date_natural_language_returns_iso():
    result = parse_due_date("next monday")
    assert result is not None
    assert re.match(r"\d{4}-\d{2}-\d{2}", result)


def test_format_confirmation_no_date():
    assert format_confirmation("Follow up with Acme", None) == "Task added: Follow up with Acme"


def test_format_confirmation_with_date():
    result = format_confirmation("Follow up with Acme", "2026-06-06")
    assert result == "Task added: Follow up with Acme — due 2026-06-06"


def test_format_confirmation_with_horizon():
    result = format_confirmation("Renew SSL", None, horizon="2026-09-01")
    assert result == "Task added: Renew SSL — on horizon until 2026-09-01"


def test_format_confirmation_due_and_horizon():
    result = format_confirmation("Renew SSL", "2026-09-15", horizon="2026-09-01")
    assert result == "Task added: Renew SSL — due 2026-09-15 — on horizon until 2026-09-01"


def test_horizon_conflict_message():
    from scripts.slack_add_task import horizon_conflict_message
    assert horizon_conflict_message("2026-09-15", "2026-09-01") is not None
    assert "2026-09-15" in horizon_conflict_message("2026-09-15", "2026-09-01")
    assert horizon_conflict_message("2026-09-01", "2026-09-15") is None  # horizon before due: fine
    assert horizon_conflict_message(None, "2026-09-01") is None
    assert horizon_conflict_message("2026-09-01", None) is None
