#!/usr/bin/env python3
"""Check for due reminders and send them via Slack DM. Called by reminders.yml."""

import json
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

    timezone_name = config.get("timezone", "America/Chicago")
    max_age_hours = config.get("reminder_max_age_hours", 24)

    fire_due_reminders(storage, config, timezone_name, max_age_hours)
    print("✅ Reminder check complete.")


if __name__ == "__main__":
    main()
