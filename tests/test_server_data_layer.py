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
        "data/routines.json": json.dumps({"version": 1, "routines": []}),
    }
    committed = []

    monkeypatch.setattr(server.git_sync, "fetch_main", lambda *a, **k: True)
    monkeypatch.setattr(server.git_sync, "show_main", lambda rel: main.get(rel))

    def fake_commit(files, msg):
        # apply union-merge for jsonl, overwrite otherwise — mirrors real behavior
        for rel, content in files.items():
            if rel.endswith(".jsonl"):
                existing = main.get(rel, "")
                main[rel] = server.git_sync._union_merge_lines(existing, content)
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
    assert "remember this" in client._main["data/notes.jsonl"]


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


def test_complete_task_returns_200_with_push_ok(client):
    created = client.post("/api/tasks", json={"title": "finish me"}).get_json()["task"]
    r = client.post(f"/api/tasks/{created['id']}/complete")
    assert r.status_code == 200
    assert r.get_json()["push"]["status"] == "ok"


def test_delete_missing_task_returns_404(client):
    r = client.delete("/api/tasks/t-doesnotexist")
    assert r.status_code == 404


def test_patch_person_updates_fields_and_commits(client):
    r = client.patch("/api/people/trent-luecke",
                     json={"email": "trent@teambuildr.com", "type": "internal"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["person"]["email"] == "trent@teambuildr.com"
    assert body["person"]["type"] == "internal"
    assert body["push"]["status"] == "ok"
    # landed on main and the snapshot reflects it
    stored = json.loads(client._main["data/people_registry.json"])["people"][0]
    assert stored["email"] == "trent@teambuildr.com"
    assert stored["type"] == "internal"
    # untouched fields preserved
    assert stored["canonical_name"] == "Trent Luecke"


def test_patch_person_ignores_unknown_fields(client):
    r = client.patch("/api/people/trent-luecke",
                     json={"email": "x@y.com", "id": "hacked", "bogus": 1})
    assert r.status_code == 200
    stored = json.loads(client._main["data/people_registry.json"])["people"][0]
    assert stored["id"] == "trent-luecke"  # id not overwritten
    assert "bogus" not in stored


def test_patch_missing_person_returns_404(client):
    r = client.patch("/api/people/nobody", json={"email": "x@y.com"})
    assert r.status_code == 404


def test_patch_person_offline_returns_503_no_commit(client, monkeypatch):
    monkeypatch.setattr(server.git_sync, "fetch_main", lambda *a, **k: False)
    before = client._main["data/people_registry.json"]
    r = client.patch("/api/people/trent-luecke", json={"email": "x@y.com"})
    assert r.status_code == 503
    assert client._main["data/people_registry.json"] == before


def _set_two_people(client):
    main = {
        "id": "trent-luecke", "canonical_name": "Trent Luecke",
        "email": None, "aliases": ["Trent"],
    }
    dup = {
        "id": "trent-l", "canonical_name": "Trent L",
        "email": "trent@teambuildr.com", "aliases": ["TL"],
    }
    client._main["data/people_registry.json"] = json.dumps({"people": [main, dup]})
    server.rebuild_snapshot()


def test_merge_person_applies_fields_removes_dup_and_commits(client):
    _set_two_people(client)
    r = client.post("/api/people/trent-luecke/merge", json={
        "merge_id": "trent-l",
        "fields": {
            "canonical_name": "Trent Luecke",
            "email": "trent@teambuildr.com",  # value chosen from the dup
            "aliases": ["Trent", "TL", "trent-l"],
        },
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["person"]["email"] == "trent@teambuildr.com"
    assert body["push"]["status"] == "ok"
    people = json.loads(client._main["data/people_registry.json"])["people"]
    ids = [p["id"] for p in people]
    assert ids == ["trent-luecke"]               # dup removed
    survivor = people[0]
    assert survivor["email"] == "trent@teambuildr.com"
    assert "trent-l" in survivor["aliases"]       # merged-away id preserved as alias


def test_merge_into_self_returns_400(client):
    _set_two_people(client)
    r = client.post("/api/people/trent-luecke/merge",
                    json={"merge_id": "trent-luecke", "fields": {}})
    assert r.status_code == 400


def test_merge_missing_survivor_returns_404(client):
    _set_two_people(client)
    r = client.post("/api/people/nobody/merge",
                    json={"merge_id": "trent-l", "fields": {}})
    assert r.status_code == 404


def test_merge_ignores_unknown_fields(client):
    _set_two_people(client)
    r = client.post("/api/people/trent-luecke/merge", json={
        "merge_id": "trent-l",
        "fields": {"id": "hacked", "bogus": 1, "email": "x@y.com"},
    })
    assert r.status_code == 200
    survivor = json.loads(client._main["data/people_registry.json"])["people"][0]
    assert survivor["id"] == "trent-luecke"
    assert "bogus" not in survivor


def test_merge_offline_returns_503_no_commit(client, monkeypatch):
    _set_two_people(client)
    monkeypatch.setattr(server.git_sync, "fetch_main", lambda *a, **k: False)
    before = client._main["data/people_registry.json"]
    r = client.post("/api/people/trent-luecke/merge",
                    json={"merge_id": "trent-l", "fields": {}})
    assert r.status_code == 503
    assert client._main["data/people_registry.json"] == before


def test_create_task_with_horizon_roundtrips(client):
    r = client.post("/api/tasks", json={"title": "Renew SSL", "horizon": "2099-01-01"})
    assert r.status_code == 201
    assert json.loads(r.data)["task"]["horizon"] == "2099-01-01"
    tasks = json.loads(client.get("/api/tasks").data)
    assert tasks[0]["horizon"] == "2099-01-01"


def test_patch_task_horizon(client):
    r = client.post("/api/tasks", json={"title": "Send deck"})
    task_id = json.loads(r.data)["task"]["id"]
    r = client.patch(f"/api/tasks/{task_id}", json={"horizon": "2099-01-01"})
    assert r.status_code == 200
    assert json.loads(r.data)["task"]["horizon"] == "2099-01-01"


# --- Routines ---

def _mk_routine(client, name="OOO Prep", steps=("Cancel meetings", "Set responder")):
    r = client.post("/api/routines", json={"name": name, "steps": list(steps)})
    assert r.status_code == 201
    return json.loads(r.data)["routine"]


def test_routines_crud_roundtrip(client):
    r = _mk_routine(client)
    assert r["id"] == "ooo-prep"
    listed = json.loads(client.get("/api/routines").data)
    assert [x["id"] for x in listed] == ["ooo-prep"]

    resp = client.patch("/api/routines/ooo-prep", json={"name": "OOO", "steps": ["Only step"]})
    assert resp.status_code == 200
    assert json.loads(resp.data)["routine"]["steps"] == [{"title": "Only step"}]

    resp = client.delete("/api/routines/ooo-prep")
    assert resp.status_code == 200
    assert json.loads(client.get("/api/routines").data) == []


def test_create_routine_requires_name_and_steps(client):
    assert client.post("/api/routines", json={"steps": ["x"]}).status_code == 400
    assert client.post("/api/routines", json={"name": "R", "steps": ["", "  "]}).status_code == 400


def test_patch_delete_missing_routine_404(client):
    assert client.patch("/api/routines/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/routines/nope").status_code == 404


def test_run_routine_creates_tasks(client):
    _mk_routine(client)
    resp = client.post("/api/routines/ooo-prep/run", json={})
    assert resp.status_code == 201
    body = json.loads(resp.data)
    assert [t["title"] for t in body["tasks"]] == ["Cancel meetings", "Set responder"]
    tasks = json.loads(client.get("/api/tasks").data)
    routine_tasks = [t for t in tasks if t["metadata"].get("routine") == "ooo-prep"]
    assert len(routine_tasks) == 2


def test_run_routine_recent_guard_and_force(client):
    _mk_routine(client)
    assert client.post("/api/routines/ooo-prep/run", json={}).status_code == 201
    resp = client.post("/api/routines/ooo-prep/run", json={})
    assert resp.status_code == 409
    assert json.loads(resp.data)["error"] == "recent_run"
    assert client.post("/api/routines/ooo-prep/run", json={"force": True}).status_code == 201


def test_run_routine_missing_and_empty(client):
    assert client.post("/api/routines/nope/run", json={}).status_code == 404
    assert client.post("/api/routines", json={"name": "E2", "steps": []}).status_code == 400


def test_bootstrap_includes_routines(client):
    _mk_routine(client)
    boot = json.loads(client.get("/api/bootstrap").data)
    assert [r["id"] for r in boot["routines"]] == ["ooo-prep"]


def test_patch_routine_rejects_blank_name_and_steps(client):
    _mk_routine(client)
    assert client.patch("/api/routines/ooo-prep", json={"name": "  "}).status_code == 400
    assert client.patch("/api/routines/ooo-prep", json={"steps": ["", " "]}).status_code == 400
