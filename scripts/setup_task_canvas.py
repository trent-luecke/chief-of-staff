#!/usr/bin/env python3
"""One-time setup: create the task canvas in Slack and store its ID in config.json.

Run from the project root:
    python scripts/setup_task_canvas.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from lib.slack_canvas import setup_canvas


def main() -> None:
    user_token = os.environ.get("SLACK_USER_TOKEN", "")
    if not user_token:
        print("ERROR: SLACK_USER_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)

    print("Creating task canvas in your Slack self-DM...")
    result = setup_canvas(user_token)
    print(f"✅ Canvas created: {result['canvas_id']}")
    print(f"   Self-DM channel: {result['channel_id']}")
    print(f"   config.json updated with slack_canvas block.")


if __name__ == "__main__":
    main()
