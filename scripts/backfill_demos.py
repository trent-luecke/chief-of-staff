#!/usr/bin/env python3
"""One-time backfill: detect OS demos over a wide window and push to the engine.

Usage: python3 scripts/backfill_demos.py [--hours 840]   # default ~35 days
"""
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def main():
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    from collectors.avoma import fetch_recent_meetings, DEMO_REP_ROSTER
    from lib.demo_detect import detect_demos
    from lib import metrics_client

    hours = 840
    if "--hours" in sys.argv:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])

    config = json.load(open(_ROOT / "config.json"))
    counted = set(config.get("demos", {}).get("counted_reps", []))
    model = config.get("ai_model", "claude-sonnet-4-6")

    print(f"Backfilling demos over last {hours}h...")
    transcripts = fetch_recent_meetings(
        api_key=os.environ["AVOMA_API_KEY"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        model=model,
        lookback_hours=hours,
        rep_roster=DEMO_REP_ROSTER,
        filter_internal=config.get("avoma", {}).get("filter_internal", True),
    )
    records = detect_demos(transcripts, counted)
    print(f"  Detected {len(records)} OS demo(s).")
    result = metrics_client.push_demos(
        os.environ["METRICS_BASE_URL"], os.environ["METRICS_PASSWORD"], records)
    print(f"  Push result: {result}")


if __name__ == "__main__":
    main()
