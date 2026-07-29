from collectors.calendar import CalendarEvent
from processors import today_brief as tb


def _ev(eid, title, details, declined=False):
    from datetime import datetime
    return CalendarEvent(
        id=eid, summary=title,
        start=datetime(2026, 7, 29, 9, 0), end=datetime(2026, 7, 29, 9, 30),
        attendees=[d["email"] for d in details],
        attendee_details=details, declined=declined,
    )


def test_rank_needs_orders_and_caps():
    tasks = [
        {"id": "a", "title": "H", "due_date": None, "horizon": "2026-07-29", "project_id": None},
        {"id": "b", "title": "O", "due_date": "2026-07-01", "project_id": None},
        {"id": "c", "title": "D", "due_date": "2026-07-29", "project_id": None},
        {"id": "d", "title": "O2", "due_date": "2026-06-15", "project_id": None},
    ]
    out = tb.rank_needs(tasks, today="2026-07-29", cap=3)
    assert [x["id"] for x in out] == ["d", "b", "c"]  # overdue(oldest first), then due; horizon dropped by cap
    assert out[0]["reason"] == "overdue" and out[2]["reason"] == "due"


def test_meeting_dict_classifies_external_and_internal():
    ext = tb._meeting_dict(
        _ev("m1", "Acme demo", [{"email": "jane@acme.com", "name": "Jane"},
                                {"email": "q@teambuildr.com", "name": "Quinn"}]),
        ["teambuildr.com"])
    assert ext["kind"] == "external"
    assert ext["prep"] is None
    assert ext["attendees"] == [{"email": "jane@acme.com", "name": "Jane"},
                                {"email": "q@teambuildr.com", "name": "Quinn"}]
    internal = tb._meeting_dict(
        _ev("m2", "Team sync", [{"email": "q@teambuildr.com", "name": "Quinn"}]),
        ["teambuildr.com"])
    assert internal["kind"] == "internal"


def test_build_today_brief_skips_declined_and_shapes_payload():
    events = [
        _ev("m1", "Acme demo", [{"email": "jane@acme.com", "name": "Jane"}]),
        _ev("m2", "Declined call", [{"email": "x@acme.com", "name": "X"}], declined=True),
    ]
    needs = [{"id": "t1", "title": "Ship it", "reason": "due", "due_date": "2026-07-29", "project_id": None}]
    brief = tb.build_today_brief(events, needs, ["teambuildr.com"],
                                 today="2026-07-29", generated_at="2026-07-29T11:00:00Z")
    assert brief["date"] == "2026-07-29"
    assert brief["generated_at"] == "2026-07-29T11:00:00Z"
    assert [m["id"] for m in brief["meetings"]] == ["m1"]  # declined skipped
    assert brief["needs_today"] == needs
    assert brief["what_moved"] == []


def test_generate_and_write_persists_and_provisions(tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    events = [_ev("m1", "Acme demo", [{"email": "jane@acme.com", "name": "Jane Smith"}])]
    config = {"demo_scan": {"internal_domains": ["teambuildr.com"]}}
    brief = tb.generate_and_write(config, events, storage,
                                  today="2026-07-29", generated_at="2026-07-29T11:00:00Z")
    saved = storage.read_json("brief_today.json")
    assert saved["date"] == "2026-07-29"
    assert saved["meetings"][0]["title"] == "Acme demo"
    # provisioning created a stub for the external attendee
    people = storage.read_json("people_registry.json")["people"]
    assert any(p["email"] == "jane@acme.com" for p in people)


def test_rank_needs_horizon_bucket_orders_by_horizon_date():
    # Two horizon tasks (no due_date); cap high enough to keep both.
    tasks = [
        {"id": "h_new", "title": "newer horizon", "due_date": None, "horizon": "2026-07-29", "project_id": None},
        {"id": "h_old", "title": "older horizon", "due_date": None, "horizon": "2026-07-10", "project_id": None},
    ]
    out = tb.rank_needs(tasks, today="2026-07-29", cap=5)
    assert [x["id"] for x in out] == ["h_old", "h_new"]  # oldest horizon first
    assert all(x["reason"] == "horizon" for x in out)
