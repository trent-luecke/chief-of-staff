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
    # Defense-in-depth: never let a test reach the real commit/push to origin/main.
    # A test that forgets to fake _write_main must still be incapable of writing
    # to the live datastore (a leak here already pushed junk events to main once).
    monkeypatch.setattr(srv.git_sync, "commit_files_to_main",
                        lambda files, msg: {"status": "ok"})
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


def test_post_status_lost_appends_status_event(monkeypatch):
    srv, c = _client(monkeypatch, "")
    captured = {}

    def fake_write_main(mutate, msg_fn):
        store = srv._read_store()
        result = mutate(store)
        captured["dirty"] = store.dirty()
        return result, {"status": "ok"}, 200

    monkeypatch.setattr(srv, "_write_main", fake_write_main)
    r = c.post("/api/deals/status", json={"deal_key": "x@acme.com", "status": "lost",
                                          "lost_reason": "budget"})
    assert r.status_code == 201
    line = captured["dirty"]["data/deal_events.jsonl"].strip().splitlines()[-1]
    ev = json.loads(line)
    assert ev["kind"] == "status" and ev["email"] == "x@acme.com"
    assert ev["payload"] == {"status": "lost", "lost_reason": "budget"}


def test_post_status_hold_requires_check_back(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/status", json={"deal_key": "x@acme.com", "status": "hold"})
    assert r.status_code == 400


def test_post_status_rejects_unknown_status(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/status", json={"deal_key": "x@acme.com", "status": "won"})
    assert r.status_code == 400


def test_post_status_rejects_non_string_deal_key(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/status", json={"deal_key": 12345, "status": "lost"})
    assert r.status_code == 400


def test_post_status_rejects_empty_deal_key(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/status", json={"deal_key": "", "status": "lost"})
    assert r.status_code == 400


def test_post_review_confirm_appends_manual_event(monkeypatch):
    srv, c = _client(monkeypatch, "")
    captured = {}

    def fake_write_main(mutate, msg_fn):
        store = srv._read_store()
        result = mutate(store)
        captured["dirty"] = store.dirty()
        return result, {"status": "ok"}, 200

    monkeypatch.setattr(srv, "_write_main", fake_write_main)
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "confirm"})
    assert r.status_code == 201
    ev = json.loads(captured["dirty"]["data/deal_events.jsonl"].strip().splitlines()[-1])
    assert ev["kind"] == "manual" and ev["payload"]["action"] == "confirm"


def test_post_review_choose_primary_requires_email(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/review", json={"deal_key": "info@acme.com", "action": "choose_primary"})
    assert r.status_code == 400


def test_post_review_merge_carries_merge_with(monkeypatch):
    srv, c = _client(monkeypatch, "")
    captured = {}
    monkeypatch.setattr(srv, "_write_main",
                        lambda mutate, msg_fn: (mutate(srv._read_store()), {"status": "ok"}, 200))
    # capture via a second call path: re-run mutate to inspect
    r = c.post("/api/deals/review", json={"deal_key": "b@beta.com", "action": "merge",
                                          "merge_with": "a@acme.com"})
    assert r.status_code == 201
    assert r.get_json()["event"]["payload"]["merge_with"] == "a@acme.com"


def test_post_review_rejects_unknown_action(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "frobnicate"})
    assert r.status_code == 400


def test_post_review_split_requires_groups(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "split"})
    assert r.status_code == 400


def test_post_review_split_rejects_empty_groups_list(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "split", "groups": []})
    assert r.status_code == 400


def test_post_review_rejects_non_string_deal_key(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/review", json={"deal_key": 12345, "action": "confirm"})
    assert r.status_code == 400


def test_post_review_rejects_empty_deal_key(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/review", json={"deal_key": "", "action": "confirm"})
    assert r.status_code == 400


def test_post_review_not_a_deal_appends_event(monkeypatch):
    srv, c = _client(monkeypatch, "")
    captured = {}

    def fake_write_main(mutate, msg_fn):
        store = srv._read_store()
        result = mutate(store)
        captured["dirty"] = store.dirty()
        return result, {"status": "ok"}, 200

    monkeypatch.setattr(srv, "_write_main", fake_write_main)
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "not_a_deal"})
    assert r.status_code == 201
    ev = json.loads(captured["dirty"]["data/deal_events.jsonl"].strip().splitlines()[-1])
    assert ev["payload"] == {"action": "not_a_deal"}


def test_post_review_split_carries_groups(monkeypatch):
    srv, c = _client(monkeypatch, "")
    monkeypatch.setattr(srv, "_write_main",
                        lambda mutate, msg_fn: (mutate(srv._read_store()), {"status": "ok"}, 200))
    groups = [["a@acme.com", "b@acme.com"], ["c@acme.com"]]
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "split",
                                          "groups": groups})
    assert r.status_code == 201
    assert r.get_json()["event"]["payload"]["groups"] == groups


def test_post_review_5xx_returns_error_no_phantom_success(monkeypatch):
    srv, c = _client(monkeypatch, "")
    monkeypatch.setattr(srv, "_write_main",
                        lambda mutate, msg_fn: (None, {"status": "push_failed"}, 502))
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "confirm"})
    assert r.status_code == 502
    body = r.get_json()
    assert "error" in body and "push" in body
