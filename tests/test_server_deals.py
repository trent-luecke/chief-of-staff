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
