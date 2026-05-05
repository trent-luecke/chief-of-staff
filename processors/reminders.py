"""Reminder queue: set and fire timed Telegram reminders."""

import json
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from lib.telegram import send_message


_REMINDERS_KEY = "reminders.json"
_HISTORY_KEY = "reminder_history.jsonl"


def _format_local_time(dt: datetime, tz_name: str) -> str:
    """Format a UTC datetime as a human-readable local time string."""
    try:
        local = dt.astimezone(ZoneInfo(tz_name))
        hour = int(local.strftime("%I"))
        return f"{hour}:{local.strftime('%M %p %Z')}"
    except Exception:
        return dt.strftime("%H:%MZ")


def set_reminder(storage, message: str, fire_at_iso: str, config: dict = None) -> str:
    """Validate and persist a reminder. Returns a user-facing confirmation or error string."""
    config = config or {}
    tz_name = config.get("timezone", "America/Chicago")

    # Parse fire_at
    try:
        fire_at = datetime.fromisoformat(fire_at_iso.replace("Z", "+00:00"))
        if fire_at.tzinfo is None:
            fire_at = fire_at.replace(tzinfo=timezone.utc)
        fire_at = fire_at.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return f"Couldn't parse '{fire_at_iso}' as a datetime — please try again."

    # Reject past times
    now = datetime.now(timezone.utc)
    if fire_at <= now:
        return "That time is already in the past — please set a future time."

    # Validate 15-minute alignment
    if fire_at.minute % 15 != 0 or fire_at.second != 0:
        return (
            f"Fire time must be on a 15-minute boundary (:00, :15, :30, :45). "
            f"Got :{fire_at.minute:02d} — pick :{(fire_at.minute // 15) * 15:02d} "
            f"or :{min((fire_at.minute // 15 + 1) * 15, 59):02d}."
        )

    display_time = _format_local_time(fire_at, tz_name)

    entry = {
        "id": str(uuid.uuid4()),
        "message": message,
        "fire_at": fire_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fired": False,
    }
    reminders = storage.read_json(_REMINDERS_KEY, default=[])
    reminders.append(entry)
    storage.write_json(_REMINDERS_KEY, reminders)

    return f"Reminder set for {display_time}: {message}"
