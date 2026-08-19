import json
import importlib


def _client(monkeypatch, events_jsonl):
    import tools.server as srv
    importlib.reload(srv)

    def fake_show_main(path):
        if path.endswith("deal_events.jsonl"):
            return events_jsonl
        return None  # everything else empty

    monkeypatch.setattr(srv.git_sync, "show_main", fake_show_main)
    monkeypatch.setattr(srv.git_sync, "fetch_main", lambda: True)
    srv.rebuild_snapshot(known_online=True)
    srv.app.config["TESTING"] = True
    return srv, srv.app.test_client()


def test_get_deals_review_returns_two_queues(monkeypatch):
    ev = {"event_id": "e1", "email": "jane@acme.com", "email_raw": "", "kind": "demo",
          "timestamp": "2026-08-17T00:00:00Z", "account_name": "", "rep": "Luke Martin",
          "source": "avoma",
          "payload": {"avoma_uuid": "u1", "contact_emails": ["jane@acme.com"],
                      "ambiguous_reason": "free_email"}}
    srv, c = _client(monkeypatch, json.dumps(ev) + "\n")
    r = c.get("/api/deals/review")
    assert r.status_code == 200
    body = r.get_json()
    assert body["counts"]["identity"] == 1
    assert body["identity"][0]["deal_key"] == "jane@acme.com"


def test_bootstrap_includes_deals_review(monkeypatch):
    srv, c = _client(monkeypatch, "")
    body = c.get("/api/bootstrap").get_json()
    assert "deals_review" in body
    assert body["deals_review"]["counts"]["total"] == 0


def test_malformed_event_email_does_not_crash_rebuild(monkeypatch):
    # A non-string email in the event log used to raise AttributeError deep
    # inside the fold (`.startswith` on an int), and because the deals-review
    # compute was unguarded in rebuild_snapshot, that took down the WHOLE
    # snapshot (tasks/projects/notes/meetings included), not just deals.
    ev = {"event_id": "e1", "email": 12345, "email_raw": "", "kind": "demo",
          "timestamp": "2026-08-17T00:00:00Z", "payload": {}}
    srv, c = _client(monkeypatch, json.dumps(ev) + "\n")  # must not raise

    r = c.get("/api/bootstrap")
    assert r.status_code == 200
    body = r.get_json()
    assert "tasks" in body  # rest of the snapshot still rebuilt
    assert isinstance(body["deals_review"]["counts"]["total"], int)
    assert body["deals_review"]["counts"]["total"] == 0


def test_snapshot_guard_degrades_to_empty_when_compute_raises(monkeypatch):
    # Proves the server-level guard independently of fold hardening: even if
    # _compute_deals_review itself blows up for some other reason, the rest
    # of rebuild_snapshot must still complete and deals_review must fall back
    # to the empty default rather than propagating.
    import tools.server as srv
    importlib.reload(srv)

    def fake_show_main(path):
        return None

    monkeypatch.setattr(srv.git_sync, "show_main", fake_show_main)
    monkeypatch.setattr(srv.git_sync, "fetch_main", lambda: True)

    def boom(store):
        raise RuntimeError("deliberate failure")

    monkeypatch.setattr(srv, "_compute_deals_review", boom)

    srv.rebuild_snapshot(known_online=True)  # must not raise

    assert srv.SNAPSHOT.deals_review == {
        "identity": [], "stale": [], "counts": {"identity": 0, "stale": 0, "total": 0},
    }
    assert srv.SNAPSHOT.tasks == []  # rest of snapshot still rebuilt
