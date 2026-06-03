# lib/project_links.py
import json
from datetime import date
from typing import Optional

_KEY = "project_observation_links.jsonl"


def _replay(storage) -> dict:
    """Return active links as {(project_id, obs_date, obs_entity): link_dict}."""
    content = storage.read(_KEY) or ""
    active: dict = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (event["project_id"], event["obs_date"], event["obs_entity"])
        if event["event"] == "link":
            active[key] = {
                "project_id": event["project_id"],
                "obs_date": event["obs_date"],
                "obs_entity": event["obs_entity"],
                "call_title": event.get("call_title", ""),
                "source_thread_ts": event.get("source_thread_ts", ""),
                "linked_at": event.get("linked_at", ""),
            }
        elif event["event"] == "unlink":
            active.pop(key, None)
    return active


def add_link(
    storage,
    project_id: str,
    obs_date: str,
    obs_entity: str,
    source_thread_ts: str,
    call_title: str,
) -> None:
    event = {
        "event": "link",
        "project_id": project_id,
        "obs_date": obs_date,
        "obs_entity": obs_entity,
        "source_thread_ts": source_thread_ts,
        "call_title": call_title,
        "linked_at": date.today().isoformat(),
    }
    storage.append_line(_KEY, json.dumps(event))


def remove_link(storage, project_id: str, obs_date: str, obs_entity: str) -> None:
    event = {
        "event": "unlink",
        "project_id": project_id,
        "obs_date": obs_date,
        "obs_entity": obs_entity,
        "unlinked_at": date.today().isoformat(),
    }
    storage.append_line(_KEY, json.dumps(event))


def get_links_for_project(storage, project_id: str) -> list:
    active = _replay(storage)
    return [v for k, v in active.items() if k[0] == project_id]


def get_projects_for_observation(storage, obs_date: str, obs_entity: str) -> list:
    active = _replay(storage)
    return [k[0] for k in active if k[1] == obs_date and k[2] == obs_entity]
