import lib.metrics_client as mc


class FakeStorage:
    def __init__(self, initial=None):
        self.store = dict(initial or {})
    def read_json(self, key):
        return self.store.get(key)
    def write_json(self, key, value):
        self.store[key] = value


def test_fetch_snapshot_happy(monkeypatch):
    payload = {"schema_version": 1, "sales_data": {"count": 2}, "targets": {}}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return payload

    monkeypatch.setattr(mc.requests, "get", lambda *a, **k: Resp())
    storage = FakeStorage()
    snap = mc.fetch_snapshot("http://x", "pw", storage)

    assert snap["stale"] is False
    assert snap["sales_data"]["count"] == 2
    # Cached for next time.
    assert storage.store[mc.SNAPSHOT_CACHE_KEY]["sales_data"]["count"] == 2


def test_fetch_snapshot_down_returns_cached_stale(monkeypatch):
    def boom(*a, **k):
        raise mc.requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(mc.requests, "get", boom)
    cached = {"schema_version": 1, "sales_data": {"count": 9}, "targets": {}}
    storage = FakeStorage({mc.SNAPSHOT_CACHE_KEY: cached})

    snap = mc.fetch_snapshot("http://x", "pw", storage)
    assert snap["stale"] is True
    assert "stale_reason" in snap
    assert snap["sales_data"]["count"] == 9


def test_fetch_snapshot_down_no_cache_returns_none(monkeypatch):
    def boom(*a, **k):
        raise mc.requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(mc.requests, "get", boom)
    assert mc.fetch_snapshot("http://x", "pw", FakeStorage()) is None


def test_trigger_sync_failure_is_non_fatal(monkeypatch):
    def boom(*a, **k):
        raise mc.requests.exceptions.Timeout("slow")
    monkeypatch.setattr(mc.requests, "post", boom)
    out = mc.trigger_sync("http://x", "pw")
    assert out["status"] == "error"
    assert "report" in out
