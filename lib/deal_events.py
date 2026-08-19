"""Append-only DealEvent log. Deals are derived by folding these events."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

_KEY = "deal_events.jsonl"


@dataclass
class DealEvent:
    event_id: str
    email: str
    email_raw: str
    kind: str  # demo | trial | sale | status | manual
    timestamp: str  # ISO 8601
    account_name: str = ""
    rep: str = ""
    source: str = ""
    payload: dict = field(default_factory=dict)


def make_event_id(kind: str, native_id: str, email: str) -> str:
    raw = f"{kind}|{native_id}|{email}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_events(storage, key: str = _KEY) -> list[DealEvent]:
    content = storage.read(key) or ""
    events: list[DealEvent] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = DealEvent(**json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(ev.payload, dict):
            ev.payload = {}
        events.append(ev)
    return events


def append_events(storage, events: list[DealEvent], key: str = _KEY) -> int:
    seen = {e.event_id for e in load_events(storage, key)}
    appended = 0
    for e in events:
        if e.event_id in seen:
            continue
        storage.append_line(key, json.dumps(asdict(e)))
        seen.add(e.event_id)
        appended += 1
    return appended
