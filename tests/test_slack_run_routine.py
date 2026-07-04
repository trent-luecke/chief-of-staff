import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.slack_run_routine import (
    match_routines, format_routine_list, format_run_confirmation,
)


def _r(name, rid=None, steps=1, trigger=None):
    return {"id": rid or name.lower().replace(" ", "-"), "name": name,
            "steps": [{"title": f"s{i}"} for i in range(steps)],
            "trigger": trigger, "runs": []}


def test_match_exact_and_substring():
    routines = [_r("Out of Office Prep"), _r("Weekly Review")]
    assert [m["name"] for m in match_routines("out of office prep", routines)] == ["Out of Office Prep"]
    assert [m["name"] for m in match_routines("weekly", routines)] == ["Weekly Review"]
    assert [m["name"] for m in match_routines("ooo-prep", routines)] == []  # id substring only when query matches id
    assert [m["name"] for m in match_routines("out-of-office-prep", routines)] == ["Out of Office Prep"]


def test_match_multiple_and_none():
    routines = [_r("OOO Prep"), _r("OOO Wrap-up")]
    assert len(match_routines("ooo", routines)) == 2
    assert match_routines("zzz", routines) == []


def test_format_routine_list():
    routines = [_r("OOO Prep", steps=3, trigger={"type": "calendar_ooo", "lead_days": 7}),
                _r("Weekly Review", steps=1)]
    out = format_routine_list(routines)
    assert "OOO Prep (3 steps · auto-OOO)" in out
    assert "Weekly Review (1 step)" in out
    assert "`/routine OOO Prep`" in out


def test_format_routine_list_empty():
    assert "No routines defined yet" in format_routine_list([])


def test_format_run_confirmation():
    routine = _r("OOO Prep")
    tasks = [{"title": "Cancel meetings"}, {"title": "Set responder"}]
    out = format_run_confirmation(routine, tasks)
    assert out.startswith("Ran 'OOO Prep' — created 2 tasks:")
    assert "• Cancel meetings" in out and "• Set responder" in out


def test_format_run_confirmation_with_note():
    out = format_run_confirmation(_r("R"), [{"title": "a"}], note="_Note: last ran 2026-07-01._")
    assert out.endswith("_Note: last ran 2026-07-01._")
    assert "created 1 task:" in out


def test_match_exact_name_beats_superstring_sibling():
    routines = [_r("OOO Prep"), _r("OOO Prep v2")]
    assert [m["name"] for m in match_routines("ooo prep", routines)] == ["OOO Prep"]
    assert len(match_routines("ooo", routines)) == 2  # non-exact still fans out


def test_detect_trigger_key_skips_already_keyed_window(monkeypatch):
    from datetime import date, timedelta
    import scripts.slack_run_routine as srr
    from lib.ooo import OooWindow

    near = OooWindow(event_id="w1", summary="OOO", start=date.today() + timedelta(days=2), end=date.today() + timedelta(days=3))
    far = OooWindow(event_id="w2", summary="OOO", start=date.today() + timedelta(days=6), end=date.today() + timedelta(days=7))

    import lib.ooo as ooo_mod
    import lib.google_auth as ga
    monkeypatch.setattr(ga, "build_calendar_service", lambda: object())
    monkeypatch.setattr(ooo_mod, "detect_ooo_windows", lambda service, lead, today=None: [near, far])

    routine = {"id": "r", "name": "R", "steps": [{"title": "a"}],
               "trigger": {"type": "calendar_ooo", "lead_days": 7},
               "runs": [{"date": "2026-01-01", "trigger_key": "gcal:w1", "source": "slack"}]}
    assert srr.detect_trigger_key(routine) == "gcal:w2"

    routine["runs"] = []
    assert srr.detect_trigger_key(routine) == "gcal:w1"
