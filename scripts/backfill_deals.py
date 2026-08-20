#!/usr/bin/env python3
"""One-shot: import Notion pipeline_cache.json records as `seed` DealEvents.

Reads the pipeline_cache.json snapshot (produced via the normal sync path),
transforms each lead into a seed event, and appends unseen ones to
data/deal_events.jsonl. Idempotent (keyed on Notion page_id). Run --dry-run
first; commit deal_events.jsonl to origin/main after a real run."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone

from lib.deal_backfill import normalize_seed_events
from lib.deal_events import append_events
from lib.storage import registry_storage


def run_backfill(storage, import_ts: str, dry_run: bool = False,
                 cache_key: str = "pipeline_cache.json") -> dict:
    cache = storage.read_json(cache_key, default={}) or {}
    leads = cache.get("leads", []) or []
    events = normalize_seed_events(leads, import_ts)
    by_stage = Counter(e.payload.get("stage", "") for e in events)
    notion_keyed = sum(1 for e in events if e.email.startswith("notion:"))
    appended = 0 if dry_run else append_events(storage, events)
    return {
        "leads": len(leads),
        "events": len(events),
        "appended": appended,
        "by_stage": dict(by_stage),
        "notion_keyed": notion_keyed,
        "email_keyed": len(events) - notion_keyed,
        "skipped_no_page_id": len(leads) - len(events),
        "dry_run": dry_run,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="One-shot Notion pipeline backfill.")
    ap.add_argument("--dry-run", action="store_true", help="compute + report, append nothing")
    ap.add_argument("--config", default="config.json")
    args = ap.parse_args()
    with open(args.config) as f:
        config = json.load(f)
    storage = registry_storage(config)
    import_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = run_backfill(storage, import_ts, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        print("\n[dry-run] nothing appended. Re-run without --dry-run to write, "
              "then commit data/deal_events.jsonl to origin/main.")


if __name__ == "__main__":
    main()
