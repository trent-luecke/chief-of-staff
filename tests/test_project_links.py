# tests/test_project_links.py
import pytest
from lib.storage import LocalStorage
from lib.project_links import add_link, remove_link, get_links_for_project, get_projects_for_observation


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_add_link(tmp_path):
    add_link(_s(tmp_path), project_id="proj-a", obs_date="2026-06-02",
             obs_entity="demo-call", source_thread_ts="ts1", call_title="Demo")
    links = get_links_for_project(_s(tmp_path), "proj-a")
    assert len(links) == 1
    assert links[0]["obs_date"] == "2026-06-02"
    assert links[0]["obs_entity"] == "demo-call"


def test_add_link_idempotent(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="demo-call", source_thread_ts="ts1", call_title="Demo")
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="demo-call", source_thread_ts="ts1", call_title="Demo")
    assert len(get_links_for_project(s, "proj-a")) == 1


def test_remove_link(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="demo-call", source_thread_ts="ts1", call_title="Demo")
    remove_link(s, project_id="proj-a", obs_date="2026-06-02", obs_entity="demo-call")
    assert get_links_for_project(s, "proj-a") == []


def test_get_links_for_project_empty(tmp_path):
    assert get_links_for_project(_s(tmp_path), "proj-x") == []


def test_get_links_multiple_projects(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-01",
             obs_entity="call-1", source_thread_ts="ts1", call_title="Call 1")
    add_link(s, project_id="proj-b", obs_date="2026-06-02",
             obs_entity="call-2", source_thread_ts="ts2", call_title="Call 2")
    assert len(get_links_for_project(s, "proj-a")) == 1
    assert len(get_links_for_project(s, "proj-b")) == 1


def test_get_projects_for_observation(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="shared-call", source_thread_ts="ts1", call_title="Shared")
    add_link(s, project_id="proj-b", obs_date="2026-06-02",
             obs_entity="shared-call", source_thread_ts="ts1", call_title="Shared")
    projects = get_projects_for_observation(s, obs_date="2026-06-02", obs_entity="shared-call")
    assert set(projects) == {"proj-a", "proj-b"}


def test_get_projects_for_observation_after_unlink(tmp_path):
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="call", source_thread_ts="ts1", call_title="Call")
    remove_link(s, project_id="proj-a", obs_date="2026-06-02", obs_entity="call")
    assert get_projects_for_observation(s, "2026-06-02", "call") == []


def test_events_are_jsonl(tmp_path):
    import json
    s = _s(tmp_path)
    add_link(s, project_id="proj-a", obs_date="2026-06-02",
             obs_entity="call", source_thread_ts="ts1", call_title="Call")
    lines = (tmp_path / "project_observation_links.jsonl").read_text().strip().splitlines()
    event = json.loads(lines[0])
    assert event["event"] == "link"
    assert event["project_id"] == "proj-a"
