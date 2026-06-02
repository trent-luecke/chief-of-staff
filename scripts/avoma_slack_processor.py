#!/usr/bin/env python3
"""Avoma Slack thread processor — dispatched by avoma_slack_trigger.yml.

Reads env vars, routes to Phase 1 (first reply) or Phase 2 (subsequent replies).
"""

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")

    thread_ts = os.environ.get("AVOMA_THREAD_TS", "").strip()
    channel_id = os.environ.get("AVOMA_CHANNEL_ID", "").strip()
    trigger_text = os.environ.get("AVOMA_TRIGGER_TEXT", "").strip()
    avoma_key = os.environ.get("AVOMA_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    slack_bot_token = os.environ.get("SLACK_BOT_TOKEN", "")

    for name, val in [
        ("AVOMA_THREAD_TS", thread_ts),
        ("AVOMA_CHANNEL_ID", channel_id),
        ("AVOMA_API_KEY", avoma_key),
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("SLACK_BOT_TOKEN", slack_bot_token),
    ]:
        if not val:
            print(f"ERROR: {name} not set — avoma_slack_processor cannot run.", file=sys.stderr)
            sys.exit(0)  # non-fatal — never fail the Actions run

    config_path = _ROOT / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    from lib.storage import build_storage
    storage = build_storage(config)

    from processors.avoma_thread_state import is_processed, get_thread_record

    if not is_processed(storage, thread_ts):
        print(f"Phase 1: processing thread {thread_ts}")
        from processors.avoma_phase1 import run_phase1
        run_phase1(thread_ts, channel_id, trigger_text, storage, config, avoma_key, anthropic_key, slack_bot_token)
    else:
        state_record = get_thread_record(storage, thread_ts)
        print(f"Phase 2: conversation for thread {thread_ts}")
        from processors.avoma_phase2 import run_phase2
        run_phase2(thread_ts, trigger_text, state_record, slack_bot_token, channel_id, storage, config, anthropic_key)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: avoma_slack_processor failed: {exc}", file=sys.stderr)
        sys.exit(0)  # non-fatal
