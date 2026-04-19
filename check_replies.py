#!/usr/bin/env python3
"""Entry point for email reply polling. Called by reply-check.yml workflow."""

import json
import os
import sys
from datetime import date

from dotenv import load_dotenv
load_dotenv()

from lib.google_auth import build_gmail_service
from processors.feedback import classify_feedback, append_brief_feedback
from lib.captures import append_capture
from outputs.sender import send_brief_email


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_brief_state(state_dir: str) -> dict | None:
    path = os.path.join(state_dir, "brief_message_id.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_brief_state(state_dir: str, state: dict) -> None:
    path = os.path.join(state_dir, "brief_message_id.json")
    with open(path, "w") as f:
        json.dump(state, f)


def main() -> None:
    config = load_config()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    user_email = config["email"]

    state = load_brief_state(config["state_dir"])
    if not state:
        print("No brief state found — skipping reply check.")
        return

    if state.get("date") != date.today().isoformat():
        print(f"Brief state is from {state.get('date')} — skipping.")
        return

    thread_id = state.get("thread_id")
    if not thread_id:
        print("No thread_id in brief state — skipping.")
        return

    gmail = build_gmail_service(user_email)

    try:
        thread_data = gmail.users().threads().get(
            userId="me", id=thread_id, format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()
    except Exception as e:
        print(f"WARNING: Could not fetch brief thread: {e}", file=sys.stderr)
        return

    messages = thread_data.get("messages", [])
    brief_msg_id = state.get("message_id")
    processed_ids = set(state.get("processed_reply_ids", []))

    # Find replies: messages after the original brief, from user_email, not yet processed
    replies = []
    found_original = False
    for msg in messages:
        if msg["id"] == brief_msg_id:
            found_original = True
            continue
        if found_original and msg["id"] not in processed_ids:
            headers = msg.get("payload", {}).get("headers", [])
            from_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
            if user_email.lower() in from_header.lower():
                replies.append(msg)

    if not replies:
        print("No new replies found.")
        return

    brief_subject = state.get("subject", "Morning Brief")
    captures_file = config.get("captures_file", "data/captures.md")
    feedback_file = config.get("brief_feedback_file", "data/brief_feedback.md")

    for reply in replies:
        snippet = reply.get("snippet", "")
        print(f"Processing reply: {snippet[:80]}...")

        result = classify_feedback(
            api_key=api_key,
            model=config["ai_model"],
            reply_body=snippet,
            brief_subject=brief_subject,
        )

        if result.classification == "action_signal" and result.capture_content:
            append_capture(captures_file, result.capture_type or "flag",
                           result.capture_target, result.capture_content)
            ack = f"Got it — logged as [{result.capture_type or 'flag'}]: {result.capture_content}"
        elif result.classification == "delivery_note" and result.delivery_note:
            append_brief_feedback(feedback_file, result.delivery_note)
            ack = f"Got it — noted for future briefs: {result.delivery_note}"
        else:
            ack = result.clarification_question or "Received — could you clarify what you'd like me to do?"

        try:
            _, _ = send_brief_email(
                gmail_service=gmail,
                to_email=user_email,
                subject=f"Re: {brief_subject}",
                html_body=f"<p>{ack}</p>",
                thread_id=thread_id,
            )
            print(f"Acknowledged: {ack}")
        except Exception as e:
            print(f"WARNING: Could not send acknowledgment: {e}", file=sys.stderr)

        processed_ids.add(reply["id"])

    state["processed_reply_ids"] = list(processed_ids)
    save_brief_state(config["state_dir"], state)


if __name__ == "__main__":
    main()
