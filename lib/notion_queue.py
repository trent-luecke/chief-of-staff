"""Append-only JSONL queue for Notion updates (data/notion_updates_queue.jsonl).

Written by the nightly avoma_sync producer and the Telegram queue_notion_update
tool; drained by the local Cowork routine, which dedups on `id` via a laptop-
local seen-set and never mutates this file. JSONL + a merge=union git driver
means concurrent appends never clobber each other.
"""
import json
import os
from datetime import datetime, timezone

DEFAULT_QUEUE_PATH = "data/notion_updates_queue.jsonl"


def _dumps(entry: dict) -> str:
    return json.dumps(entry, separators=(",", ":"))


def append_entries(queue_path: str, entries: list[dict]) -> int:
    if not entries:
        return 0
    os.makedirs(os.path.dirname(queue_path) or ".", exist_ok=True)
    with open(queue_path, "a") as f:
        for e in entries:
            f.write(_dumps(e) + "\n")
    return len(entries)


def parse_jsonl(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_queue(queue_path: str) -> list[dict]:
    try:
        with open(queue_path) as f:
            return parse_jsonl(f.read())
    except FileNotFoundError:
        return []


def prune_text(text: str, max_age_days: int, now: datetime) -> str:
    kept = []
    for e in parse_jsonl(text):
        ts = e.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
        except (ValueError, AttributeError):
            dt = None
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt is not None and (now - dt).days > max_age_days:
            continue
        kept.append(e)
    return "".join(_dumps(e) + "\n" for e in kept)


def prune_file(queue_path: str, max_age_days: int = 30, now: datetime | None = None) -> int:
    try:
        with open(queue_path) as f:
            text = f.read()
    except FileNotFoundError:
        return 0
    now = now or datetime.now(timezone.utc)
    before = len(parse_jsonl(text))
    pruned = prune_text(text, max_age_days, now)
    after = len(parse_jsonl(pruned))
    if after != before:
        with open(queue_path, "w") as f:
            f.write(pruned)
    return before - after
