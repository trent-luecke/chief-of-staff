#!/usr/bin/env python3
"""Local entity UI server.

Serves tools/registry_ui.html and provides task + project CRUD endpoints
backed by lib/tasks.py (JSONL) and lib/projects.py.

Usage:
    python tools/server.py          # start server at http://localhost:8787
"""
import json
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
    SNAPSHOT.online = online
    SNAPSHOT.fetched_at = datetime.now(timezone.utc).isoformat()


def _write_main(mutate, msg_fn):
    """Apply mutate(store) against origin/main and commit the result.

    Returns (result, push, http_status). When main is unreachable, returns
    (None, {"status":"offline"}, 503) WITHOUT attempting any commit.
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


def _people_list():
    return [
        {"id": p["id"], "name": p.get("canonical_name", p["id"])}
        for p in SNAPSHOT.people.get("people", [])
    ]


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
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    return jsonify({"task": task, "push": push}), 201


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id: str):
    patch = request.get_json(force=True)
    task, push, status = _write_main(
        lambda store: tasks_lib.edit_task(store, task_id, patch),
        f"data: update task {task_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": task, "push": push})


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id: str):
    task, push, status = _write_main(
        lambda store: tasks_lib.complete_task_by_id(store, task_id),
        f"data: complete task {task_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": task, "push": push})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id: str):
    task, push, status = _write_main(
        lambda store: tasks_lib.delete_task_by_id(store, task_id),
        f"data: delete task {task_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
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
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    return jsonify({"project": project, "push": push}), 201


@app.route("/api/projects/<project_id>", methods=["PATCH"])
def update_project(project_id: str):
    updates = request.get_json(force=True)
    project, push, status = _write_main(
        lambda store: projects_lib.update_project(store, project_id, updates),
        f"data: update project {project_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
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
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
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
        "brief": body.get("brief", False), "pinned": body.get("pinned", False),
    }
    _, push, status = _write_main(
        lambda store: store.append_line("notes.jsonl", json.dumps(ev)),
        f"data: create note {note_id}",
    )
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
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
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
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
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
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
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
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
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
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
    if status == 503:
        return jsonify({"error": "offline", "push": push}), 503
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": tag_id, "push": push})


if __name__ == "__main__":
    git_sync.prune_worktrees()
    rebuild_snapshot()
    print("Entity UI → http://localhost:8787")
    app.run(port=8787, debug=False, threaded=True)
