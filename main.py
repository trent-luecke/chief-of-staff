#!/usr/bin/env python3
"""AI Chief of Staff — Morning Brief Orchestrator."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from pipeline import collect_signals, process_context, generate_and_deliver


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _attach_avoma_payload(config: dict, storage, dry_run: bool, no_email: bool) -> None:
    """If avoma_prompt_payload.md was written by the nightly sync, reply to the brief thread with it."""
    import html as _html_mod

    payload_path = Path("data/avoma_prompt_payload.md")
    if not payload_path.exists():
        return

    try:
        payload_content = payload_path.read_text(encoding="utf-8").strip()
        if not payload_content:
            payload_path.unlink(missing_ok=True)
            return

        if dry_run or no_email:
            print("   📋 Avoma payload found — skipped in dry-run/no-email mode.")
            payload_path.unlink(missing_ok=True)
            return

        brief_state = storage.read_json("state/brief_message_id.json") or {}
        thread_id = brief_state.get("thread_id")
        if not thread_id:
            print("WARNING: No brief thread_id — Avoma payload not attached.", file=sys.stderr)
            return

        from lib.google_auth import build_gmail_service
        from outputs.sender import send_brief_email

        escaped = _html_mod.escape(payload_content)
        html_body = (
            "<h2 style='font-family:sans-serif;color:#333;'>📋 Avoma Update Payload</h2>"
            "<p style='font-family:sans-serif;color:#666;margin-bottom:16px;'>"
            "Paste the relevant section into Claude desktop to apply pipeline or onboarding updates.</p>"
            "<details open style='margin-top:8px;'>"
            "<summary style='font-weight:bold;cursor:pointer;padding:8px;"
            "background:#f5f5f5;border-radius:4px;font-family:sans-serif;'>View payload</summary>"
            f"<pre style='background:#f9f9f9;padding:16px;border-radius:4px;"
            f"overflow-x:auto;white-space:pre-wrap;font-size:13px;line-height:1.5;'>{escaped}</pre>"
            "</details>"
        )

        gmail = build_gmail_service(config["email"])
        send_brief_email(
            gmail,
            config["email"],
            "📋 Avoma Update Payload — paste into Claude desktop to apply",
            html_body,
            plain_text="Avoma update payload — view in an HTML email client.",
            thread_id=thread_id,
        )
        print("   📋 Avoma payload sent as brief thread reply.")
        payload_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"⚠️ Avoma payload attach error (non-fatal): {e}", file=sys.stderr)


def run(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    from lib.storage import build_storage
    from lib.llm_logger import flush
    storage = build_storage(config)
    try:
        _run_inner(config, storage, dry_run=dry_run, no_email=no_email)
    finally:
        flush("daily_brief", storage)


def _run_inner(config: dict, storage, dry_run: bool = False, no_email: bool = False) -> None:
    from datetime import date, datetime, timezone
    from lib.health import RunHealth, timed

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    health = RunHealth(
        run_date=date.today().isoformat(),
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    with timed() as total:
        collected = collect_signals(config, health, storage)
        ctx = process_context(config, collected, health, storage)
        generate_and_deliver(config, ctx, dry_run=dry_run, no_email=no_email, health=health, storage=storage)

    health.total_duration_ms = total.elapsed_ms
    health.compute_overall_status()

    try:
        storage.write_json("state/health.json", health.to_dict())
        status_icon = {"ok": "✅", "degraded": "⚠️", "failed": "❌"}.get(health.overall_status, "?")
        print(f"\n{status_icon} Run health: {health.overall_status} ({health.total_duration_ms}ms)")
    except Exception as e:
        print(f"⚠️ Health write error (non-fatal): {e}", file=sys.stderr)

    _attach_avoma_payload(config, storage, dry_run=dry_run, no_email=no_email)


def main():
    parser = argparse.ArgumentParser(description="AI Chief of Staff Morning Brief")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    config = load_config(args.config)
    run(config, dry_run=args.dry_run, no_email=args.no_email)


if __name__ == "__main__":
    main()
