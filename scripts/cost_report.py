#!/usr/bin/env python3
"""View / refresh the LLM API cost summary.

The cost log (data/state/llm_calls.jsonl) is git-anchored and written by every
Claude-calling job via lib.llm_logger.flush(). This reads it and prints a
per-job / per-call-site / per-model breakdown so you can see where the API
spend actually goes.

    python3 scripts/cost_report.py            # print the breakdown
    python3 scripts/cost_report.py --write     # also rewrite cost_summary.json
    python3 scripts/cost_report.py --json       # dump the raw summary JSON
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.cost_report import build_summary_from_storage, format_table, refresh  # noqa: E402
from lib.storage import registry_storage  # noqa: E402


def load_config(path: str = "config.json") -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM API cost breakdown")
    ap.add_argument("--write", action="store_true", help="rewrite data/state/cost_summary.json")
    ap.add_argument("--json", action="store_true", help="print raw summary JSON")
    args = ap.parse_args()

    store = registry_storage(load_config())
    if args.write:
        summary = refresh(store)
    else:
        summary = build_summary_from_storage(store)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(format_table(summary))


if __name__ == "__main__":
    main()
