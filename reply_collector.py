#!/usr/bin/env python3
"""Reply collector: checks for replies to nudge emails and writes them to meeting memory files."""

import base64
import json
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from processors.meeting_memory import append_session_notes


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def get_thread_message_count(thread_id: str, profile: str) -> int:
    params = json.dumps({"userId": "me", "id": thread_id, "format": "minimal"})
    result = subprocess.run(
        ["gws", "--profile", profile, "gmail", "users", "threads", "get", "--params", params],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return 0
    try:
        data = json.loads(result.stdout)
        return len(data.get("messages", []))
    except json.JSONDecodeError:
        return 0


def get_latest_reply_text(thread_id: str, profile: str) -> str:
    params = json.dumps({"userId": "me", "id": thread_id, "format": "full"})
    result = subprocess.run(
        ["gws", "--profile", profile, "gmail", "users", "threads", "get", "--params", params],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return ""
    try:
        data = json.loads(result.stdout)
        messages = data.get("messages", [])
        if len(messages) < 2:
            return ""
        last = messages[-1]
        parts = last.get("payload", {}).get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                body = part.get("body", {}).get("data", "")
                return base64.urlsafe_b64decode(body + "==").decode("utf-8", errors="ignore")
        return last.get("snippet", "")
    except Exception:
        return ""


def run() -> None:
    config = load_config()
    pending_file = config["pending_nudges_file"]
    profile = config.get("gmail_profile", "work")

    try:
        with open(pending_file) as f:
            pending = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    cutoff = datetime.now() - timedelta(days=7)
    still_pending = []

    for nudge in pending:
        sent_at = datetime.fromisoformat(nudge["sent_at"])
        if sent_at < cutoff:
            continue

        thread_id = nudge.get("thread_id")
        memory_file = nudge.get("memory_file")
        if not thread_id or not memory_file:
            still_pending.append(nudge)
            continue

        count = get_thread_message_count(thread_id, profile)
        if count < 2:
            still_pending.append(nudge)
            continue

        reply_text = get_latest_reply_text(thread_id, profile)
        if reply_text.strip():
            append_session_notes(memory_file, nudge["session_date"], reply_text)
            print(f"  Captured notes for: {nudge['meeting_name']}")
        else:
            still_pending.append(nudge)

    with open(pending_file, "w") as f:
        json.dump(still_pending, f, indent=2)

    print("✅ Reply collector complete.")


if __name__ == "__main__":
    run()
