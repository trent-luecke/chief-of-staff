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
