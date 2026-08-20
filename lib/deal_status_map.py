"""Map a Notion pipeline Status to the deal store's (stage, outcome)."""
from __future__ import annotations

_STATUS_MAP: dict[str, tuple[str, str]] = {
    "Demo Scheduled": ("demoed", "open"),
    "No-Show": ("demoed", "open"),
    "Out of Demo / Need Upate": ("demoed", "open"),  # Notion's own spelling
    "No Trial / Post Demo": ("demoed", "open"),
    "On-Hold": ("demoed", "open"),
    "In-Trial / Post Demo": ("in_trial", "open"),
    "Closed": ("won", "won"),
    "Lost": ("lost", "lost"),
}


def map_notion_status(status: str | None) -> tuple[str, str]:
    """Return (stage, outcome) for a Notion Status string. Unknown/blank ->
    ('demoed', 'open'). Total: never raises."""
    return _STATUS_MAP.get((status or "").strip(), ("demoed", "open"))
