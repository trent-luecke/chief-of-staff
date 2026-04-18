import json
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from dateutil.parser import parse as parse_dt


@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    description: str = ""
    attendees: list[str] = field(default_factory=list)


def fetch_today_events(
    calendar_id: str = "primary",
    target_date: Optional[date] = None,
    profile: Optional[str] = None,
) -> list[CalendarEvent]:
    if target_date is None:
        target_date = date.today()
    time_min = datetime.combine(target_date, datetime.min.time()).isoformat() + "Z"
    time_max = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).isoformat() + "Z"

    params = {
        "calendarId": calendar_id,
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    cmd = ["gws", "calendar", "events", "list", "--params", json.dumps(params)]
    if profile:
        cmd = ["gws", "--profile", profile] + cmd[1:]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("WARNING: gws not found in PATH — calendar fetch skipped.", flush=True)
        return []
    if result.returncode != 0:
        print(f"WARNING: gws calendar command failed (exit {result.returncode}): {result.stderr.strip()}", flush=True)
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    events = []
    for item in data.get("items", []):
        start_raw = item.get("start", {})
        if "date" in start_raw and "dateTime" not in start_raw:
            continue  # skip all-day events
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
    profile: Optional[str] = None,
) -> tuple[list[CalendarEvent], list[CalendarEvent]]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_events, tomorrow_events = [], []
    for cal_id in calendar_ids:
        today_events.extend(fetch_today_events(cal_id, today, profile))
        tomorrow_events.extend(fetch_today_events(cal_id, tomorrow, profile))
    today_events.sort(key=lambda e: e.start)
    tomorrow_events.sort(key=lambda e: e.start)
    return today_events, tomorrow_events
