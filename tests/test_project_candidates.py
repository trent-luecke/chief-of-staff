# tests/test_project_candidates.py
import pytest
from lib.storage import LocalStorage
from lib.project_candidates import (
    flag_candidate, list_pending_candidates, resolve_candidate, get_candidate,
)


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_flag_candidate(tmp_path):
    c = flag_candidate(
        _s(tmp_path),
        project_id="nicole-campaign",
        obs_date="2026-06-02",
        obs_entity="demo-call-acme",
        source_thread_ts="1234.5678",
        call_title="Demo - Acme",
    )
    assert c["project_id"] == "nicole-campaign"
    assert c["status"] == "pending"
    assert c["id"].startswith("plc-")


def test_list_pending_empty(tmp_path):
    assert list_pending_candidates(_s(tmp_path)) == []


def test_list_pending_returns_only_pending(tmp_path):
    s = _s(tmp_path)
    c = flag_candidate(s, project_id="proj-a", obs_date="2026-06-02",
                       obs_entity="ent", source_thread_ts="ts1", call_title="Call A")
    resolve_candidate(s, c["id"], "confirmed")
    flag_candidate(s, project_id="proj-b", obs_date="2026-06-02",
                   obs_entity="ent2", source_thread_ts="ts2", call_title="Call B")
    assert len(list_pending_candidates(s)) == 1
    assert list_pending_candidates(s)[0]["project_id"] == "proj-b"


def test_get_candidate(tmp_path):
    s = _s(tmp_path)
    c = flag_candidate(s, project_id="proj-a", obs_date="2026-06-02",
                       obs_entity="ent", source_thread_ts="ts1", call_title="Call A")
    assert get_candidate(s, c["id"])["id"] == c["id"]


def test_get_candidate_missing(tmp_path):
    assert get_candidate(_s(tmp_path), "nope") is None


def test_resolve_confirmed(tmp_path):
    s = _s(tmp_path)
    c = flag_candidate(s, project_id="proj-a", obs_date="2026-06-02",
                       obs_entity="ent", source_thread_ts="ts1", call_title="Call")
    resolved = resolve_candidate(s, c["id"], "confirmed")
    assert resolved["status"] == "confirmed"
    assert list_pending_candidates(s) == []


def test_resolve_dismissed(tmp_path):
    s = _s(tmp_path)
    c = flag_candidate(s, project_id="proj-a", obs_date="2026-06-02",
                       obs_entity="ent", source_thread_ts="ts1", call_title="Call")
    resolve_candidate(s, c["id"], "dismissed")
    assert list_pending_candidates(s) == []


def test_resolve_missing(tmp_path):
    assert resolve_candidate(_s(tmp_path), "nope", "confirmed") is None
