#!/usr/bin/env python3
"""Local entity UI server.

Serves tools/registry_ui.html and provides task + project CRUD endpoints
backed by lib/tasks.py (JSONL) and lib/projects.py.

Usage:
    python tools/server.py          # start server at http://localhost:8787
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_file
import lib.tasks as tasks_lib
import lib.projects as projects_lib
from lib.storage import LocalStorage

UI_PATH = Path(__file__).parent / "registry_ui.html"
DATA_DIR = ROOT / "data"

app = Flask(__name__)


def _storage():
    return LocalStorage(base_dir=str(DATA_DIR))


@app.route("/")
def index():
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
    )
    return jsonify(task), 201


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id: str):
    patch = request.get_json(force=True)
    result = tasks_lib.edit_task(_storage(), task_id, patch)
    if result is None:
        return jsonify({"error": "not found"}), 404
    push = _git_push_tasks(f"update task {task_id}")
    if push["status"] != "ok":
        return jsonify({"error": f"git push failed: {push['detail']}"}), 500
    return jsonify(result)


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id: str):
    result = tasks_lib.complete_task_by_id(_storage(), task_id)
    if result is None:
        return jsonify({"error": "not found"}), 404
    push = _git_push_tasks(f"complete task {task_id}")
    if push["status"] != "ok":
        return jsonify({"error": f"git push failed: {push['detail']}"}), 500
    return jsonify(result)


def _git_push_projects(project_name: str) -> dict:
    """Stage, commit, and push projects_registry.json. Non-fatal — project creation succeeds regardless."""
    try:
        repo = str(ROOT)
        subprocess.run(
            ["git", "add", "data/projects_registry.json"],
            cwd=repo, check=True, capture_output=True,
        )
        commit = subprocess.run(
            ["git", "commit", "-m", f"data: add project '{project_name}'"],
            cwd=repo, capture_output=True, text=True,
        )
        if commit.returncode != 0:
            out = (commit.stdout + commit.stderr).strip()
            if "nothing to commit" in out:
                return {"status": "ok", "detail": "already committed"}
            return {"status": "commit_failed", "detail": out}
        push = subprocess.run(
            ["git", "push"],
            cwd=repo, capture_output=True, text=True,
        )
        if push.returncode != 0:
            return {"status": "push_failed", "detail": push.stderr.strip()}
        return {"status": "ok", "detail": "committed and pushed"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _git_push_tasks(detail: str) -> dict:
    """Stage, commit, and push tasks.jsonl. Returns status dict."""
    try:
        repo = str(ROOT)
        subprocess.run(
            ["git", "add", "data/tasks.jsonl"],
            cwd=repo, check=True, capture_output=True,
        )
        commit = subprocess.run(
            ["git", "commit", "-m", f"data: {detail}"],
            cwd=repo, capture_output=True, text=True,
        )
        if commit.returncode != 0:
            out = (commit.stdout + commit.stderr).strip()
            if "nothing to commit" in out:
                return {"status": "ok", "detail": "already committed"}
            return {"status": "commit_failed", "detail": out}
        push = subprocess.run(
            ["git", "push"],
            cwd=repo, capture_output=True, text=True,
        )
        if push.returncode != 0:
            return {"status": "push_failed", "detail": push.stderr.strip()}
        return {"status": "ok", "detail": "committed and pushed"}
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


if __name__ == "__main__":
    print("Entity UI → http://localhost:8787")
    app.run(port=8787, debug=False)
