from lib.storage import LocalStorage
from lib.deal_events import DealEvent, make_event_id, append_events, load_events


def _store(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_make_event_id_is_deterministic():
    a = make_event_id("demo", "uuid-1", "x@acme.com")
    b = make_event_id("demo", "uuid-1", "x@acme.com")
    c = make_event_id("demo", "uuid-2", "x@acme.com")
    assert a == b and a != c and len(a) == 16


def test_append_is_idempotent_by_event_id(tmp_path):
    s = _store(tmp_path)
    e = DealEvent(event_id="e1", email="x@acme.com", email_raw="X@acme.com",
                  kind="demo", timestamp="2026-08-01T10:00:00Z")
    assert append_events(s, [e]) == 1
    assert append_events(s, [e]) == 0          # re-append is a no-op
    loaded = load_events(s)
    assert len(loaded) == 1 and loaded[0].email == "x@acme.com"
    assert loaded[0].kind == "demo"


def test_load_events_coerces_null_payload_to_empty_dict(tmp_path):
    # A hand-edited or malformed JSONL row can carry `"payload": null`.
    # json.loads(...) succeeds and DealEvent(**...) happily sets
    # payload=None (no TypeError), so it must NOT slip past the loader as
    # None — every downstream consumer (deal_fold) calls e.payload.get(...)
    # and a bare None there would crash the ENTIRE fold, not just this row.
    s = _store(tmp_path)
    s.write("deal_events.jsonl", '{"event_id": "e1", "email": "x@acme.com", '
            '"email_raw": "X@acme.com", "kind": "demo", '
            '"timestamp": "2026-08-01T10:00:00Z", "payload": null}\n')
    loaded = load_events(s)  # must not raise
    assert len(loaded) == 1
    assert loaded[0].payload == {}
