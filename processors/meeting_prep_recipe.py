"""Per-meeting prep recipes for the Today tab.

Deterministic block gathering + one LLM synthesis call. Non-fatal throughout:
a failing block is dropped; a failing synthesis yields None. The legacy
processors/meeting_prep.py (emailed brief) is intentionally not reused.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from lib import meetings as meetings_lib
from processors.meeting_memory import load_last_session_summary

log = logging.getLogger(__name__)


@dataclass
class PrepContext:
    event: object          # collectors.calendar.CalendarEvent (duck-typed in tests)
    meeting_cfg: object    # processors.meeting_memory.MeetingConfig
    config: dict
    storage: object


def gather_open_threads(ctx: PrepContext, params: dict) -> Optional[str]:
    data_dir = ctx.config.get("data_dir", "data")
    state = meetings_lib.replay_local(data_dir)
    mtg = state.get(ctx.meeting_cfg.meeting_id)
    if not mtg:
        return None
    threads = meetings_lib.open_threads(mtg)
    if not threads:
        return None
    lines = ["## Open Threads"]
    for t in threads:
        owner = f" (→ {t['person_id']})" if t.get("person_id") else ""
        lines.append(f"- {t.get('text', '')}{owner}")
    return "\n".join(lines)


def gather_last_session(ctx: PrepContext, params: dict) -> Optional[str]:
    key = ctx.meeting_cfg.memory_file
    if key.startswith("data/"):
        key = key[len("data/"):]
    summary = load_last_session_summary(ctx.storage, key)
    if not summary or not summary.strip():
        return None
    return "## Last Session\n" + summary.strip()
