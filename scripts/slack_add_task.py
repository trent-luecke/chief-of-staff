#!/usr/bin/env python3
"""Add a task from a Slack slash command. Called by task_add.yml."""
import json
import os
import sys
import urllib.request
from pathlib import Path

import dateparser
from dateutil import parser as _du_parser

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.storage import LocalStorage
from lib.tasks import add_task


def parse_due_date(raw: str):
    """Parse natural language date to YYYY-MM-DD. Returns None if empty or unparseable."""
    if not raw or not raw.strip():
        return None
    result = dateparser.parse(
        raw,
        settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
    )
    if result is None:
        # Fall back to dateutil for relative phrases like "next monday" that
        # dateparser misses on some platforms.
        try:
            result = _du_parser.parse(raw, fuzzy=True, default=None)
        except Exception:
            return None
    if result is None:
        return None
    return result.strftime("%Y-%m-%d")


def format_confirmation(title: str, due_date) -> str:
    if due_date:
        return f"Task added: {title} — due {due_date}"
    return f"Task added: {title}"


def post_to_slack(response_url: str, text: str) -> None:
    if not response_url:
        return
    payload = json.dumps({"response_type": "ephemeral", "text": text}).encode()
    req = urllib.request.Request(
        response_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Warning: failed to post to Slack response_url: {e}", file=sys.stderr)


def main():
    title = os.environ.get("TASK_TITLE", "").strip()
    response_url = os.environ.get("RESPONSE_URL", "")
    due_date_raw = os.environ.get("DUE_DATE_RAW", "")

    if not title:
        print("Error: TASK_TITLE is required", file=sys.stderr)
        sys.exit(1)

    storage = LocalStorage(base_dir=str(ROOT / "data"))
    due_date = parse_due_date(due_date_raw)
    add_task(storage, title=title, source="slack", due_date=due_date)
    post_to_slack(response_url, format_confirmation(title, due_date))
    print(f"Task added: {title}" + (f" (due {due_date})" if due_date else ""))


if __name__ == "__main__":
    main()
