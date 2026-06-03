"""Thread state store for Avoma Slack processing.

Tracks which Slack thread_ts values have completed Phase 1 and any
pending Phase 2 correction awaiting Trent's confirmation.

State schema per thread_ts key:
{
  "phase": 2,
  "avoma_uuid": str | null,
  "processed_at": "2026-06-02T10:00:00+00:00",
  "output_ts": str | null,
  "phase1_output": str,
  "transcript_json": dict,
  "pending_correction": null | {
    "description": str,
    "writes": [{"type": str, "target": str, "value": str}],
    "notion_payload": str | null,
    "confirmation_prompt": str,
  }
  "pending_project_link": null | {
    "candidate_ids": [str],
    "project_ids": [str],
    "obs_date": str,
    "obs_entity": str,
    "call_title": str,
    "confirmation_prompt": str,
  }
}
"""

from __future__ import annotations
from datetime import datetime, timezone

_STATE_KEY = "state/avoma_thread_state.json"


def _load(storage) -> dict:
    return storage.read_json(_STATE_KEY, default={})


def _save(storage, state: dict) -> None:
    storage.write_json(_STATE_KEY, state)


def is_processed(storage, thread_ts: str) -> bool:
    return thread_ts in _load(storage)


def get_thread_record(storage, thread_ts: str) -> dict | None:
    return _load(storage).get(thread_ts)


def set_phase1_complete(
    storage,
    thread_ts: str,
    avoma_uuid: str | None,
    output_ts: str | None,
    phase1_output: str,
    transcript_json: dict,
) -> None:
    state = _load(storage)
    state[thread_ts] = {
        "phase": 2,
        "avoma_uuid": avoma_uuid,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "output_ts": output_ts,
        "phase1_output": phase1_output,
        "transcript_json": transcript_json,
        "pending_correction": None,
    }
    _save(storage, state)


def set_pending_correction(storage, thread_ts: str, correction: dict) -> None:
    state = _load(storage)
    if thread_ts not in state:
        return
    state[thread_ts]["pending_correction"] = correction
    _save(storage, state)


def clear_pending_correction(storage, thread_ts: str) -> None:
    state = _load(storage)
    if thread_ts not in state:
        return
    state[thread_ts]["pending_correction"] = None
    _save(storage, state)


def set_pending_project_link(storage, thread_ts: str, link_proposal: dict) -> None:
    """Store a proposed project link awaiting confirmation."""
    state = _load(storage)
    if thread_ts not in state:
        return
    state[thread_ts]["pending_project_link"] = link_proposal
    _save(storage, state)


def clear_pending_project_link(storage, thread_ts: str) -> None:
    state = _load(storage)
    if thread_ts not in state:
        return
    state[thread_ts]["pending_project_link"] = None
    _save(storage, state)
