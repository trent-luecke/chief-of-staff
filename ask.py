#!/usr/bin/env python3
"""Entry point for Telegram query runs. Called by ask.yml workflow."""

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from processors.query import answer_query_with_tools
from lib.telegram import send_message


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _main_inner(query: str, chat_id: str, bot_token: str, config: dict) -> None:
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
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    allowed_chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

    if not query or not chat_id:
        print("ERROR: QUERY_TEXT and QUERY_CHAT_ID must be set.", file=sys.stderr)
        sys.exit(1)

    if allowed_chat_id and chat_id != allowed_chat_id:
        print(f"Rejected: unknown chat_id {chat_id}", file=sys.stderr)
        sys.exit(0)

    config = load_config()

    from lib.llm_logger import flush
    try:
        _main_inner(query, chat_id, bot_token, config)
    finally:
        flush("telegram_query", config.get("logs_file", "data/logs/run_log.jsonl"))


if __name__ == "__main__":
    main()
