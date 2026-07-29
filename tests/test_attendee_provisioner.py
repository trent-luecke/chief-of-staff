from collectors.calendar import CalendarEvent
from processors import attendee_provisioner as ap


def _event(eid, summary, details):
    return CalendarEvent(
        id=eid, summary=summary, start=None, end=None,
        attendees=[d["email"] for d in details],
        attendee_details=details,
    )


def test_classify_attendees_splits_by_domain():
    internal, external = ap.classify_attendees(
        ["q@teambuildr.com", "jane@acme.com", "bob@acme.com"], ["teambuildr.com"]
    )
    assert internal == ["q@teambuildr.com"]
    assert external == ["jane@acme.com", "bob@acme.com"]


def test_stubs_created_for_unresolved_external_only():
    people = [{
        "id": "jane-smith", "canonical_name": "Jane Smith",
        "aliases": ["Jane Smith", "jane@acme.com"], "email": "jane@acme.com",
        "type": "lead", "pipeline_record": None, "people_file": None,
        "created": "2026-01-01", "last_seen": "2026-01-01",
    }]
    ev = _event("e1", "Acme demo", [
        {"email": "q@teambuildr.com", "name": "Quinn"},      # internal -> skip
        {"email": "jane@acme.com", "name": "Jane Smith"},    # already known -> skip
        {"email": "mike_jones@acme.com", "name": ""},        # NEW external -> stub
    ])
    new_stubs, updated = ap.stubs_for_events([ev], people, ["teambuildr.com"], "2026-07-29")
    assert len(new_stubs) == 1
    stub = new_stubs[0]
    assert stub["email"] == "mike_jones@acme.com"
    assert stub["canonical_name"] == "Mike Jones"       # derived from email (no displayName)
    assert stub["aliases"] == ["mike_jones@acme.com"]
    assert stub["type"] == "unknown"
    assert stub["created"] == "2026-07-29" and stub["last_seen"] == "2026-07-29"
    assert stub["provenance"] == "auto:calendar 2026-07-29 meeting:Acme demo"
    assert len(updated) == 2  # original + new stub


def test_stub_uses_display_name_when_present():
    ev = _event("e1", "Acme demo", [{"email": "x@acme.com", "name": "Xavier Onassis"}])
    new_stubs, _ = ap.stubs_for_events([ev], [], ["teambuildr.com"], "2026-07-29")
    assert new_stubs[0]["canonical_name"] == "Xavier Onassis"
    assert new_stubs[0]["id"] == "xavier-onassis"


def test_large_meetings_skipped():
    details = [{"email": f"p{i}@acme.com", "name": ""} for i in range(6)]  # 6 attendees
    ev = _event("e1", "Big webinar", details)
    new_stubs, _ = ap.stubs_for_events([ev], [], ["teambuildr.com"], "2026-07-29")
    assert new_stubs == []


def test_dedup_within_run_across_events():
    d = [{"email": "same@acme.com", "name": "Same Person"}]
    evs = [_event("e1", "Call A", d), _event("e2", "Call B", d)]
    new_stubs, _ = ap.stubs_for_events(evs, [], ["teambuildr.com"], "2026-07-29")
    assert len(new_stubs) == 1  # only one stub despite two events


def test_provision_from_events_writes_registry(tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    ev = _event("e1", "Acme demo", [{"email": "jane@acme.com", "name": "Jane Smith"}])
    config = {"demo_scan": {"internal_domains": ["teambuildr.com"]}}
    new_stubs = ap.provision_from_events([ev], storage, config, "2026-07-29")
    assert len(new_stubs) == 1
    saved = storage.read_json("people_registry.json")
    assert saved["version"] == 1
    assert any(p["email"] == "jane@acme.com" for p in saved["people"])


def test_exactly_five_attendees_allowed():
    # 5 external attendees is below the >=6 skip threshold -> all 5 provision
    details = [{"email": f"p{i}@acme.com", "name": ""} for i in range(5)]
    ev = _event("e1", "Small call", details)
    new_stubs, _ = ap.stubs_for_events([ev], [], ["teambuildr.com"], "2026-07-29")
    assert len(new_stubs) == 5


def test_no_write_when_no_new_stubs(tmp_path):
    # all-internal event -> zero new stubs -> provision_from_events must NOT write
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("people_registry.json", {"version": 1, "people": []})
    writes = []
    orig_write = storage.write_json
    def spy(key, data, *a, **k):
        writes.append(key)
        return orig_write(key, data, *a, **k)
    storage.write_json = spy
    ev = _event("e1", "Internal sync", [{"email": "q@teambuildr.com", "name": "Quinn"}])
    config = {"demo_scan": {"internal_domains": ["teambuildr.com"]}}
    new_stubs = ap.provision_from_events([ev], storage, config, "2026-07-29")
    assert new_stubs == []
    assert writes == []  # write skipped entirely when no new stubs
