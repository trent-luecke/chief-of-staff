import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


@dataclass
class StateSnapshot:
    date: str
    open_email_thread_ids: list[str] = field(default_factory=list)
    open_notion_item_ids: list[str] = field(default_factory=list)


def _snapshot_path(target_date: date, state_dir: str) -> str:
    return os.path.join(state_dir, f"state_{target_date.isoformat()}.json")


def save_snapshot(snapshot: StateSnapshot, state_dir: str) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = _snapshot_path(date.fromisoformat(snapshot.date), state_dir)
    with open(path, "w") as f:
        json.dump(asdict(snapshot), f, indent=2)


def load_snapshot(target_date: date, state_dir: str) -> Optional[StateSnapshot]:
    path = _snapshot_path(target_date, state_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return StateSnapshot(**data)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def diff_snapshots(
    previous: StateSnapshot,
    today_email_ids: list[str],
    today_notion_ids: list[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Returns (resolved, still_open) dicts each with 'email' and 'notion' keys.

    resolved: items that were in yesterday's snapshot but not in today's state
    still_open: items that were in yesterday's snapshot AND still in today's state
    """
    prev_emails = set(previous.open_email_thread_ids)
    prev_notion = set(previous.open_notion_item_ids)
    curr_emails = set(today_email_ids)
    curr_notion = set(today_notion_ids)

    resolved = {
        "email": list(prev_emails - curr_emails),
        "notion": list(prev_notion - curr_notion),
    }
    still_open = {
        "email": list(prev_emails & curr_emails),
        "notion": list(prev_notion & curr_notion),
    }
    return resolved, still_open
