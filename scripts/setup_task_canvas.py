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
load_dotenv()

from lib.slack_canvas import setup_canvas


def main() -> None:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        print("ERROR: SLACK_BOT_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)

    with open("config.json") as f:
        config = json.load(f)
    email = config.get("email", "")
    if not email:
        print("ERROR: 'email' not found in config.json", file=sys.stderr)
        sys.exit(1)

    if config.get("slack_canvas", {}).get("canvas_id"):
        print(f"Canvas already configured: {config['slack_canvas']['canvas_id']}")
        print("Delete 'slack_canvas' from config.json to recreate.")
        sys.exit(0)

    print(f"Creating task canvas for {email}...")
    result = setup_canvas(token, email)
    print(f"✅ Canvas created: {result['canvas_id']}")
    print(f"   DM channel: {result['channel_id']}")
    print(f"   config.json updated with slack_canvas block.")


if __name__ == "__main__":
    main()
