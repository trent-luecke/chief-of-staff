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


# --- Run ---

def test_run_routine_creates_tagged_tasks_and_records_run(tmp_path):
    from datetime import date
    from lib.tasks import get_open_tasks
    from lib.routines import run_routine
    s = _s(tmp_path)
    r = add_routine(s, name="OOO Prep", steps=["Cancel meetings", "Set responder"])
    result = run_routine(s, r["id"])
    today = date.today().isoformat()

    assert [t["title"] for t in result["tasks"]] == ["Cancel meetings", "Set responder"]
    for t in result["tasks"]:
        assert t["source"] == "routine"
        assert t["metadata"] == {"routine": r["id"], "routine_run": today}
    assert result["routine"]["runs"] == [{"date": today, "trigger_key": None, "source": "ui"}]

    # tasks landed in the real task ledger, run persisted in the registry
    open_titles = {t["title"] for t in get_open_tasks(s)}
    assert {"Cancel meetings", "Set responder"} <= open_titles
    assert get_routine(s, r["id"])["runs"] == result["routine"]["runs"]


def test_run_routine_with_source_and_trigger_key(tmp_path):
    from lib.routines import run_routine
    s = _s(tmp_path)
    r = add_routine(s, name="R", steps=["a"])
    result = run_routine(s, r["id"], source="slack", trigger_key="gcal:evt123")
    assert result["routine"]["runs"][0]["source"] == "slack"
    assert result["routine"]["runs"][0]["trigger_key"] == "gcal:evt123"


def test_run_routine_missing_returns_none(tmp_path):
    from lib.routines import run_routine
    assert run_routine(_s(tmp_path), "nope") is None


def test_ran_within(tmp_path):
    from datetime import date, timedelta
    from lib.routines import ran_within, last_run_date
    today = date.today()
    recent = {"runs": [{"date": (today - timedelta(days=3)).isoformat(), "trigger_key": None, "source": "ui"}]}
    old = {"runs": [{"date": (today - timedelta(days=10)).isoformat(), "trigger_key": None, "source": "ui"}]}
    never = {"runs": []}
    assert ran_within(recent, days=7) is True
    assert ran_within(old, days=7) is False
    assert ran_within(never, days=7) is False
    assert last_run_date(recent) == (today - timedelta(days=3)).isoformat()
    assert last_run_date(never) is None


def test_ran_within_explicit_today():
    from lib.routines import ran_within
    r = {"runs": [{"date": "2026-07-01", "trigger_key": None, "source": "ui"}]}
    assert ran_within(r, days=7, today="2026-07-05") is True
    assert ran_within(r, days=7, today="2026-07-20") is False
