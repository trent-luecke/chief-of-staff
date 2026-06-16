#!/usr/bin/env python3
"""Reply collector: checks for replies to nudge emails and writes them to meeting memory files."""

import base64
import json
import os
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

import lib.meetings as meetings_lib


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
    from lib.storage import build_storage
    storage = build_storage(config)
    profile = config.get("gmail_profile", "work")

    pending = storage.read_json("pending_nudges.json", default=[])
    if not pending:
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
            meeting_id = memory_file.rsplit("/", 1)[-1].removesuffix(".md")
            meetings_lib.append_session_local(config.get("data_dir", "data"), meeting_id, nudge["session_date"], reply_text.strip())
            print(f"  Captured notes for: {nudge['meeting_name']}")
        else:
            still_pending.append(nudge)

    storage.write_json("pending_nudges.json", still_pending)
    print("✅ Reply collector complete.")


if __name__ == "__main__":
    run()
