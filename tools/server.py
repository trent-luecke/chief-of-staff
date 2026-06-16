#!/usr/bin/env python3
"""Local entity UI server.

Serves tools/registry_ui.html and provides task + project CRUD endpoints
backed by lib/tasks.py (JSONL) and lib/projects.py.

Usage:
    python tools/server.py          # start server at http://localhost:8787
"""
import json
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_file
import lib.tasks as tasks_lib
import lib.projects as projects_lib
import lib.git_sync as git_sync
from lib.main_storage import MainStorage
from lib.notes import replay_notes_content
import lib.meetings as meetings_lib

UI_PATH = Path(__file__).parent / "registry_ui.html"

app = Flask(__name__)


# --- Snapshot of origin/main (the single source of truth) ---

class _Snapshot:
    def __init__(self):
        self.online = False
        self.fetched_at = None
        self.tasks = []
        self.projects = []
        self.people = {"people": []}
        self.notes = []
        self.tags = []
        self.meetings = {}        # slug -> replayed doc state
        self.meeting_index = []   # list of config dicts from meeting_index.json


SNAPSHOT = _Snapshot()


def _read_store() -> MainStorage:
    """A MainStorage that reads from origin/main (current local ref)."""
    return MainStorage(read_blob=git_sync.show_main)


def rebuild_snapshot(known_online=None) -> None:
    """Re-read every dataset from origin/main into SNAPSHOT.

    If known_online is None, fetch origin/main first (the fetch result is the
    connectivity signal). Pass True to skip the fetch (e.g. right after a write
    that already updated the ref).
    """
    online = git_sync.fetch_main() if known_online is None else known_online
    store = _read_store()
    SNAPSHOT.tasks = tasks_lib.get_open_tasks(store)
    SNAPSHOT.projects = projects_lib.list_projects(store, status=None)
    SNAPSHOT.people = store.read_json("people_registry.json", default={"people": []})
    SNAPSHOT.notes = replay_notes_content(store.read("notes.jsonl") or "")
    SNAPSHOT.tags = store.read_json("notes_tags.json", default=[])
    SNAPSHOT.meetings = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
    SNAPSHOT.meeting_index = store.read_json("meeting_index.json", default={"meetings": []}).get("meetings", [])
    SNAPSHOT.online = online
    SNAPSHOT.fetched_at = datetime.now(timezone.utc).isoformat()


def _write_main(mutate, msg_fn):
    """Apply mutate(store) against origin/main and commit the result.

    Returns (result, push, http_status):
    - 200 when the commit/push to main succeeded (snapshot is rebuilt).
    - 503 when main is unreachable: either the up-front fetch fails (no commit
      attempted, result is None) or the commit's own fetch times out (offline).
    - 502 when the commit or push to main failed for any other reason; the write
      did NOT land on main, so the client must not treat it as success.
    msg_fn is a commit message string, or a callable taking the mutate result.
    """
    if not git_sync.fetch_main():
        return None, {"status": "offline", "detail": "cannot reach main"}, 503
    store = _read_store()
    result = mutate(store)
    msg = msg_fn(result) if callable(msg_fn) else msg_fn
    push = git_sync.commit_files_to_main(store.dirty(), msg)
    if push.get("status") == "ok":
        rebuild_snapshot(known_online=True)
        return result, push, 200
    if push.get("status") == "offline":
        return result, push, 503
    return result, push, 502


def _people_list():
    return [
        {"id": p["id"], "name": p.get("canonical_name", p["id"])}
        for p in SNAPSHOT.people.get("people", [])
    ]


def _meeting_id(entry: dict) -> str:
    return entry["memory_file"].rsplit("/", 1)[-1].removesuffix(".md")


def _meetings_list():
    """Join config (meeting_index) with replayed doc state, keyed by slug."""
    out = []
    for entry in SNAPSHOT.meeting_index:
        mid = _meeting_id(entry)
        doc = SNAPSHOT.meetings.get(mid, {"id": mid, "agenda": [], "threads": [], "sessions": []})
        out.append({
            "id": mid,
            "name": entry.get("name") or mid.replace("_", " ").title(),
            "calendar_pattern": entry.get("calendar_pattern", ""),
            "people_ids": entry.get("people_ids", []),
            "nudge_subject": entry.get("nudge_subject", ""),
            "nudge_minutes_after": entry.get("nudge_minutes_after", 5),
            "agenda": doc["agenda"],
            "threads": doc["threads"],
            "sessions": doc["sessions"],
        })
    return out


@app.route("/")
def index():
    return send_file(str(UI_PATH))


@app.route("/api/bootstrap", methods=["GET"])
@app.route("/api/refresh", methods=["POST"])
def bootstrap():
    rebuild_snapshot()
    return jsonify({
        "online": SNAPSHOT.online,
        "fetched_at": SNAPSHOT.fetched_at,
        "tasks": SNAPSHOT.tasks,
        "projects": SNAPSHOT.projects,
        "people": _people_list(),
        "notes": SNAPSHOT.notes,
        "tags": SNAPSHOT.tags,
        "meetings": _meetings_list(),
    })


# --- Tasks ---

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    project_id = request.args.get("project_id")
    tasks = SNAPSHOT.tasks
    if project_id:
        tasks = [t for t in tasks if t.get("project_id") == project_id]
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    body = request.get_json(force=True)
    if not body or not body.get("title"):
        return jsonify({"error": "title is required"}), 400

    def mutate(store):
        return tasks_lib.add_task(
            store,
            title=body["title"],
            source=body.get("source", "ui"),
            due_date=body.get("due_date"),
            metadata=body.get("metadata"),
            project_id=body.get("project_id"),
            collaborators=body.get("collaborators"),
            owner=body.get("owner"),
        )

    task, push, status = _write_main(mutate, lambda t: f"data: create task {t['id']}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    return jsonify({"task": task, "push": push}), 201


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id: str):
    patch = request.get_json(force=True)
    task, push, status = _write_main(
        lambda store: tasks_lib.edit_task(store, task_id, patch),
        f"data: update task {task_id}",
    )
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": task, "push": push})


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id: str):
    task, push, status = _write_main(
        lambda store: tasks_lib.complete_task_by_id(store, task_id),
        f"data: complete task {task_id}",
    )
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": task, "push": push})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id: str):
    task, push, status = _write_main(
        lambda store: tasks_lib.delete_task_by_id(store, task_id),
        f"data: delete task {task_id}",
    )
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": task, "push": push})


# --- Projects ---

@app.route("/api/projects", methods=["GET"])
def list_projects():
    status = request.args.get("status", "active")
    projects = SNAPSHOT.projects
    if status:
        projects = [p for p in projects if p.get("status") == status]
    return jsonify(projects)


@app.route("/api/projects", methods=["POST"])
def create_project():
    body = request.get_json(force=True)
    if not body or not body.get("canonical_name"):
        return jsonify({"error": "canonical_name is required"}), 400

    def mutate(store):
        return projects_lib.add_project(
            store,
            canonical_name=body["canonical_name"],
            aliases=body.get("aliases"),
            members=body.get("members"),
        )

    project, push, status = _write_main(mutate, lambda p: f"data: add project '{p['canonical_name']}'")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    return jsonify({"project": project, "push": push}), 201


@app.route("/api/projects/<project_id>", methods=["PATCH"])
def update_project(project_id: str):
    updates = request.get_json(force=True)
    project, push, status = _write_main(
        lambda store: projects_lib.update_project(store, project_id, updates),
        f"data: update project {project_id}",
    )
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if project is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(project)


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id: str):
    def mutate(store):
        open_tasks = tasks_lib.get_open_tasks(store)
        proj_tasks = [t for t in open_tasks if t.get("project_id") == project_id]
        for t in proj_tasks:
            tasks_lib.delete_task_by_id(store, t["id"])
        deleted = projects_lib.delete_project(store, project_id)
        if not deleted:
            return None
        return {"project_id": project_id, "tasks_deleted": len(proj_tasks)}

    result, push, status = _write_main(mutate, f"data: delete project {project_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": project_id, "tasks_deleted": result["tasks_deleted"], "push": push})


# --- People ---

@app.route("/api/people", methods=["GET"])
def list_people():
    return jsonify(_people_list())


@app.route("/api/registry", methods=["GET"])
def get_registry():
    return jsonify(SNAPSHOT.people)


# --- Notes ---

@app.route("/api/notes", methods=["GET"])
def list_notes():
    return jsonify(SNAPSHOT.notes)


@app.route("/api/notes", methods=["POST"])
def create_note():
    body = request.get_json(force=True)
    if not body or not body.get("body"):
        return jsonify({"error": "body is required"}), 400
    note_id = "n-" + secrets.token_hex(3)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ev = {
        "event": "create", "id": note_id, "ts": ts,
        "body": body["body"], "tags": body.get("tags", []),
        "person_id": body.get("person_id"), "task_id": body.get("task_id"),
        "project_id": body.get("project_id"),
        "brief": body.get("brief", False), "pinned": body.get("pinned", False),
    }
    _, push, status = _write_main(
        lambda store: store.append_line("notes.jsonl", json.dumps(ev)),
        f"data: create note {note_id}",
    )
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    note_out = {**ev, "brief_flagged_date": ts[:10] if ev["brief"] else None}
    return jsonify({"note": note_out, "push": push}), 201


@app.route("/api/notes/<note_id>", methods=["PATCH"])
def patch_note(note_id: str):
    body = request.get_json(force=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    event_type = body.pop("event_type", "update")
    if event_type == "pin":
        ev = {"event": "pin", "id": note_id, "ts": ts, "pinned": body.get("pinned", True)}
    else:
        ev = {"event": "update", "id": note_id, "ts": ts,
              **{k: v for k, v in body.items() if k not in ("event", "id", "ts")}}

    def mutate(store):
        notes = replay_notes_content(store.read("notes.jsonl") or "")
        if not any(n["id"] == note_id for n in notes):
            return None
        store.append_line("notes.jsonl", json.dumps(ev))
        updated = replay_notes_content(store.read("notes.jsonl"))
        return next(n for n in updated if n["id"] == note_id)

    note, push, status = _write_main(mutate, f"data: update note {note_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if note is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"note": note, "push": push})


@app.route("/api/notes/<note_id>", methods=["DELETE"])
def delete_note(note_id: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def mutate(store):
        notes = replay_notes_content(store.read("notes.jsonl") or "")
        if not any(n["id"] == note_id for n in notes):
            return None
        store.append_line("notes.jsonl", json.dumps({"event": "delete", "id": note_id, "ts": ts}))
        return note_id

    result, push, status = _write_main(mutate, f"data: delete note {note_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": note_id, "push": push})


# --- Notes Tags ---

@app.route("/api/notes/tags", methods=["GET"])
def list_note_tags():
    return jsonify(SNAPSHOT.tags)


@app.route("/api/notes/tags", methods=["POST"])
def create_note_tag():
    body = request.get_json(force=True)
    if not body or not body.get("id"):
        return jsonify({"error": "id is required"}), 400
    tag_id = body["id"].upper().replace(" ", "_")
    tag = {"id": tag_id, "color": body.get("color", "#555555")}

    def mutate(store):
        tags = store.read_json("notes_tags.json", default=[])
        if any(t["id"] == tag_id for t in tags):
            return "exists"
        tags.append(tag)
        store.write_json("notes_tags.json", tags)
        return tag

    result, push, status = _write_main(mutate, f"data: create tag {tag_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result == "exists":
        return jsonify({"error": "tag already exists"}), 409
    return jsonify({"tag": result}), 201


@app.route("/api/notes/tags/<tag_id>", methods=["PATCH"])
def update_note_tag(tag_id: str):
    body = request.get_json(force=True)
    new_id = body.get("id", tag_id).upper().replace(" ", "_")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def mutate(store):
        tags = store.read_json("notes_tags.json", default=[])
        tag = next((t for t in tags if t["id"] == tag_id), None)
        if tag is None:
            return None
        new_color = body.get("color", tag.get("color", "#555555"))
        for t in tags:
            if t["id"] == tag_id:
                t["id"] = new_id
                t["color"] = new_color
        store.write_json("notes_tags.json", tags)
        if new_id != tag_id:
            affected = [n for n in replay_notes_content(store.read("notes.jsonl") or "")
                        if tag_id in n.get("tags", [])]
            for note in affected:
                new_tags = [new_id if x == tag_id else x for x in note["tags"]]
                store.append_line("notes.jsonl", json.dumps(
                    {"event": "update", "id": note["id"], "ts": ts, "tags": new_tags}))
        return {"id": new_id, "color": new_color}

    result, push, status = _write_main(mutate, f"data: rename tag {tag_id} -> {new_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"tag": result})


@app.route("/api/notes/tags/<tag_id>", methods=["DELETE"])
def delete_note_tag(tag_id: str):
    def mutate(store):
        tags = store.read_json("notes_tags.json", default=[])
        new_tags = [t for t in tags if t["id"] != tag_id]
        if len(new_tags) == len(tags):
            return None
        store.write_json("notes_tags.json", new_tags)
        return tag_id

    result, push, status = _write_main(mutate, f"data: delete tag {tag_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": tag_id, "push": push})


# --- Meetings ---

@app.route("/api/meetings", methods=["GET"])
def list_meetings():
    return jsonify(_meetings_list())


@app.route("/api/meetings/<meeting_id>", methods=["GET"])
def get_meeting(meeting_id: str):
    for mtg in _meetings_list():
        if mtg["id"] == meeting_id:
            return jsonify(mtg)
    return jsonify({"error": "not found"}), 404


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "meeting"


@app.route("/api/meetings", methods=["POST"])
def create_meeting():
    body = request.get_json(force=True)
    if not body or not body.get("name"):
        return jsonify({"error": "name is required"}), 400
    name = body["name"]

    def mutate(store):
        existing = store.read_json("meeting_index.json", default={"meetings": []})
        slugs = {_meeting_id(e) for e in existing["meetings"]}
        slug = _slugify(name)
        candidate, i = slug, 2
        while candidate in slugs:
            candidate, i = f"{slug}_{i}", i + 1
        slug = candidate
        entry = {
            "calendar_pattern": body.get("calendar_pattern", ""),
            "memory_file": f"data/meeting_memory/{slug}.md",
            "nudge_subject": body.get("nudge_subject", f"{name} notes?"),
            "nudge_minutes_after": body.get("nudge_minutes_after", 5),
            "name": name,
            "people_ids": body.get("people_ids", []),
        }
        existing["meetings"].append(entry)
        store.write_json("meeting_index.json", existing)
        meetings_lib.append_create(store, slug)
        return slug

    slug, push, status = _write_main(mutate, lambda s: f"data: create meeting {s}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    return jsonify({"id": slug, "push": push}), 201


@app.route("/api/meetings/<meeting_id>", methods=["PATCH"])
def update_meeting(meeting_id: str):
    body = request.get_json(force=True)

    def mutate(store):
        idx = store.read_json("meeting_index.json", default={"meetings": []})
        entry = next((e for e in idx["meetings"] if _meeting_id(e) == meeting_id), None)
        if entry is None:
            return None
        for k in ("name", "calendar_pattern", "people_ids", "nudge_subject", "nudge_minutes_after"):
            if k in body:
                entry[k] = body[k]
        store.write_json("meeting_index.json", idx)
        return entry

    result, push, status = _write_main(mutate, f"data: update meeting {meeting_id} config")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


def _meeting_exists(store, meeting_id: str) -> bool:
    idx = store.read_json("meeting_index.json", default={"meetings": []})
    return any(_meeting_id(e) == meeting_id for e in idx["meetings"])


def _meeting_doc_after_write(store, meeting_id: str) -> dict:
    state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
    return state.get(meeting_id, {"id": meeting_id, "agenda": [], "threads": [], "sessions": []})


@app.route("/api/meetings/<meeting_id>/agenda", methods=["PUT"])
def set_meeting_agenda(meeting_id: str):
    body = request.get_json(force=True)
    items = body.get("items", [])
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400

    def mutate(store):
        if not _meeting_exists(store, meeting_id):
            return None
        meetings_lib.append_set_agenda(store, meeting_id, items)
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: set agenda {meeting_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/sessions", methods=["POST"])
def add_meeting_session(meeting_id: str):
    body = request.get_json(force=True)
    if not body or not body.get("body"):
        return jsonify({"error": "body is required"}), 400
    session_date = body.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def mutate(store):
        if not _meeting_exists(store, meeting_id):
            return None
        meetings_lib.append_add_session(store, meeting_id, session_date, body["body"])
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: add session {meeting_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/threads", methods=["POST"])
def add_meeting_thread(meeting_id: str):
    body = request.get_json(force=True)
    if not body or not body.get("text"):
        return jsonify({"error": "text is required"}), 400

    def mutate(store):
        if not _meeting_exists(store, meeting_id):
            return None
        meetings_lib.append_add_thread(store, meeting_id, body["text"], person_id=body.get("person_id"))
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: add thread {meeting_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/threads/<thread_id>", methods=["PATCH"])
def patch_meeting_thread(meeting_id: str, thread_id: str):
    body = request.get_json(force=True)
    patch = {k: v for k, v in body.items() if k in ("text", "person_id", "task_id", "closed")}
    # auto-stamp closed_date when closing
    if patch.get("closed") is True and "closed_date" not in patch:
        patch["closed_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if patch.get("closed") is False:
        patch["closed_date"] = None

    def mutate(store):
        state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
        mtg = state.get(meeting_id)
        if not mtg or not any(t["thread_id"] == thread_id for t in mtg["threads"]):
            return None
        meetings_lib.append_update_thread(store, meeting_id, thread_id, **patch)
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: update thread {thread_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/threads/<thread_id>", methods=["DELETE"])
def delete_meeting_thread(meeting_id: str, thread_id: str):
    def mutate(store):
        state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
        mtg = state.get(meeting_id)
        if not mtg or not any(t["thread_id"] == thread_id for t in mtg["threads"]):
            return None
        meetings_lib.append_delete_thread(store, meeting_id, thread_id)
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: delete thread {thread_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/threads/<thread_id>/promote", methods=["POST"])
def promote_thread_to_task(meeting_id: str, thread_id: str):
    body = request.get_json(force=True) or {}

    def mutate(store):
        state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
        mtg = state.get(meeting_id)
        thread = next((t for t in (mtg["threads"] if mtg else []) if t["thread_id"] == thread_id), None)
        if thread is None:
            return None
        task = tasks_lib.add_task(
            store,
            title=thread["text"],
            source=f"meeting-{meeting_id}",
            due_date=body.get("due_date"),
            owner=thread.get("person_id"),
            metadata={"meeting_id": meeting_id, "thread_id": thread_id},
        )
        meetings_lib.append_update_thread(store, meeting_id, thread_id, task_id=task["id"])
        return {"task": task, "meeting": _meeting_doc_after_write(store, meeting_id)}

    result, push, status = _write_main(mutate, lambda r: f"data: promote thread {thread_id} -> task {r['task']['id']}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": result["task"], "meeting": result["meeting"], "push": push}), 201


if __name__ == "__main__":
    git_sync.prune_worktrees()
    rebuild_snapshot()
    print("Entity UI → http://localhost:8787")
    app.run(port=8787, debug=False, threaded=True)
