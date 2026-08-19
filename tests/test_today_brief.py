import json

from collectors.calendar import CalendarEvent
from lib.storage import LocalStorage
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


def _internal_ev(eid, title="Luke / Trent"):
    return _ev(eid, title, [{"email": "luke@teambuildr.com", "name": "Luke Green"}])


def _write_index(tmp_path, recipe):
    idx = tmp_path / "meeting_index.json"
    idx.write_text(json.dumps({"meetings": [{
        "calendar_pattern": "luke / trent",
        "memory_file": "data/meeting_memory/luke_1on1.md",
        "nudge_subject": "1:1?", "nudge_minutes_after": 5, "name": "Luke 1:1",
        "prep_recipe": recipe,
    }]}))
    return str(idx)


def test_internal_meeting_with_recipe_gets_prep(monkeypatch, tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    recipe = {"blocks": ["open_threads"], "instruction": "x"}
    idx_path = _write_index(tmp_path, recipe)

    calls = {"n": 0}
    monkeypatch.setattr(tb.meeting_prep_recipe, "build_prep",
                        lambda event, cfg, config, storage_, api_key: (calls.__setitem__("n", calls["n"] + 1) or "PREP TEXT"))

    config = {"meeting_index_file": idx_path, "demo_scan": {"internal_domains": ["teambuildr.com"]}}
    brief = tb.generate_and_write(config, [_internal_ev("m1")], storage,
                                  today="2026-08-04", generated_at="2026-08-04T12:00:00Z", api_key="key")
    m = next(x for x in brief["meetings"] if x["id"] == "m1")
    assert m["prep"] == "PREP TEXT"
    assert m["prep_hash"] == tb.meeting_prep_recipe.prep_hash(recipe)
    assert calls["n"] == 1


def test_prep_reused_from_prior_brief_when_hash_matches(monkeypatch, tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    recipe = {"blocks": ["open_threads"], "instruction": "x"}
    idx_path = _write_index(tmp_path, recipe)
    phash = tb.meeting_prep_recipe.prep_hash(recipe)
    # prior brief for the SAME day with a matching hash → cache hit
    storage.write_json("brief_today.json", {"date": "2026-08-04",
        "meetings": [{"id": "m1", "prep": "CACHED", "prep_hash": phash}]})

    def boom(*a, **k):
        raise AssertionError("build_prep should not be called on cache hit")
    monkeypatch.setattr(tb.meeting_prep_recipe, "build_prep", boom)

    config = {"meeting_index_file": idx_path, "demo_scan": {"internal_domains": ["teambuildr.com"]}}
    brief = tb.generate_and_write(config, [_internal_ev("m1")], storage,
                                  today="2026-08-04", generated_at="2026-08-04T12:00:00Z", api_key="key")
    m = next(x for x in brief["meetings"] if x["id"] == "m1")
    assert m["prep"] == "CACHED"


def test_prep_regenerates_when_hash_differs(monkeypatch, tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    recipe = {"blocks": ["open_threads"], "instruction": "NEW"}
    idx_path = _write_index(tmp_path, recipe)
    # prior brief carries a STALE hash → must re-run build_prep
    storage.write_json("brief_today.json", {"date": "2026-08-04",
        "meetings": [{"id": "m1", "prep": "OLD", "prep_hash": "staleeeeeeee"}]})
    monkeypatch.setattr(tb.meeting_prep_recipe, "build_prep",
                        lambda *a, **k: "FRESH")
    config = {"meeting_index_file": idx_path, "demo_scan": {"internal_domains": ["teambuildr.com"]}}
    brief = tb.generate_and_write(config, [_internal_ev("m1")], storage,
                                  today="2026-08-04", generated_at="2026-08-04T12:00:00Z", api_key="key")
    m = next(x for x in brief["meetings"] if x["id"] == "m1")
    assert m["prep"] == "FRESH"


def test_external_meeting_prep_stays_none(monkeypatch, tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    idx_path = _write_index(tmp_path, {"blocks": ["open_threads"]})
    monkeypatch.setattr(tb.meeting_prep_recipe, "build_prep",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no prep for external")))
    config = {"meeting_index_file": idx_path, "demo_scan": {"internal_domains": ["teambuildr.com"]}}
    ev = _ev("x1", "Prospect sync", [{"email": "buyer@acme.com", "name": "Buyer"}])
    brief = tb.generate_and_write(config, [ev], storage,
                                  today="2026-08-04", generated_at="2026-08-04T12:00:00Z", api_key="key")
    assert brief["meetings"][0]["prep"] is None


def test_brief_carries_deal_review_counts(tmp_path):
    store = LocalStorage(str(tmp_path))
    store.append_line("deal_events.jsonl",
        '{"event_id":"e1","email":"x@acme.com","email_raw":"","kind":"demo",'
        '"timestamp":"2026-06-01T00:00:00Z","account_name":"","rep":"Luke",'
        '"source":"avoma","payload":{"avoma_uuid":"u1","contact_emails":["x@acme.com"],'
        '"ambiguous_reason":null}}')  # aged → stale_check
    brief = tb.build_today_brief([], [], ["teambuildr.com"], "2026-08-18",
                              "2026-08-18T12:00:00Z", config={}, storage=store)
    assert brief["deals_to_review"]["counts"]["stale"] == 1
    assert brief["deals_to_review"]["counts"]["total"] == 1
