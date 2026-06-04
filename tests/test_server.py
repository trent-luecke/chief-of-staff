import json
import pytest
from unittest.mock import patch
from lib.storage import LocalStorage
from tools.server import app


def _storage_with(tmp_path, people=None):
    s = LocalStorage(base_dir=str(tmp_path))
    if people is not None:
        s.write_json("people_registry.json", {"version": 1, "people": people})
    return s


def test_list_people_empty(tmp_path):
    with patch("tools.server._storage", return_value=_storage_with(tmp_path)):
        resp = app.test_client().get("/api/people")
    assert resp.status_code == 200
    assert json.loads(resp.data) == []


def test_list_people_returns_id_and_name(tmp_path):
    people = [
        {"id": "nicole-foley", "canonical_name": "Nicole Foley", "aliases": []},
        {"id": "luke-martin", "canonical_name": "Luke Martin", "aliases": []},
    ]
    with patch("tools.server._storage", return_value=_storage_with(tmp_path, people)):
        resp = app.test_client().get("/api/people")
    data = json.loads(resp.data)
    assert {"id": "nicole-foley", "name": "Nicole Foley"} in data
    assert {"id": "luke-martin", "name": "Luke Martin"} in data


def test_list_people_falls_back_to_id_when_no_canonical_name(tmp_path):
    people = [{"id": "unknown-person"}]
    with patch("tools.server._storage", return_value=_storage_with(tmp_path, people)):
        resp = app.test_client().get("/api/people")
    data = json.loads(resp.data)
    assert data[0] == {"id": "unknown-person", "name": "unknown-person"}
