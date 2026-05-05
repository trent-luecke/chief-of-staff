#!/usr/bin/env python3
"""Check for due reminders and send them via Telegram. Called by reminders.yml."""

import json
import os
from dotenv import load_dotenv

load_dotenv()

from processors.reminders import fire_due_reminders


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def main() -> None:
    config = load_config()
    from lib.storage import build_storage
    storage = build_storage(config)

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

    if not bot_token or not chat_id:
        print("WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_CHAT_ID not set — skipping.")
        return

    timezone_name = config.get("timezone", "America/Chicago")
    max_age_hours = config.get("reminder_max_age_hours", 24)

    fire_due_reminders(storage, bot_token, chat_id, timezone_name, max_age_hours)
    print("✅ Reminder check complete.")


if __name__ == "__main__":
    main()
