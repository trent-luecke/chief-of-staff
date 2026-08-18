"""Client for the OS-Metric-Sync engine — the only module that talks to it.

trigger_sync() drives a refresh; fetch_snapshot() reads the canonical contract
with a last-good cache fallback so the brief never hard-fails on engine downtime.
"""

from __future__ import annotations

import sys
import requests
from lib.gtm_metrics import evaluate_metrics, MetricResult

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


def sync_failures(report: dict) -> list[str]:
    """Return source names that did not sync OK in a /api/sync-all report."""
    return [r["source"] for r in report.get("report", []) if r.get("status") != "ok"]


def metrics_from_snapshot(snapshot: dict, onboarding_active: list[dict], today=None) -> list[MetricResult]:
    """Map a canonical snapshot + local onboarding into MetricResult objects."""
    cancellations = snapshot.get("cancellations") or {}
    return evaluate_metrics(
        demos_data=snapshot.get("demos_data"),
        sales_data=snapshot.get("sales_data"),
        onboarding_active=onboarding_active,
        cancellations=cancellations if cancellations.get("count", 0) > 0 else None,
        cfg=snapshot.get("targets", {}),
        today=today,
    )


def push_demos(base_url: str, password: str, demos: list[dict], timeout: int = 60) -> dict:
    """POST detected demos to the engine /api/demos/ingest. Never raises."""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/demos/ingest",
            auth=("", password),
            json={"demos": demos},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️  Demo push failed (non-fatal): {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)[:200]}


def push_deals(base_url: str, password: str, deals: list[dict], timeout: int = 60) -> dict:
    """POST resolved deals to the engine /api/deals/ingest. Never raises."""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/deals/ingest",
            auth=("", password),
            json={"deals": deals},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️  Deal push failed (non-fatal): {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)[:200]}
