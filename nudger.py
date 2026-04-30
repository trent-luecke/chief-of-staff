#!/usr/bin/env python3
"""Post-meeting nudger: sends a Telegram message after work meetings end."""

import os
import json
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from collectors.calendar import CalendarEvent, fetch_two_day_events
from lib.telegram import send_message


PERSONAL_KEYWORDS = {
    "haircut", "doctor", "dentist", "gym", "workout", "therapy",
    "appointment", "physical", "checkup", "check-up", "optometrist",
    "chiropractor", "massage", "pto", "ooo", "out of office",
    "blocked", "focus time", "deep work", "no meetings",
    "birthday", "anniversary", "vacation", "lunch", "dinner",
}

MEETING_KEYWORDS = {
    "call", "sync", "meeting", "1:1", "one-on-one", "standup", "stand-up",
    "demo", "interview", "review", "check-in", "checkin", "huddle",
    "connect", "catchup", "catch-up", "kickoff", "kick-off", "debrief",
    "session", "discussion", "chat", "workshop", "training", "onboarding",
    "presentation", "pitch", "walkthrough", "intro", "follow-up",
}


def is_work_meeting(event: CalendarEvent) -> bool:
    title = event.summary.lower()
    if any(kw in title for kw in PERSONAL_KEYWORDS):
        return False
    # Other attendees on the invite is the strongest signal
    if event.attendees:
        return True
    # No attendees — require an explicit meeting keyword
    return any(kw in title for kw in MEETING_KEYWORDS)


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_pending_nudges(path: str) -> list[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_pending_nudges(nudges: list[dict], path: str) -> None:
    with open(path, "w") as f:
        json.dump(nudges, f, indent=2)


def run() -> None:
    config = load_config()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")
    nudge_delay = config.get("nudge_minutes_after", 5)
    pending_file = config["pending_nudges_file"]
    pending = load_pending_nudges(pending_file)
    already_nudged = {n["event_id"] for n in pending}

    today_events, _, _ = fetch_two_day_events(config["calendar_ids"])
    now = datetime.now().astimezone()

    for event in today_events:
        if event.id in already_nudged:
            continue
        if not is_work_meeting(event):
            continue
        nudge_time = event.end + timedelta(minutes=nudge_delay)
        if now < nudge_time:
            continue

        if bot_token and chat_id:
            text = f"📝 {event.summary} just wrapped. Drop your notes — what was covered, open items, action items."
            send_message(bot_token, chat_id, text)
            print(f"  Nudge sent for: {event.summary}")
        else:
            print(f"  WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_CHAT_ID not set — skipping nudge for {event.summary}")

        pending.append({
            "event_id": event.id,
            "meeting_name": event.summary,
            "sent_at": now.isoformat(),
            "session_date": date.today().isoformat(),
        })

    save_pending_nudges(pending, pending_file)
    print("✅ Nudger run complete.")


if __name__ == "__main__":
    run()
