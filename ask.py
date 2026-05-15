#!/usr/bin/env python3
"""Entry point for Telegram query runs. Called by ask.yml workflow."""

import json
import os
import subprocess
import sys

from dotenv import load_dotenv
load_dotenv()

from processors.query import answer_query_with_tools
from processors.brief_scorer import handle_score_command
from processors.meeting_memory import append_session_notes
from lib.telegram import send_message
from processors.query_tools import PENDING_CHANGE_PATH, CHANGE_WHITELIST


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)



def _resolve_nudge_reply(reply_to_id: str, storage) -> dict | None:
    """Return the pending nudge record if reply_to_id matches a sent nudge, else None."""
    pending = storage.read_json("pending_nudges.json", default=[])
    for nudge in pending:
        if str(nudge.get("telegram_message_id", "")) == reply_to_id:
            return nudge
    return None


def _handle_pending_change(action: str, chat_id: str, bot_token: str) -> None:
    try:
        with open(PENDING_CHANGE_PATH) as f:
            pending = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        if bot_token:
            send_message(bot_token, chat_id, f"Could not read pending change: {e}")
        return

    file_path = pending.get("file", "")
    description = pending.get("description", "")

    if action == "reject":
        os.remove(PENDING_CHANGE_PATH)
        if bot_token:
            send_message(bot_token, chat_id, f"Change to {file_path} rejected and discarded.")
        return

    if file_path not in CHANGE_WHITELIST:
        os.remove(PENDING_CHANGE_PATH)
        if bot_token:
            send_message(bot_token, chat_id, f"Rejected: '{file_path}' is not on the change whitelist. Pending change discarded.")
        return

    new_content = pending.get("new_content", "")
    try:
        with open(file_path, "w") as f:
            f.write(new_content)
    except OSError as e:
        if bot_token:
            send_message(bot_token, chat_id, f"Could not write {file_path}: {e}")
        return

    commit_msg = f"bot: {description} [telegram-approved]"
    try:
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
        subprocess.run(["git", "add", file_path], check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
    except subprocess.CalledProcessError as e:
        if bot_token:
            send_message(bot_token, chat_id, f"Git error after applying change: {e}")
        return

    os.remove(PENDING_CHANGE_PATH)
    if bot_token:
        send_message(bot_token, chat_id, f"Change to {file_path} applied and pushed. Commit: \"{commit_msg}\"")


def _main_inner(query: str, chat_id: str, bot_token: str, config: dict, storage, reply_to_id: str = "") -> None:
    # Approve/reject pending code change — exact match only
    query_normalized = query.strip().lower()
    if query_normalized in ("approve", "reject") and os.path.exists(PENDING_CHANGE_PATH):
        _handle_pending_change(query_normalized, chat_id, bot_token)
        return

    # If this is a Telegram reply to a nudge, route directly to meeting notes
    if reply_to_id:
        nudge = _resolve_nudge_reply(reply_to_id, storage)
        if nudge:
            memory_key = nudge.get("memory_file", "").removeprefix("data/") or None
            if not memory_key:
                safe = nudge["meeting_name"].lower().replace(" ", "_")[:40]
                memory_key = f"meeting_memory/{safe}.md"
            append_session_notes(storage, memory_key, nudge["session_date"], query)

            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                attendees = nudge.get("attendees", [])
                attendee_str = ", ".join(attendees) if attendees else "none listed"
                enriched_query = (
                    f"[MEETING NUDGE REPLY]\n"
                    f"Meeting: {nudge['meeting_name']}\n"
                    f"Date: {nudge['session_date']}\n"
                    f"Attendees (emails): {attendee_str}\n"
                    f"Meeting notes already saved to: {memory_key}\n\n"
                    f"Process these meeting notes. For each attendee, add a note to their people "
                    f"file (match by email in the people profiles). If an attendee has no existing "
                    f"profile, create one using the email prefix as their name. Extract any action "
                    f"items, todos, ideas, or next steps as captures.\n\n"
                    f"Notes:\n{query}"
                )
                try:
                    answer = answer_query_with_tools(
                        api_key=api_key,
                        model=config["ai_model"],
                        query=enriched_query,
                        config=config,
                        storage=storage,
                    )
                except Exception as e:
                    print(f"  WARNING: Claude call failed for nudge reply: {e}", file=sys.stderr)
                    answer = (
                        f"Notes saved for *{nudge['meeting_name']}*.\n"
                        f"📝 Meeting memory: `{memory_key}`\n"
                        f"⚠️ People file updates skipped — API error."
                    )
            else:
                answer = (
                    f"Notes saved for *{nudge['meeting_name']}*.\n"
                    f"📝 Meeting memory: `{memory_key}`"
                )

            if bot_token:
                send_message(bot_token, chat_id, answer)
            print(f"  Notes captured via reply for: {nudge['meeting_name']}")
            return

    # /brief score commands are handled locally — no Claude call, no API cost
    score_response = handle_score_command(query, storage=storage)
    if score_response is not None:
        if bot_token:
            send_message(bot_token, chat_id, score_response)
        return

    # /todo <text> — direct dispatch, no Claude call needed
    if query_normalized.startswith("/todo "):
        text = query[6:].strip()
        if not text:
            if bot_token:
                send_message(bot_token, chat_id, "Usage: /todo <task description>")
            return
        from processors.query_tools import _tool_add_capture
        _tool_add_capture("todo", text, storage, config)
        if bot_token:
            send_message(bot_token, chat_id, f"Done.\n  → task ledger: {text}\n  → Slack canvas: synced")
        return

    # /reminder <text with time> — still uses Claude for time parsing, but forces set_reminder intent
    if query_normalized.startswith("/reminder "):
        text = query[10:].strip()
        if not text:
            if bot_token:
                send_message(bot_token, chat_id, "Usage: /reminder <message and time>")
            return
        query = f"[SLASH COMMAND: set_reminder — you MUST call the set_reminder tool] {text}"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        if bot_token:
            send_message(bot_token, chat_id, "Something went wrong — check Actions logs.")
        sys.exit(1)

    try:
        answer = answer_query_with_tools(
            api_key=api_key,
            model=config["ai_model"],
            query=query,
            config=config,
            storage=storage,
        )
    except Exception as e:
        print(f"Query error: {e}", file=sys.stderr)
        if bot_token:
            send_message(bot_token, chat_id, "Something went wrong — check Actions logs.")
        sys.exit(1)

    if bot_token:
        send_message(bot_token, chat_id, answer)


def main() -> None:
    query = os.environ.get("QUERY_TEXT", "").strip()
    chat_id = os.environ.get("QUERY_CHAT_ID", "").strip()
    reply_to_id = os.environ.get("REPLY_TO_MESSAGE_ID", "").strip()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    allowed_chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

    if not query or not chat_id:
        print("ERROR: QUERY_TEXT and QUERY_CHAT_ID must be set.", file=sys.stderr)
        sys.exit(1)

    if allowed_chat_id and chat_id != allowed_chat_id:
        print(f"Rejected: unknown chat_id {chat_id}", file=sys.stderr)
        sys.exit(0)

    config = load_config()
    from lib.storage import build_storage
    from lib.llm_logger import flush
    storage = build_storage(config)

    try:
        _main_inner(query, chat_id, bot_token, config, storage, reply_to_id=reply_to_id)
    finally:
        flush("ask", storage)


if __name__ == "__main__":
    main()
