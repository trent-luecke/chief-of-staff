from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from dateutil.parser import parse as parse_dt

from lib.google_auth import build_calendar_service


@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    description: str = ""
    attendees: list[str] = field(default_factory=list)
    attendee_details: list[dict] = field(default_factory=list)
    declined: bool = False


def _build_service(user_email: str):
    return build_calendar_service(user_email)


def fetch_today_events(
    calendar_id: str = "primary",
    target_date: Optional[date] = None,
    user_email: str = "",
    _return_error: bool = False,
) -> list[CalendarEvent]:
    if target_date is None:
        target_date = date.today()
    time_min = datetime.combine(target_date, datetime.min.time()).astimezone().isoformat()
    time_max = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).astimezone().isoformat()

    try:
        service = _build_service(user_email)
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except Exception as e:
        print(f"WARNING: Calendar fetch failed: {e}", flush=True)
        if _return_error:
            return e
        return []

    events = []
    for item in result.get("items", []):
        start_raw = item.get("start", {})
        if "date" in start_raw and "dateTime" not in start_raw:
            continue
        try:
            raw_attendees = item.get("attendees", [])
            self_entry = next((a for a in raw_attendees if a.get("self")), None)
            owner_declined = (
                self_entry is not None
                and self_entry.get("responseStatus") == "declined"
            )
            events.append(
                CalendarEvent(
                    id=item["id"],
                    summary=item.get("summary", "(no title)"),
                    start=parse_dt(start_raw["dateTime"]),
                    end=parse_dt(item["end"]["dateTime"]),
                    description=item.get("description", ""),
                    attendees=[
                        a["email"] for a in raw_attendees if not a.get("self")
                    ],
                    attendee_details=[
                        {"email": a["email"], "name": a.get("displayName", "")}
                        for a in raw_attendees if not a.get("self")
                    ],
                    declined=owner_declined,
                )
            )
        except (KeyError, ValueError):
            continue
    return events


def fetch_two_day_events(
    calendar_ids: list[str],
    user_email: str = "",
) -> tuple[list[CalendarEvent], list[CalendarEvent], bool]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_events, tomorrow_events = [], []
    calendar_failed = False
    for cal_id in calendar_ids:
        result = fetch_today_events(cal_id, today, user_email, _return_error=True)
        if isinstance(result, Exception):
            calendar_failed = True
        else:
            today_events.extend(result)
        result = fetch_today_events(cal_id, tomorrow, user_email, _return_error=True)
        if not isinstance(result, Exception):
            tomorrow_events.extend(result)
    today_events.sort(key=lambda e: e.start)
    tomorrow_events.sort(key=lambda e: e.start)
    return today_events, tomorrow_events, calendar_failed


def fetch_date_range_events(
    calendar_ids: list[str],
    start_date: date,
    end_date: date,
    user_email: str = "",
) -> list[CalendarEvent]:
    seen: set[str] = set()
    events: list[CalendarEvent] = []
    current = start_date
    while current < end_date:
        for cal_id in calendar_ids:
            result = fetch_today_events(cal_id, current, user_email, _return_error=True)
            if isinstance(result, Exception):
                print(f"WARNING: calendar fetch failed for {cal_id} on {current}: {result}", flush=True)
                continue
            for evt in result:
                if evt.id not in seen:
                    seen.add(evt.id)
                    events.append(evt)
        current += timedelta(days=1)
    events.sort(key=lambda e: e.start)
    return events
