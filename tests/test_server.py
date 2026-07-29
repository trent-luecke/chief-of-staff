import json
from tools.server import app, SNAPSHOT


def _set_people(people):
    SNAPSHOT.people = {"version": 1, "people": people or []}


def test_list_people_empty():
    _set_people([])
    resp = app.test_client().get("/api/people")
    assert resp.status_code == 200
    assert json.loads(resp.data) == []


def test_list_people_returns_id_and_name():
    _set_people([
        {"id": "nicole-foley", "canonical_name": "Nicole Foley", "aliases": []},
        {"id": "luke-martin", "canonical_name": "Luke Martin", "aliases": []},
    ])
    resp = app.test_client().get("/api/people")
    data = json.loads(resp.data)
    assert {"id": "nicole-foley", "name": "Nicole Foley"} in data
    assert {"id": "luke-martin", "name": "Luke Martin"} in data


def test_list_people_falls_back_to_id_when_no_canonical_name():
    _set_people([{"id": "unknown-person"}])
    resp = app.test_client().get("/api/people")
    data = json.loads(resp.data)
    assert data[0] == {"id": "unknown-person", "name": "unknown-person"}


def test_brief_today_endpoint_returns_snapshot():
    SNAPSHOT.brief = {
        "date": "2026-07-29",
        "generated_at": "2026-07-29T11:00:00Z",
        "meetings": [{"id": "m1", "title": "Acme demo", "kind": "external",
                      "attendees": [], "prep": None, "start": None, "end": None}],
        "needs_today": [],
        "what_moved": [],
    }
    resp = app.test_client().get("/api/brief_today")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["date"] == "2026-07-29"
    assert body["meetings"][0]["title"] == "Acme demo"
