# lib/ooo.py
"""Google Calendar out-of-office detection for routine triggers.

Owns the OOO query (independent of collectors/calendar.py, which drops
eventType) and the brief's suggestion lines. All functions take the calendar
service as an argument — callers build it via lib.google_auth.

Detection matches native `eventType: outOfOffice` events or titles containing
"OOO"/"out of office" (word-boundary match) — one-off events only; recurring
instances (identified by `recurringEventId`) are skipped since weekly/monthly
OOO blocks are schedule structure, not trips.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

_OOO_TITLE_RE = re.compile(r"\bOOO\b|out of office", re.IGNORECASE)


@dataclass
class OooWindow:
    event_id: str
    summary: str
    start: date
    end: date  # inclusive last day


def trigger_key(window: OooWindow) -> str:
    return f"gcal:{window.event_id}"


def _parse_day(value: dict, end: bool = False) -> Optional[date]:
    """Parse a Google event start/end. All-day events use {'date': 'YYYY-MM-DD'}
    with an EXCLUSIVE end; timed events use {'dateTime': ISO} where a midnight
    end also means "through the previous day"."""
    if "date" in value:
        d = date.fromisoformat(value["date"])
        return d - timedelta(days=1) if end else d
    if "dateTime" in value:
        dt = datetime.fromisoformat(value["dateTime"])
        d = dt.date()
        if end and dt.time() == time(0, 0):
            d -= timedelta(days=1)
        return d
    return None


def detect_ooo_windows(service, lead_days: int, today: Optional[date] = None) -> list:
    """OOO windows on the primary calendar within [today, today + lead_days]."""
    today = today or date.today()
    time_min = datetime.combine(today, datetime.min.time()).astimezone().isoformat()
    time_max = datetime.combine(
        today + timedelta(days=lead_days + 1), datetime.min.time()
    ).astimezone().isoformat()
    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    windows = []
    for item in result.get("items", []):
        summary = item.get("summary", "")
        if item.get("recurringEventId"):
            continue  # weekly OOO blocks etc. are schedule structure, not trips
        if item.get("eventType") != "outOfOffice" and not _OOO_TITLE_RE.search(summary):
            continue
        start = _parse_day(item.get("start", {}))
        if start is None:
            continue
        end = _parse_day(item.get("end", {}), end=True) or start
        windows.append(OooWindow(
            event_id=item["id"],
            summary=summary or "Out of office",
            start=start,
            end=max(end, start),
        ))
    return windows


def _span(w: OooWindow) -> str:
    if w.end == w.start:
        return w.start.strftime("%b %-d")
    return f"{w.start.strftime('%b %-d')}–{w.end.strftime('%b %-d')}"


def routine_suggestions(service, routines: list, today: Optional[date] = None) -> list:
    """Brief suggestion lines for calendar-triggered routines.

    A window is suggested while it hasn't started (today < start) and the
    routine has no run keyed to it. Recomputed from scratch each call — no
    suggestion state is stored anywhere.
    """
    today = today or date.today()
    lines = []
    windows_by_lead: dict = {}
    for r in routines:
        trig = r.get("trigger") or {}
        if trig.get("type") != "calendar_ooo":
            continue
        lead = int(trig.get("lead_days", 7))
        if lead not in windows_by_lead:
            windows_by_lead[lead] = detect_ooo_windows(service, lead, today=today)
        run_keys = {run.get("trigger_key") for run in (r.get("runs") or [])}
        for w in windows_by_lead[lead]:
            if w.start <= today:
                continue
            if trigger_key(w) in run_keys:
                continue
            lines.append(
                f"OOO detected {_span(w)} — activate '{r['name']}': "
                f"type `/routine {r['name']}` in Slack."
            )
    return lines
