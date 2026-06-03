# lib/project_candidates.py
import uuid
from datetime import date
from typing import Optional

_KEY = "project_link_candidates.json"


def _load(storage) -> dict:
    return storage.read_json(_KEY, default={"candidates": []})


def _save(storage, data: dict) -> None:
    storage.write_json(_KEY, data)


def flag_candidate(
    storage,
    project_id: str,
    obs_date: str,
    obs_entity: str,
    source_thread_ts: str,
    call_title: str,
) -> dict:
    data = _load(storage)
    candidate = {
        "id": f"plc-{uuid.uuid4().hex[:6]}",
        "project_id": project_id,
        "obs_date": obs_date,
        "obs_entity": obs_entity,
        "source_thread_ts": source_thread_ts,
        "call_title": call_title,
        "status": "pending",
        "created": date.today().isoformat(),
    }
    data["candidates"].append(candidate)
    _save(storage, data)
    return candidate


def get_candidate(storage, candidate_id: str) -> Optional[dict]:
    for c in _load(storage)["candidates"]:
        if c["id"] == candidate_id:
            return c
    return None


def list_pending_candidates(storage) -> list:
    return [c for c in _load(storage)["candidates"] if c["status"] == "pending"]


def resolve_candidate(storage, candidate_id: str, resolution: str) -> Optional[dict]:
    data = _load(storage)
    for c in data["candidates"]:
        if c["id"] == candidate_id:
            c["status"] = resolution
            _save(storage, data)
            return c
    return None
