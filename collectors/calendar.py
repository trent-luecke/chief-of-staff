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


def _build_service(user_email: str):
    return build_calendar_service(user_email)


def fetch_today_events(
    calendar_id: str = "primary",
    target_date: Optional[date] = None,
    user_email: str = "",
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
        return []

    events = []
    for item in result.get("items", []):
        start_raw = item.get("start", {})
        if "date" in start_raw and "dateTime" not in start_raw:
            continue
        try:
            events.append(
                CalendarEvent(
                    id=item["id"],
                    summary=item.get("summary", "(no title)"),
                    start=parse_dt(start_raw["dateTime"]),
                    end=parse_dt(item["end"]["dateTime"]),
                    description=item.get("description", ""),
                    attendees=[
                        a["email"] for a in item.get("attendees", []) if not a.get("self")
                    ],
                )
            )
        except (KeyError, ValueError):
            continue
    return events


def fetch_two_day_events(
    calendar_ids: list[str],
    user_email: str = "",
) -> tuple[list[CalendarEvent], list[CalendarEvent]]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_events, tomorrow_events = [], []
    for cal_id in calendar_ids:
        today_events.extend(fetch_today_events(cal_id, today, user_email))
        tomorrow_events.extend(fetch_today_events(cal_id, tomorrow, user_email))
    today_events.sort(key=lambda e: e.start)
    tomorrow_events.sort(key=lambda e: e.start)
    return today_events, tomorrow_events
