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


_NUDGES_KEY = "pending_nudges.json"


def load_pending_nudges(storage) -> list[dict]:
    return storage.read_json(_NUDGES_KEY, default=[])


def save_pending_nudges(nudges: list[dict], storage) -> None:
    storage.write_json(_NUDGES_KEY, nudges)


def run() -> None:
    config = load_config()
    from lib.storage import build_storage
    storage = build_storage(config)
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    nudge_delay = config.get("nudge_minutes_after", 5)
    pending = load_pending_nudges(storage)
    already_nudged = {n["event_id"] for n in pending}

    prep_config = config.get("meeting_prep", {})
    prep_enabled = prep_config.get("enabled", False)
    prep_window = prep_config.get("prep_window_minutes", 20)

    today_events, _, _ = fetch_two_day_events(config["calendar_ids"])
    now = datetime.now().astimezone()

    from processors.meeting_prep import (
        classify_meeting, build_prep_message,
        load_prep_state, save_prep_state, make_prep_key,
    )
    sent_preps = load_prep_state(storage) if prep_enabled else set()

    for event in today_events:
        # ── Pre-meeting prep ────────────────────────────────────────────
        if prep_enabled and api_key and bot_token and chat_id:
            prep_key = make_prep_key(event)
            if prep_key not in sent_preps:
                meeting_type = classify_meeting(event, config)
                if meeting_type:
                    prep_start = event.start - timedelta(minutes=prep_window)
                    if prep_start <= now <= event.start:
                        try:
                            message = build_prep_message(event, meeting_type, config, api_key)
                            if message is None:
                                print(f"  Prep suppressed (no context): {event.summary}")
                                continue
                            send_message(bot_token, chat_id, message)
                            sent_preps.add(prep_key)
                            print(f"  Prep sent for: {event.summary} ({meeting_type})")
                        except Exception as e:
                            print(f"  WARNING: Prep failed for {event.summary}: {e}")

        # ── Post-meeting nudge ───────────────────────────────────────────
        if event.id in already_nudged:
            continue
        if not is_work_meeting(event):
            continue
        nudge_time = event.end + timedelta(minutes=nudge_delay)
        if now < nudge_time:
            continue

        nudge_message_id = None
        if bot_token and chat_id:
            text = f"📝 {event.summary} just wrapped. Drop your notes — what was covered, open items, action items."
            nudge_message_id = send_message(bot_token, chat_id, text)
            print(f"  Nudge sent for: {event.summary}")
        else:
            print(f"  WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_CHAT_ID not set — skipping nudge for {event.summary}")

        entry = {
            "event_id": event.id,
            "meeting_name": event.summary,
            "sent_at": now.isoformat(),
            "session_date": date.today().isoformat(),
            "attendees": event.attendees,
        }
        if nudge_message_id:
            entry["telegram_message_id"] = nudge_message_id
        pending.append(entry)

    save_pending_nudges(pending, storage)
    if prep_enabled:
        save_prep_state(sent_preps, storage)
    print("✅ Nudger run complete.")


if __name__ == "__main__":
    run()
