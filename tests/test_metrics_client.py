from datetime import date
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


def test_metrics_from_snapshot_maps_inputs():
    snapshot = {
        "demos_data": {"count": 8},
        "sales_data": {"count": 5, "revenue": 1000.0},
        "cancellations": {"count": 1, "entries": [{"date": "6/3/2026", "reason": "price"}]},
        "targets": {"demos_mtd_target": 30, "sales_mtd_target": 15,
                    "onboarding_coverage_threshold": 5, "churn_count_threshold": 2,
                    "churn_reason_cluster_threshold": 2, "churn_reason_window_days": 30,
                    "pace_early_month_guard_pct": 0.25},
    }
    results = mc.metrics_from_snapshot(
        snapshot, onboarding_active=[{"status": "In Progress"}] * 6, today=date(2026, 6, 16),
    )
    by_id = {r.id: r for r in results}
    assert by_id["demos_mtd"].current == 8
    assert by_id["sales_mtd"].current == 5
    assert by_id["onboarding_coverage"].current == 6
    assert by_id["churn_count"].current == 1


def test_metrics_from_snapshot_zero_cancellations_passes_none():
    snapshot = {
        "demos_data": {"count": 0}, "sales_data": {"count": 0},
        "cancellations": {"count": 0, "entries": []},
        "targets": {"demos_mtd_target": 30, "sales_mtd_target": 15,
                    "onboarding_coverage_threshold": 5, "churn_count_threshold": 2,
                    "churn_reason_cluster_threshold": 2, "churn_reason_window_days": 30,
                    "pace_early_month_guard_pct": 0.25},
    }
    results = mc.metrics_from_snapshot(snapshot, onboarding_active=[], today=date(2026, 6, 16))
    assert {r.id for r in results} == {
        "demos_mtd", "sales_mtd", "onboarding_coverage", "churn_count", "churn_reasons"}
