#!/usr/bin/env python3
"""AI Chief of Staff — Morning Brief Orchestrator."""

import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from pipeline import collect_signals, process_context, generate_and_deliver


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


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

        # Pre-compute the Today brief (git-anchored) — non-fatal.
        try:
            from lib.storage import registry_storage
            from processors.today_brief import generate_and_write
            generate_and_write(
                config,
                collected.today_events,
                registry_storage(config),
                today=date.today().isoformat(),
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
            print("   ✅ brief_today.json generated")
        except Exception as e:
            print(f"⚠️ Today-brief generation error (non-fatal): {e}", file=sys.stderr)

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
