# tests/test_routines.py
import pytest
from lib.storage import LocalStorage
from lib.routines import (
    add_routine, get_routine, list_routines,
    update_routine, delete_routine,
)


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


# --- CRUD ---

def test_add_routine_minimal(tmp_path):
    r = add_routine(_s(tmp_path), name="Out of Office Prep",
                    steps=["Cancel meetings", "Set OOO responder"])
    assert r["id"] == "out-of-office-prep"
    assert r["name"] == "Out of Office Prep"
    assert r["steps"] == [{"title": "Cancel meetings"}, {"title": "Set OOO responder"}]
    assert r["trigger"] is None
    assert r["runs"] == []
    assert r["created"]


def test_add_routine_normalizes_dict_steps_and_drops_blanks(tmp_path):
    r = add_routine(_s(tmp_path), name="R",
                    steps=[{"title": "Keep"}, "", "  ", "Also keep"])
    assert r["steps"] == [{"title": "Keep"}, {"title": "Also keep"}]


def test_add_routine_with_trigger(tmp_path):
    r = add_routine(_s(tmp_path), name="OOO",
                    steps=["x"], trigger={"type": "calendar_ooo", "lead_days": 7})
    assert r["trigger"] == {"type": "calendar_ooo", "lead_days": 7}


def test_add_routine_unique_slug(tmp_path):
    s = _s(tmp_path)
    add_routine(s, name="Weekly Review", steps=["a"])
    r2 = add_routine(s, name="Weekly Review", steps=["b"])
    assert r2["id"] == "weekly-review-2"


def test_list_and_get(tmp_path):
    s = _s(tmp_path)
    assert list_routines(s) == []
    r = add_routine(s, name="R", steps=["a"])
    assert [x["id"] for x in list_routines(s)] == [r["id"]]
    assert get_routine(s, r["id"])["name"] == "R"
    assert get_routine(s, "nope") is None


def test_update_routine(tmp_path):
    s = _s(tmp_path)
    r = add_routine(s, name="R", steps=["a"])
    out = update_routine(s, r["id"], {"name": "R2", "steps": ["x", "y"],
                                      "trigger": {"type": "calendar_ooo", "lead_days": 3}})
    assert out["name"] == "R2"
    assert out["steps"] == [{"title": "x"}, {"title": "y"}]
    assert out["trigger"]["lead_days"] == 3
    # persisted
    assert get_routine(s, r["id"])["name"] == "R2"


def test_update_routine_protects_id_created_runs(tmp_path):
    s = _s(tmp_path)
    r = add_routine(s, name="R", steps=["a"])
    out = update_routine(s, r["id"], {"id": "hax", "created": "1999-01-01", "runs": ["bogus"]})
    assert out["id"] == r["id"]
    assert out["created"] == r["created"]
    assert out["runs"] == []


def test_update_routine_missing_returns_none(tmp_path):
    assert update_routine(_s(tmp_path), "nope", {"name": "x"}) is None


def test_delete_routine(tmp_path):
    s = _s(tmp_path)
    r = add_routine(s, name="R", steps=["a"])
    assert delete_routine(s, r["id"]) is True
    assert list_routines(s) == []
    assert delete_routine(s, r["id"]) is False
