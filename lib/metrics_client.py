"""Client for the OS-Metric-Sync engine — the only module that talks to it.

trigger_sync() drives a refresh; fetch_snapshot() reads the canonical contract
with a last-good cache fallback so the brief never hard-fails on engine downtime.
"""

from __future__ import annotations

import sys
import requests

SNAPSHOT_CACHE_KEY = "state/metrics_snapshot.json"


def trigger_sync(base_url: str, password: str, timeout: int = 120) -> dict:
    """POST /api/sync-all. Returns the report dict; never raises."""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/sync-all",
            auth=("", password),
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️  Metrics sync trigger failed (non-fatal): {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)[:200], "report": []}


def fetch_snapshot(base_url: str, password: str, storage, timeout: int = 30) -> dict | None:
    """GET /api/metrics/snapshot with last-good cache fallback.

    Returns the snapshot dict with a `stale` flag, or None if the engine is
    unreachable and no cached snapshot exists.
    """
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/api/metrics/snapshot",
            auth=("", password),
            timeout=timeout,
        )
        resp.raise_for_status()
        snap = resp.json()
        snap["stale"] = False
        storage.write_json(SNAPSHOT_CACHE_KEY, snap)
        return snap
    except Exception as e:
        print(f"⚠️  Metrics snapshot fetch failed (non-fatal): {e}", file=sys.stderr)
        cached = storage.read_json(SNAPSHOT_CACHE_KEY)
        if cached:
            cached["stale"] = True
            cached["stale_reason"] = f"live fetch failed ({str(e)[:80]}); using last-good snapshot"
            return cached
        return None
