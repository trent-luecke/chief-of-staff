# tests/test_ooo.py
from datetime import date
from unittest.mock import MagicMock

from lib.ooo import OooWindow, detect_ooo_windows, routine_suggestions, trigger_key

TODAY = date(2026, 8, 3)


def _svc(items):
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {"items": items}
    return service


def _ooo_event(eid="evt1", summary="Out of office", start="2026-08-10", end="2026-08-15",
               event_type="outOfOffice", all_day=True):
    key = "date" if all_day else "dateTime"
    ev = {"id": eid, "summary": summary,
          "start": {key: start}, "end": {key: end}}
    if event_type:
        ev["eventType"] = event_type
    return ev


# --- detect_ooo_windows ---

def test_detects_native_ooo_event():
    # all-day event 8/10–8/15 exclusive end → inclusive 8/10–8/14
    windows = detect_ooo_windows(_svc([_ooo_event()]), lead_days=7, today=TODAY)
    assert len(windows) == 1
    w = windows[0]
    assert (w.event_id, w.start, w.end) == ("evt1", date(2026, 8, 10), date(2026, 8, 14))
    assert trigger_key(w) == "gcal:evt1"


def test_detects_title_fallback_regular_event():
    ev = _ooo_event(eid="evt2", summary="OOO - Hawaii", event_type="default")
    assert len(detect_ooo_windows(_svc([ev]), 7, today=TODAY)) == 1
    ev2 = _ooo_event(eid="evt3", summary="Heading out of office Friday", event_type=None)
    assert len(detect_ooo_windows(_svc([ev2]), 7, today=TODAY)) == 1


def test_ignores_unrelated_events():
    ev = _ooo_event(eid="evt4", summary="Demo: Apex Fitness", event_type="default")
    assert detect_ooo_windows(_svc([ev]), 7, today=TODAY) == []


def test_title_word_boundary():
    ev = _ooo_event(eid="evt5", summary="Vroom party", event_type="default")
    assert detect_ooo_windows(_svc([ev]), 7, today=TODAY) == []


def test_datetime_event_midnight_end_is_previous_day():
    ev = _ooo_event(eid="evt6", start="2026-08-10T00:00:00-05:00",
                    end="2026-08-15T00:00:00-05:00", all_day=False)
    w = detect_ooo_windows(_svc([ev]), 14, today=TODAY)[0]
    assert (w.start, w.end) == (date(2026, 8, 10), date(2026, 8, 14))


def test_datetime_event_midday_end_is_same_day():
    ev = _ooo_event(eid="evt7", start="2026-08-10T09:00:00-05:00",
                    end="2026-08-10T17:00:00-05:00", all_day=False)
    w = detect_ooo_windows(_svc([ev]), 14, today=TODAY)[0]
    assert (w.start, w.end) == (date(2026, 8, 10), date(2026, 8, 10))


def test_query_window_uses_lead_days():
    svc = _svc([])
    detect_ooo_windows(svc, lead_days=5, today=TODAY)
    kwargs = svc.events.return_value.list.call_args.kwargs
    assert kwargs["calendarId"] == "primary"
    assert kwargs["singleEvents"] is True
    assert "2026-08-03" in kwargs["timeMin"]
    assert "2026-08-09" in kwargs["timeMax"]  # today + lead_days + 1


# --- routine_suggestions ---

def _routine(name="Out of Office Prep", lead=7, runs=None, trigger=True):
    return {
        "id": "ooo-prep", "name": name,
        "steps": [{"title": "a"}],
        "trigger": {"type": "calendar_ooo", "lead_days": lead} if trigger else None,
        "runs": runs or [],
    }


def test_suggests_upcoming_unrun_window():
    lines = routine_suggestions(_svc([_ooo_event()]), [_routine()], today=TODAY)
    assert len(lines) == 1
    assert "Aug 10" in lines[0] and "Aug 14" in lines[0]
    assert "Out of Office Prep" in lines[0]
    assert "/routine Out of Office Prep" in lines[0]


def test_quiet_once_window_started():
    started = _ooo_event(start="2026-08-03", end="2026-08-05")  # starts today
    assert routine_suggestions(_svc([started]), [_routine()], today=TODAY) == []


def test_quiet_after_keyed_run():
    runs = [{"date": "2026-08-01", "trigger_key": "gcal:evt1", "source": "slack"}]
    assert routine_suggestions(_svc([_ooo_event()]), [_routine(runs=runs)], today=TODAY) == []


def test_unkeyed_run_does_not_suppress():
    runs = [{"date": "2026-08-01", "trigger_key": None, "source": "ui"}]
    assert len(routine_suggestions(_svc([_ooo_event()]), [_routine(runs=runs)], today=TODAY)) == 1


def test_untriggered_routines_ignored_and_no_calendar_call():
    svc = _svc([_ooo_event()])
    assert routine_suggestions(svc, [_routine(trigger=False)], today=TODAY) == []
    svc.events.return_value.list.assert_not_called()


def test_single_day_window_format():
    ev = _ooo_event(start="2026-08-10", end="2026-08-11")  # all-day exclusive end → 8/10 only
    lines = routine_suggestions(_svc([ev]), [_routine()], today=TODAY)
    assert "Aug 10 —" in lines[0] and "Aug 10–" not in lines[0]
