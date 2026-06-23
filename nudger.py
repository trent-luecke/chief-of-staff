#!/usr/bin/env python3
"""Pre-meeting prep runner: sends pre-meeting briefs to Slack before work meetings."""

import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from collectors.calendar import fetch_two_day_events
from lib.notify import notify_user


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def run() -> None:
    config = load_config()
    from lib.storage import build_storage
    storage = build_storage(config)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

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
        if prep_enabled and api_key:
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
                            notify_user(message, config)
                            sent_preps.add(prep_key)
                            print(f"  Prep sent for: {event.summary} ({meeting_type})")
                        except Exception as e:
                            print(f"  WARNING: Prep failed for {event.summary}: {e}")

    if prep_enabled:
        save_prep_state(sent_preps, storage)
    print("✅ Nudger run complete.")


if __name__ == "__main__":
    run()
