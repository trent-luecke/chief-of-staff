#!/usr/bin/env python3
"""Entry point for email reply polling. Called by reply-check.yml workflow."""

import base64 as _base64
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


def _get_message_body(gmail, msg_id: str, fallback_snippet: str) -> str:
    try:
        msg = gmail.users().messages().get(userId="me", id=msg_id, format="full").execute()
        payload = msg.get("payload", {})
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return _base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        data = payload.get("body", {}).get("data", "")
        if data:
            return _base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except Exception:
        pass
    return fallback_snippet


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_brief_state(storage) -> dict | None:
    return storage.read_json("state/brief_message_id.json")


def save_brief_state(storage, state: dict) -> None:
    storage.write_json("state/brief_message_id.json", state)


def main() -> None:
    config = load_config()
    from lib.storage import build_storage
    from lib.llm_logger import flush
    storage = build_storage(config)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    user_email = config["email"]

    state = load_brief_state(storage)
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
            metadataHeaders=["Subject", "From", "Date", "X-CoS-Type"],
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
            cos_type = next((h["value"] for h in headers if h["name"].lower() == "x-cos-type"), "")
            if cos_type == "ack":
                processed_ids.add(msg["id"])
                continue
            from_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
            if user_email.lower() in from_header.lower():
                replies.append(msg)

    if not replies:
        print("No new replies found.")
        if processed_ids != set(state.get("processed_reply_ids", [])):
            state["processed_reply_ids"] = list(processed_ids)
            save_brief_state(storage, state)
        return

    brief_subject = state.get("subject", "Morning Brief")

    try:
        for reply in replies:
            snippet = reply.get("snippet", "")
            reply_body = _get_message_body(gmail, reply["id"], snippet)
            print(f"Processing reply: {reply_body[:80]}...")

            result = classify_feedback(
                api_key=api_key,
                model=config["ai_model"],
                reply_body=reply_body,
                brief_subject=brief_subject,
            )

            if result.classification == "action_signal" and result.capture_content:
                append_capture(storage, result.capture_type or "flag",
                               result.capture_target, result.capture_content)
                ack = f"Got it — logged as [{result.capture_type or 'flag'}]: {result.capture_content}"
            elif result.classification == "delivery_note" and result.delivery_note:
                append_brief_feedback(storage, result.delivery_note)
                ack = f"Got it — noted for future briefs: {result.delivery_note}"
            elif result.classification in ("action_signal", "delivery_note"):
                print(f"WARNING: classifier returned {result.classification} with no content — asking for clarification.", file=sys.stderr)
                ack = "I understood the intent but couldn't extract the specific action. Could you rephrase?"
            else:
                ack = result.clarification_question or "Received — could you clarify what you'd like me to do?"

            try:
                # Threads via Gmail's threadId; standard In-Reply-To/References headers not set.
                # Some non-Gmail clients may display ack emails outside the brief thread.
                ack_msg_id, _ = send_brief_email(
                    gmail_service=gmail,
                    to_email=user_email,
                    subject=f"Re: {brief_subject}",
                    html_body=f"<p>{ack}</p>",
                    thread_id=thread_id,
                    is_ack=True,
                )
                print(f"Acknowledged: {ack}")
                if ack_msg_id:
                    processed_ids.add(ack_msg_id)
            except Exception as e:
                print(f"WARNING: Could not send acknowledgment: {e}", file=sys.stderr)

            processed_ids.add(reply["id"])
            state["processed_reply_ids"] = list(processed_ids)
            save_brief_state(storage, state)
    finally:
        flush("email_reply", storage)


if __name__ == "__main__":
    main()
