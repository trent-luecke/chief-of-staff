"""Compose the deal store: demo events -> deals -> pipeline_cache + OMS push."""
from __future__ import annotations

import dataclasses
import sys

from lib.deal_crosswalk import load_crosswalk
from lib.deal_events import append_events, load_events
from lib.deal_fold import build_deals
from lib.deal_normalize import normalize_demo_events, normalize_sale_events
from lib.deal_projection import deals_to_pipeline_cache
from lib.metrics_client import push_deals
from lib.sales_sheet import fetch_sale_rows


def refresh_deal_store(transcripts, storage, today: str, fetched_at: str,
                       stale_days: int = 45, cache_key: str = "deal_pipeline_cache.json",
                       base_url: str = "", password: str = "", config: dict | None = None) -> dict:
    appended = append_events(storage, normalize_demo_events(transcripts))
    if config is not None:
        try:
            sale_rows = fetch_sale_rows(config, today)
            appended += append_events(storage, normalize_sale_events(sale_rows))
        except Exception as e:  # non-fatal: sales never sink the deal refresh
            print(f"⚠️  Sale sync error (non-fatal): {e}", file=sys.stderr)
    events = load_events(storage)
    crosswalk = load_crosswalk(storage)
    deals = build_deals(events, crosswalk, today, stale_days=stale_days)

    # Phase 1a: the deal store is a SUBSET of the live pipeline (demos only,
    # un-backfilled), so it writes to a separate file for inspection/validation.
    # The live pipeline_cache.json seam-swap is deferred to the backfill phase.
    storage.write_json(cache_key, deals_to_pipeline_cache(deals, fetched_at))

    pushed = False
    if base_url:
        push_deals(base_url, password, [dataclasses.asdict(d) for d in deals.values()])
        pushed = True

    return {"deals": len(deals), "appended": appended, "pushed": pushed}
