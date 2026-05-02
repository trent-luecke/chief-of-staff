from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


@dataclass
class StateSnapshot:
    date: str
    open_email_thread_ids: list[str] = field(default_factory=list)
    open_notion_item_ids: list[str] = field(default_factory=list)


def save_snapshot(snapshot: StateSnapshot, storage) -> None:
    key = f"state/state_{snapshot.date}.json"
    storage.write_json(key, asdict(snapshot))


def load_snapshot(target_date: date, storage) -> Optional[StateSnapshot]:
    key = f"state/state_{target_date.isoformat()}.json"
    data = storage.read_json(key)
    if data is None:
        return None
    try:
        return StateSnapshot(**data)
    except (TypeError, KeyError):
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
