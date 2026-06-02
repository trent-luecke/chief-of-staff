# tests/test_projects.py
import pytest
from lib.storage import LocalStorage
from lib.projects import (
    add_project, get_project, list_projects,
    find_project_by_alias, update_project,
    project_context_for_brief,
)


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_add_project_minimal(tmp_path):
    p = add_project(_s(tmp_path), canonical_name="Nicole Campaign")
    assert p["canonical_name"] == "Nicole Campaign"
    assert p["id"] == "nicole-campaign"
    assert p["status"] == "active"
    assert p["members"] == []
    assert p["aliases"] == []


def test_add_project_with_aliases_and_members(tmp_path):
    p = add_project(
        _s(tmp_path),
        canonical_name="Customer Outreach 2026",
        aliases=["marketing push"],
        members=[{"person_id": "nicole-foley", "role": "owner"}],
    )
    assert "marketing push" in p["aliases"]
    assert p["members"][0]["role"] == "owner"


def test_add_project_deduplicates_slug(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Demo")
    p2 = add_project(s, canonical_name="Demo")
    assert p2["id"] == "demo-2"


def test_get_project_found(tmp_path):
    s = _s(tmp_path)
    added = add_project(s, canonical_name="Alpha")
    assert get_project(s, added["id"])["id"] == added["id"]


def test_get_project_missing(tmp_path):
    assert get_project(_s(tmp_path), "nope") is None


def test_list_projects_empty(tmp_path):
    assert list_projects(_s(tmp_path)) == []


def test_list_projects(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Alpha")
    add_project(s, canonical_name="Beta")
    assert len(list_projects(s)) == 2


def test_list_projects_filter_status(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Active One", status="active")
    add_project(s, canonical_name="Archived", status="archived")
    assert len(list_projects(s, status="active")) == 1


def test_find_by_alias(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Nicole Campaign", aliases=["marketing push"])
    assert find_project_by_alias(s, "marketing push") is not None
    assert find_project_by_alias(s, "unknown") is None


def test_find_by_alias_case_insensitive(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Demo Push", aliases=["Demo Push"])
    assert find_project_by_alias(s, "demo push") is not None


def test_find_by_canonical_name(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Exact Match")
    assert find_project_by_alias(s, "Exact Match") is not None


def test_update_project(tmp_path):
    s = _s(tmp_path)
    p = add_project(s, canonical_name="Draft")
    updated = update_project(s, p["id"], {"status": "archived"})
    assert updated["status"] == "archived"
    assert get_project(s, p["id"])["status"] == "archived"


def test_update_project_missing(tmp_path):
    assert update_project(_s(tmp_path), "nope", {"status": "archived"}) is None


def test_persisted_across_loads(tmp_path):
    s = _s(tmp_path)
    add_project(s, canonical_name="Persist Me")
    s2 = LocalStorage(base_dir=str(tmp_path))
    assert list_projects(s2)[0]["canonical_name"] == "Persist Me"


def test_project_context_for_brief_empty(tmp_path):
    assert project_context_for_brief(_s(tmp_path)) == []


def test_project_context_for_brief_with_open_task(tmp_path):
    from lib.tasks import add_task
    s = _s(tmp_path)
    add_project(s, canonical_name="Nicole Campaign")
    add_task(s, "Follow up", project_id="nicole-campaign")
    ctx = project_context_for_brief(s)
    assert len(ctx) == 1
    assert ctx[0]["project"]["id"] == "nicole-campaign"
    assert len(ctx[0]["open_tasks"]) == 1
    assert ctx[0]["linked_obs"] == []
