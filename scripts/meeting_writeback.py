"""Orchestrate approved internal-meeting items into the Registry via HTTP.

The Registry server (tools/server.py, default http://localhost:8787) commits
every write to origin/main, so this must run against a RUNNING server. This
module contains NO parsing judgment — it just maps an approved-items payload
to endpoint calls. See docs/superpowers/plans/2026-07-23-parse-internal-meeting.md
for the payload schema.
"""
from __future__ import annotations

import json
import sys

import requests

MEETING_NOTES_TAG = "MEETING_NOTES"
TIMEOUT = 30


def _post(base_url: str, path: str, body: dict) -> dict:
    resp = requests.post(f"{base_url}{path}", json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def write_back(payload: dict, base_url: str = "http://localhost:8787") -> dict:
    created: list[str] = []
    errors: list[str] = []
    mtg = payload["meeting"]
    date = mtg.get("date")

    try:
        if mtg["kind"] == "oneoff":
            _oneoff(base_url, payload, mtg, date, created)
        else:
            _recurring(base_url, payload, mtg, date, created)
        for text in payload.get("decisions", []):
            out = _post(base_url, "/api/decisions", {"text": text, "date": date})
            created.append(f"decision: {out['decision']}")
    except requests.RequestException as e:
        errors.append(str(e))

    return {"created": created, "errors": errors}


def _source(mtg: dict) -> str:
    return f"meeting-{mtg.get('name', 'internal')}-{mtg.get('date', '')}"


def _oneoff(base_url, payload, mtg, date, created):
    body = f"# {mtg.get('name', 'Meeting')} — {date}\n\n{payload.get('summary', '')}"
    note = _post(base_url, "/api/notes", {"body": body, "tags": [MEETING_NOTES_TAG]})
    created.append(f"note {note['note']['id']} (MEETING_NOTES)")
    for bucket in ("commitments", "owed_to_me", "team_tasks"):
        for item in payload.get(bucket, []):
            task = _post(base_url, "/api/tasks", {
                "title": item["text"], "owner": item.get("owner"),
                "source": _source(mtg),
            })
            created.append(f"task {task['task']['id']} ({bucket}, owner={item.get('owner')})")


def _recurring(base_url, payload, mtg, date, created):
    meeting_id = mtg.get("meeting_id")
    if not meeting_id:
        made = _post(base_url, "/api/meetings", {
            "name": mtg["name"], "people_ids": mtg.get("people_ids", []),
            "calendar_pattern": "",
        })
        meeting_id = made["id"]
        created.append(f"meeting series {meeting_id}")

    _post(base_url, f"/api/meetings/{meeting_id}/sessions",
          {"date": date, "body": payload.get("summary", "")})
    created.append(f"session on {meeting_id} ({date})")

    # commitments: thread owned by Trent, then promoted to a task
    for item in payload.get("commitments", []):
        doc = _post(base_url, f"/api/meetings/{meeting_id}/threads",
                    {"text": item["text"], "person_id": item.get("owner")})
        thread_id = doc["meeting"]["threads"][-1]["thread_id"]
        _post(base_url, f"/api/meetings/{meeting_id}/threads/{thread_id}/promote", {})
        created.append(f"thread {thread_id} + task (commitment)")

    # owed-to-me and team tasks: stay as threads (person_id = owner)
    for bucket in ("owed_to_me", "team_tasks"):
        for item in payload.get(bucket, []):
            doc = _post(base_url, f"/api/meetings/{meeting_id}/threads",
                        {"text": item["text"], "person_id": item.get("owner")})
            thread_id = doc["meeting"]["threads"][-1]["thread_id"]
            created.append(f"thread {thread_id} ({bucket})")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m scripts.meeting_writeback <payload.json> [base_url]", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        payload = json.load(f)
    base_url = argv[1] if len(argv) > 1 else "http://localhost:8787"
    summary = write_back(payload, base_url=base_url)
    print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
