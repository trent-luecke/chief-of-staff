# tests/test_server_data_layer.py
import json
import pytest
import tools.server as server


@pytest.fixture(autouse=True)
def _reset_snapshot():
    saved = server.SNAPSHOT
    server.SNAPSHOT = server._Snapshot()
    yield
    server.SNAPSHOT = saved


@pytest.fixture
def client(monkeypatch):
    # In-memory fake of origin/main: {repo_rel_path: content}
    main = {
        "data/tasks.jsonl": "",
        "data/projects_registry.json": json.dumps({"version": 1, "projects": []}),
        "data/people_registry.json": json.dumps({"people": [{"id": "trent-luecke", "canonical_name": "Trent Luecke"}]}),
        "data/notes.jsonl": "",
        "data/notes_tags.json": "[]",
    }
    committed = []

    monkeypatch.setattr(server.git_sync, "fetch_main", lambda *a, **k: True)
    monkeypatch.setattr(server.git_sync, "show_main", lambda rel: main.get(rel))

    def fake_commit(files, msg):
        # apply union-merge for jsonl, overwrite otherwise — mirrors real behavior
        for rel, content in files.items():
            if rel.endswith(".jsonl"):
                existing = main.get(rel, "")
                seen = set(l for l in existing.splitlines() if l.strip())
                merged = [l for l in existing.splitlines() if l.strip()]
                merged += [l for l in content.splitlines() if l.strip() and l not in seen]
                main[rel] = "\n".join(merged) + ("\n" if merged else "")
            else:
                main[rel] = content
        committed.append(msg)
        return {"status": "ok", "detail": "committed and pushed to main"}

    monkeypatch.setattr(server.git_sync, "commit_files_to_main", fake_commit)
    server.rebuild_snapshot()
    c = server.app.test_client()
    c._main = main
    c._committed = committed
    return c


def test_bootstrap_reports_online_and_people(client):
    r = client.get("/api/bootstrap")
    body = r.get_json()
    assert body["online"] is True
    assert body["people"] == [{"id": "trent-luecke", "name": "Trent Luecke"}]


def test_create_task_commits_to_main_and_appears(client):
    r = client.post("/api/tasks", json={"title": "Ship it", "owner": "trent-luecke"})
    assert r.status_code == 201
    assert "Ship it" in client._main["data/tasks.jsonl"]
    # snapshot rebuilt → GET reflects it
    tasks = client.get("/api/tasks").get_json()
    assert any(t["title"] == "Ship it" for t in tasks)


def test_create_task_offline_returns_503_no_commit(client, monkeypatch):
    monkeypatch.setattr(server.git_sync, "fetch_main", lambda *a, **k: False)
    before = client._main["data/tasks.jsonl"]
    r = client.post("/api/tasks", json={"title": "nope"})
    assert r.status_code == 503
    assert client._main["data/tasks.jsonl"] == before  # nothing committed


def test_delete_project_cascades_tasks_in_one_commit(client):
    client.post("/api/projects", json={"canonical_name": "Temp Proj"})
    pid = client.get("/api/projects").get_json()[0]["id"]
    client.post("/api/tasks", json={"title": "child", "project_id": pid})
    n_commits_before = len(client._committed)
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    assert r.get_json()["tasks_deleted"] == 1
    # exactly one new commit covered both the task deletion and the project removal
    assert len(client._committed) == n_commits_before + 1


def test_create_note_and_list(client):
    client.post("/api/notes", json={"body": "remember this", "tags": []})
    notes = client.get("/api/notes").get_json()
    assert any(n["body"] == "remember this" for n in notes)


def test_create_task_push_failure_returns_502(client, monkeypatch):
    # fetch_main succeeds (online) but the commit/push to main fails
    monkeypatch.setattr(server.git_sync, "commit_files_to_main",
                        lambda files, msg: {"status": "push_failed", "detail": "remote rejected"})
    r = client.post("/api/tasks", json={"title": "doomed"})
    assert r.status_code == 502
    body = r.get_json()
    assert body["push"]["status"] == "push_failed"


def test_commit_offline_returns_503(client, monkeypatch):
    # fetch_main passes the up-front check, but commit's own fetch times out → offline
    monkeypatch.setattr(server.git_sync, "commit_files_to_main",
                        lambda files, msg: {"status": "offline", "detail": "git fetch timed out"})
    r = client.post("/api/tasks", json={"title": "late"})
    assert r.status_code == 503
