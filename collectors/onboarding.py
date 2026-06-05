"""Onboarding cache reader — loads data/onboarding_cache.json and filters to active records."""

import json


def load_onboarding_active(cache_path: str, active_statuses: list[str]) -> list[dict]:
    """Return onboarding records whose status is in active_statuses.

    Returns empty list if the cache is missing or unreadable (non-fatal).
    len(result) is the late-stage count for GTM metrics.
    """
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    status_set = set(active_statuses)
    return [r for r in data.get("records", []) if r.get("status") in status_set]
