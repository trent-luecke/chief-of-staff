#!/usr/bin/env python3
"""Post-meeting nudger: sends a reply-able email after each tracked internal meeting ends."""

import json
import os
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from collectors.calendar import fetch_two_day_events
from processors.meeting_memory import load_meeting_index, find_meeting_for_event
from outputs.sender import build_gmail_service_from_config, send_brief_email


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
    meeting_configs = load_meeting_index(config["meeting_index_file"])
    pending_file = config["pending_nudges_file"]
    pending = load_pending_nudges(pending_file)
    already_nudged = {n["event_id"] for n in pending}

    today_events, _ = fetch_two_day_events(
        config["calendar_ids"], profile=config.get("gmail_profile")
    )
    now = datetime.now()
    gmail = build_gmail_service_from_config(config["credentials_path"], config["token_path"])

    for event in today_events:
        if event.id in already_nudged:
            continue
        meeting_config = find_meeting_for_event(event, meeting_configs)
        if not meeting_config:
            continue
        nudge_time = event.end + timedelta(minutes=meeting_config.nudge_minutes_after)
        if now < nudge_time:
            continue

        body = (
            f"<p>Your <strong>{event.summary}</strong> just wrapped.</p>"
            f"<p>Reply to this email with your notes — what was covered, open items, "
            f"and any action items. I'll add them to the meeting log automatically.</p>"
        )
        msg_id = send_brief_email(
            gmail_service=gmail,
            to_email=config["email"],
            subject=meeting_config.nudge_subject,
            html_body=body,
        )
        pending.append({
            "event_id": event.id,
            "meeting_name": event.summary,
            "memory_file": meeting_config.memory_file,
            "thread_id": msg_id,
            "sent_at": now.isoformat(),
            "session_date": date.today().isoformat(),
        })
        print(f"  Nudge sent for: {event.summary}")

    save_pending_nudges(pending, pending_file)
    print("✅ Nudger run complete.")


if __name__ == "__main__":
    run()
