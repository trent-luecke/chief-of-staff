#!/usr/bin/env python3
"""Local entity UI server.

Serves tools/registry_ui.html and provides task + project CRUD endpoints
backed by lib/tasks.py (JSONL) and lib/projects.py.

Usage:
    python tools/server.py          # start server at http://localhost:8787
"""
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_file
import lib.tasks as tasks_lib
import lib.projects as projects_lib
from lib.storage import LocalStorage
from lib.notes import replay_notes as _replay_notes_lib

UI_PATH = Path(__file__).parent / "registry_ui.html"
DATA_DIR = ROOT / "data"
NOTES_JSONL = DATA_DIR / "notes.jsonl"
NOTES_TAGS_JSON = DATA_DIR / "notes_tags.json"

app = Flask(__name__)


def _storage():
    return LocalStorage(base_dir=str(DATA_DIR))


def _git_push_notes(detail: str) -> dict:
    """Commit notes files to the current branch."""
    files = ["data/notes.jsonl"]
    if NOTES_TAGS_JSON.exists():
        files.append("data/notes_tags.json")
    return _git_commit_push(files, f"data: {detail}")


def _sync_tasks_from_main() -> None:
    """Overwrite local tasks.jsonl with the authoritative copy from origin/main. Non-fatal."""
    subprocess.run(["git", "fetch", "origin", "main"], cwd=str(ROOT), capture_output=True)
    subprocess.run(
        ["git", "checkout", "origin/main", "--", "data/tasks.jsonl"],
        cwd=str(ROOT), capture_output=True,
    )


@app.route("/")
def index():
    _sync_tasks_from_main()
    return send_file(str(UI_PATH))


# --- Tasks ---

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    project_id = request.args.get("project_id")
    open_tasks = tasks_lib.get_open_tasks(_storage())
    if project_id:
        open_tasks = [t for t in open_tasks if t.get("project_id") == project_id]
    return jsonify(open_tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    body = request.get_json(force=True)
    if not body or not body.get("title"):
        return jsonify({"error": "title is required"}), 400
    task = tasks_lib.add_task(
        _storage(),
        title=body["title"],
        source=body.get("source", "ui"),
        due_date=body.get("due_date"),
        metadata=body.get("metadata"),
        project_id=body.get("project_id"),
        collaborators=body.get("collaborators"),
        owner=body.get("owner"),
    )
    push = _git_push_tasks(f"create task {task['id']}")
    return jsonify({"task": task, "push": push}), 201


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id: str):
    patch = request.get_json(force=True)
    result = tasks_lib.edit_task(_storage(), task_id, patch)
    if result is None:
        return jsonify({"error": "not found"}), 404
    push = _git_push_tasks(f"update task {task_id}")
    return jsonify({"task": result, "push": push})


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id: str):
    result = tasks_lib.complete_task_by_id(_storage(), task_id)
    if result is None:
        return jsonify({"error": "not found"}), 404
    push = _git_push_tasks(f"complete task {task_id}")
    return jsonify({"task": result, "push": push})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id: str):
    result = tasks_lib.delete_task_by_id(_storage(), task_id)
    if result is None:
        return jsonify({"error": "not found"}), 404
    push = _git_push_tasks(f"delete task {task_id}")
    return jsonify({"task": result, "push": push})


def _git_commit_push(files: list, msg: str) -> dict:
    """Stage files, commit with msg, and push to the current branch's tracking remote."""
    try:
        repo = str(ROOT)
        subprocess.run(["git", "add"] + files, cwd=repo, check=True, capture_output=True)
        commit = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=repo, capture_output=True, text=True,
        )
        if commit.returncode != 0:
            out = (commit.stdout + commit.stderr).strip()
            if "nothing to commit" in out:
                return {"status": "ok", "detail": "already committed"}
            return {"status": "commit_failed", "detail": out}
        push = subprocess.run(["git", "push"], cwd=repo, capture_output=True, text=True)
        if push.returncode != 0:
            return {"status": "push_failed", "detail": push.stderr.strip()}
        return {"status": "ok", "detail": "committed and pushed"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _git_push_projects(project_name: str) -> dict:
    return _git_commit_push(["data/projects_registry.json"], f"data: add project '{project_name}'")


def _git_push_tasks(detail: str) -> dict:
    """Commit tasks.jsonl directly on main via a temp worktree and push. Never touches the current branch."""
    repo = str(ROOT)
    tasks_path = ROOT / "data" / "tasks.jsonl"
    try:
        subprocess.run(["git", "fetch", "origin", "main"], cwd=repo, check=True, capture_output=True)

        # Union-merge: add any lines from origin/main not yet in local file (handles concurrent GHA writes)
        remote = subprocess.run(
            ["git", "show", "origin/main:data/tasks.jsonl"],
            cwd=repo, capture_output=True, text=True,
        )
        if remote.returncode == 0 and remote.stdout.strip():
            local_set = set(tasks_path.read_text().strip().splitlines()) if tasks_path.exists() else set()
            new_lines = [l for l in remote.stdout.strip().splitlines() if l not in local_set]
            if new_lines:
                with open(tasks_path, "a") as f:
                    for line in new_lines:
                        f.write(line + "\n")

        with tempfile.TemporaryDirectory() as tmp:
            wt = tmp + "/wt"
            subprocess.run(
                ["git", "worktree", "add", "--detach", wt, "origin/main"],
                cwd=repo, check=True, capture_output=True,
            )
            try:
                shutil.copy(str(tasks_path), wt + "/data/tasks.jsonl")
                subprocess.run(["git", "add", "data/tasks.jsonl"], cwd=wt, check=True, capture_output=True)
                commit = subprocess.run(
                    ["git", "commit", "-m", f"data: {detail}"],
                    cwd=wt, capture_output=True, text=True,
                )
                if commit.returncode != 0:
                    out = (commit.stdout + commit.stderr).strip()
                    if "nothing to commit" in out:
                        return {"status": "ok", "detail": "already committed"}
                    return {"status": "commit_failed", "detail": out}
                push = subprocess.run(
                    ["git", "push", "origin", "HEAD:refs/heads/main"],
                    cwd=wt, capture_output=True, text=True,
                )
                if push.returncode != 0:
                    return {"status": "push_failed", "detail": push.stderr.strip()}
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt],
                    cwd=repo, capture_output=True,
                )

        # Reset local index to match the just-pushed main so the working tree stays clean
        subprocess.run(
            ["git", "checkout", "origin/main", "--", "data/tasks.jsonl"],
            cwd=repo, capture_output=True,
        )
        return {"status": "ok", "detail": "committed and pushed to main"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# --- Projects ---

@app.route("/api/projects", methods=["GET"])
def list_projects():
    status = request.args.get("status", "active")
    return jsonify(projects_lib.list_projects(_storage(), status=status or None))


@app.route("/api/projects", methods=["POST"])
def create_project():
    body = request.get_json(force=True)
    if not body or not body.get("canonical_name"):
        return jsonify({"error": "canonical_name is required"}), 400
    project = projects_lib.add_project(
        _storage(),
        canonical_name=body["canonical_name"],
        aliases=body.get("aliases"),
        members=body.get("members"),
    )
    push = _git_push_projects(project["canonical_name"])
    return jsonify({"project": project, "push": push}), 201


@app.route("/api/projects/<project_id>", methods=["PATCH"])
def update_project(project_id: str):
    updates = request.get_json(force=True)
    result = projects_lib.update_project(_storage(), project_id, updates)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id: str):
    storage = _storage()
    open_tasks = tasks_lib.get_open_tasks(storage)
    proj_tasks = [t for t in open_tasks if t.get("project_id") == project_id]
    for t in proj_tasks:
        tasks_lib.delete_task_by_id(storage, t["id"])
    deleted = projects_lib.delete_project(storage, project_id)
    if not deleted:
        return jsonify({"error": "not found"}), 404
    task_push = _git_push_tasks(f"delete project {project_id} tasks") if proj_tasks else {"status": "ok", "detail": "no tasks"}
    proj_push = _git_commit_push(["data/projects_registry.json"], f"data: delete project {project_id}")
    return jsonify({"deleted": project_id, "tasks_deleted": len(proj_tasks), "push": {"tasks": task_push, "projects": proj_push}})


# --- People ---

@app.route("/api/people", methods=["GET"])
def list_people():
    registry = _storage().read_json("people_registry.json", default={"people": []})
    people = [
        {"id": p["id"], "name": p.get("canonical_name", p["id"])}
        for p in registry.get("people", [])
    ]
    return jsonify(people)


@app.route("/api/registry", methods=["GET"])
def get_registry():
    registry = _storage().read_json("people_registry.json", default={"people": []})
    return jsonify(registry)


# --- Notes ---

@app.route("/api/notes", methods=["GET"])
def list_notes():
    return jsonify(_replay_notes_lib(NOTES_JSONL))


@app.route("/api/notes", methods=["POST"])
def create_note():
    body = request.get_json(force=True)
    if not body or not body.get("body"):
        return jsonify({"error": "body is required"}), 400
    note_id = "n-" + secrets.token_hex(3)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ev = {
        "event": "create",
        "id": note_id,
        "ts": ts,
        "body": body["body"],
        "tags": body.get("tags", []),
        "person_id": body.get("person_id"),
        "task_id": body.get("task_id"),
        "brief": body.get("brief", False),
        "pinned": body.get("pinned", False),
    }
    with open(NOTES_JSONL, "a") as f:
        f.write(json.dumps(ev) + "\n")
    push = _git_push_notes(f"create note {note_id}")
    note_out = {**ev, "brief_flagged_date": ts[:10] if ev["brief"] else None}
    return jsonify({"note": note_out, "push": push}), 201


@app.route("/api/notes/<note_id>", methods=["PATCH"])
def patch_note(note_id: str):
    body = request.get_json(force=True)
    notes = _replay_notes_lib(NOTES_JSONL)
    if not any(n["id"] == note_id for n in notes):
        return jsonify({"error": "not found"}), 404
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    event_type = body.pop("event_type", "update")
    if event_type == "pin":
        ev = {"event": "pin", "id": note_id, "ts": ts, "pinned": body.get("pinned", True)}
    else:
        ev = {
            "event": "update", "id": note_id, "ts": ts,
            **{k: v for k, v in body.items() if k not in ("event", "id", "ts")},
        }
    with open(NOTES_JSONL, "a") as f:
        f.write(json.dumps(ev) + "\n")
    push = _git_push_notes(f"update note {note_id}")
    updated = next(n for n in _replay_notes_lib(NOTES_JSONL) if n["id"] == note_id)
    return jsonify({"note": updated, "push": push})


@app.route("/api/notes/<note_id>", methods=["DELETE"])
def delete_note(note_id: str):
    notes = _replay_notes_lib(NOTES_JSONL)
    if not any(n["id"] == note_id for n in notes):
        return jsonify({"error": "not found"}), 404
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ev = {"event": "delete", "id": note_id, "ts": ts}
    with open(NOTES_JSONL, "a") as f:
        f.write(json.dumps(ev) + "\n")
    push = _git_push_notes(f"delete note {note_id}")
    return jsonify({"deleted": note_id, "push": push})


# --- Notes Tags ---

@app.route("/api/notes/tags", methods=["GET"])
def list_note_tags():
    if not NOTES_TAGS_JSON.exists():
        NOTES_TAGS_JSON.write_text(json.dumps([]))
    return jsonify(json.loads(NOTES_TAGS_JSON.read_text()))


@app.route("/api/notes/tags", methods=["POST"])
def create_note_tag():
    body = request.get_json(force=True)
    if not body or not body.get("id"):
        return jsonify({"error": "id is required"}), 400
    tag_id = body["id"].upper().replace(" ", "_")
    tags = json.loads(NOTES_TAGS_JSON.read_text()) if NOTES_TAGS_JSON.exists() else []
    if any(t["id"] == tag_id for t in tags):
        return jsonify({"error": "tag already exists"}), 409
    tag = {"id": tag_id, "color": body.get("color", "#555555")}
    tags.append(tag)
    NOTES_TAGS_JSON.write_text(json.dumps(tags, indent=2))
    _git_commit_push(["data/notes_tags.json"], f"data: create tag {tag_id}")
    return jsonify({"tag": tag}), 201


@app.route("/api/notes/tags/<tag_id>", methods=["PATCH"])
def update_note_tag(tag_id: str):
    body = request.get_json(force=True)
    tags = json.loads(NOTES_TAGS_JSON.read_text()) if NOTES_TAGS_JSON.exists() else []
    tag = next((t for t in tags if t["id"] == tag_id), None)
    if tag is None:
        return jsonify({"error": "not found"}), 404
    new_id = body.get("id", tag_id).upper().replace(" ", "_")
    new_color = body.get("color", tag.get("color", "#555555"))
    for t in tags:
        if t["id"] == tag_id:
            t["id"] = new_id
            t["color"] = new_color
    NOTES_TAGS_JSON.write_text(json.dumps(tags, indent=2))
    commit_files = ["data/notes_tags.json"]
    if new_id != tag_id and NOTES_JSONL.exists():
        affected = [n for n in _replay_notes_lib(NOTES_JSONL) if tag_id in n.get("tags", [])]
        if affected:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            with open(NOTES_JSONL, "a") as f:
                for note in affected:
                    new_tags = [new_id if t == tag_id else t for t in note["tags"]]
                    f.write(json.dumps({"event": "update", "id": note["id"], "ts": ts, "tags": new_tags}) + "\n")
            commit_files.append("data/notes.jsonl")
    _git_commit_push(commit_files, f"data: rename tag {tag_id} -> {new_id}")
    return jsonify({"tag": {"id": new_id, "color": new_color}})


@app.route("/api/notes/tags/<tag_id>", methods=["DELETE"])
def delete_note_tag(tag_id: str):
    tags = json.loads(NOTES_TAGS_JSON.read_text()) if NOTES_TAGS_JSON.exists() else []
    new_tags = [t for t in tags if t["id"] != tag_id]
    if len(new_tags) == len(tags):
        return jsonify({"error": "not found"}), 404
    NOTES_TAGS_JSON.write_text(json.dumps(new_tags, indent=2))
    _git_commit_push(["data/notes_tags.json"], f"data: delete tag {tag_id}")
    return jsonify({"deleted": tag_id})


if __name__ == "__main__":
    print("Entity UI → http://localhost:8787")
    app.run(port=8787, debug=False)
