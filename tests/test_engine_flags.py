from pipeline import _format_engine_flags


def test_stale_snapshot_flagged():
    flags = _format_engine_flags({"stale": True, "stale_reason": "engine down", "freshness": {}})
    assert any("engine down" in f for f in flags)


def test_unsynced_source_flagged():
    flags = _format_engine_flags({"stale": False, "freshness": {"revenue": {"ok": False}}})
    assert any("revenue" in f for f in flags)


def test_healthy_snapshot_no_flags():
    flags = _format_engine_flags({"stale": False, "freshness": {"revenue": {"ok": True}}})
    assert flags == []


def test_none_freshness_no_crash():
    flags = _format_engine_flags({"stale": False, "freshness": None})
    assert flags == []
