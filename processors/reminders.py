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
        return dt.strftime("%H:%M UTC")


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
            f"Got :{fire_at.minute:02d} — nearest valid: :{(fire_at.minute // 15) * 15:02d}."
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


def fire_due_reminders(
    storage,
    bot_token: str,
    chat_id: str,
    timezone_name: str = "America/Chicago",
    max_age_hours: int = 24,
) -> None:
    """Check for due reminders, send them via Telegram, and update state."""
    now = datetime.now(timezone.utc)
    reminders = storage.read_json(_REMINDERS_KEY, default=[])
    updated = []

    for entry in reminders:
        try:
            fire_at = datetime.fromisoformat(entry["fire_at"].replace("Z", "+00:00"))
            if fire_at.tzinfo is None:
                fire_at = fire_at.replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            updated.append(entry)
            continue

        # Already fired — keep if recent, prune if > 7 days old
        if entry.get("fired"):
            if (now - fire_at).total_seconds() < 7 * 86400:
                updated.append(entry)
            continue

        # Not yet due
        if fire_at > now:
            updated.append(entry)
            continue

        # Due — build message text
        delay = now - fire_at
        message = entry.get("message", "")
        scheduled_str = _format_local_time(fire_at, timezone_name)
        fired_str = _format_local_time(now, timezone_name)

        if delay.total_seconds() > 20 * 60:
            text = (
                f"⏰ Reminder: {message}\n"
                f"(scheduled for {scheduled_str} — fired at {fired_str} due to a delayed run)"
            )
        else:
            text = f"⏰ Reminder: {message}"

        try:
            send_message(bot_token, chat_id, text)
            entry["fired"] = True
            fired_entry = {**entry, "fired_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
            storage.append_line(_HISTORY_KEY, json.dumps(fired_entry))
            updated.append(entry)
        except Exception as e:
            print(f"WARNING: Failed to send reminder '{message}': {e}")
            if delay.total_seconds() > max_age_hours * 3600:
                print(f"WARNING: Reminder '{message}' expired after {max_age_hours}h — dropping.")
            else:
                entry["fired"] = False
                updated.append(entry)

    storage.write_json(_REMINDERS_KEY, updated)
