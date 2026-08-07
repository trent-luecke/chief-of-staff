import scout.scout as scout
from scout import backlog


def test_seed_adds_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(scout.config, "CANDIDATES_FILE", tmp_path / "c.jsonl")
    assert scout.seed("https://xoda.com/pricing", today="2026-08-06") is True
    recs = backlog.load(tmp_path / "c.jsonl")
    assert recs[0]["domain"] == "xoda.com"
    assert recs[0]["seed"] is True


def test_run_weekly_selects_analyzes_marks_and_sends(tmp_path, monkeypatch):
    monkeypatch.setattr(scout.config, "CANDIDATES_FILE", tmp_path / "c.jsonl")
    monkeypatch.setattr(scout.config, "COVERED_FILE", tmp_path / "cov.jsonl")
    monkeypatch.setattr(scout.config, "BRIEFS_DIR", tmp_path / "briefs")

    # pre-stock backlog with two uncovered candidates
    recs = [backlog.new_candidate(f"p{i}.com", f"P{i}", f"https://p{i}.com/", "A", "seed", "2026-08-01")
            for i in range(2)]
    backlog.save(recs, tmp_path / "c.jsonl")

    monkeypatch.setattr(scout, "_firecrawl", lambda: object())
    monkeypatch.setattr(scout, "_anthropic", lambda: object())
    monkeypatch.setattr(scout.discovery, "run_discovery", lambda *a, **k: 0)
    monkeypatch.setattr(scout.discovery, "meta_ad_library_boost", lambda *a, **k: 0)
    monkeypatch.setattr(scout.config, "load_grounding", lambda: "G")

    def fake_analyze(cand, fc, client, grounding):
        return {"name": cand["name"], "url": cand["url"], "bucket": "A",
                "content_hash": "h_" + cand["domain"], "standout": "x",
                "features": [], "os_takeaways": [], "jtbd": {}}
    monkeypatch.setattr(scout.teardown, "analyze", fake_analyze)

    sent = {}
    monkeypatch.setattr(scout.emailer, "send_email",
                        lambda subj, body, recip=None: sent.update(subj=subj) or True)

    result = scout.run_weekly(dry_run=False, today="2026-08-07")
    assert result["teardowns"] == 2
    assert result["sent"] is True

    covered = [r for r in backlog.load(tmp_path / "c.jsonl") if r["covered"]]
    assert len(covered) == 2                       # both marked covered
    assert covered[0]["content_hash"].startswith("h_")


def test_run_weekly_dry_run_does_not_send(tmp_path, monkeypatch):
    monkeypatch.setattr(scout.config, "CANDIDATES_FILE", tmp_path / "c.jsonl")
    monkeypatch.setattr(scout.config, "COVERED_FILE", tmp_path / "cov.jsonl")
    monkeypatch.setattr(scout.config, "BRIEFS_DIR", tmp_path / "briefs")
    backlog.save([backlog.new_candidate("p.com", "P", "https://p.com/", "A", "seed", "2026-08-01")],
                 tmp_path / "c.jsonl")
    monkeypatch.setattr(scout, "_firecrawl", lambda: object())
    monkeypatch.setattr(scout, "_anthropic", lambda: object())
    monkeypatch.setattr(scout.discovery, "run_discovery", lambda *a, **k: 0)
    monkeypatch.setattr(scout.discovery, "meta_ad_library_boost", lambda *a, **k: 0)
    monkeypatch.setattr(scout.config, "load_grounding", lambda: "G")
    monkeypatch.setattr(scout.teardown, "analyze",
                        lambda c, *a: {"name": c["name"], "url": c["url"], "bucket": "A",
                                       "content_hash": "h", "features": [], "os_takeaways": [], "jtbd": {}})
    called = {"sent": False}
    monkeypatch.setattr(scout.emailer, "send_email",
                        lambda *a, **k: called.update(sent=True) or True)
    result = scout.run_weekly(dry_run=True, today="2026-08-07")
    assert called["sent"] is False
    assert result["sent"] is False


def test_run_weekly_survives_a_raising_analyze(tmp_path, monkeypatch):
    monkeypatch.setattr(scout.config, "CANDIDATES_FILE", tmp_path / "c.jsonl")
    monkeypatch.setattr(scout.config, "COVERED_FILE", tmp_path / "cov.jsonl")
    monkeypatch.setattr(scout.config, "BRIEFS_DIR", tmp_path / "briefs")

    # pre-stock backlog with two uncovered candidates
    recs = [backlog.new_candidate(f"p{i}.com", f"P{i}", f"https://p{i}.com/", "A", "seed", "2026-08-01")
            for i in range(2)]
    backlog.save(recs, tmp_path / "c.jsonl")

    monkeypatch.setattr(scout, "_firecrawl", lambda: object())
    monkeypatch.setattr(scout, "_anthropic", lambda: object())
    monkeypatch.setattr(scout.discovery, "run_discovery", lambda *a, **k: 0)
    monkeypatch.setattr(scout.discovery, "meta_ad_library_boost", lambda *a, **k: 0)
    monkeypatch.setattr(scout.config, "load_grounding", lambda: "G")

    def flaky_analyze(cand, fc, client, grounding):
        if cand["domain"] == "p0.com":
            raise ValueError("Claude returned non-dict JSON")
        return {"name": cand["name"], "url": cand["url"], "bucket": "A",
                "content_hash": "h_" + cand["domain"], "standout": "x",
                "features": [], "os_takeaways": [], "jtbd": {}}
    monkeypatch.setattr(scout.teardown, "analyze", flaky_analyze)

    sent = {}
    monkeypatch.setattr(scout.emailer, "send_email",
                        lambda subj, body, recip=None: sent.update(subj=subj) or True)

    result = scout.run_weekly(dry_run=False, today="2026-08-07")
    assert result["teardowns"] == 1
    assert result["sent"] is True

    recs = backlog.load(tmp_path / "c.jsonl")
    by_domain = {r["domain"]: r for r in recs}
    assert by_domain["p0.com"]["covered"] is False
    assert by_domain["p1.com"]["covered"] is True


def test_main_returns_1_when_send_fails(monkeypatch):
    monkeypatch.setattr(scout, "run_weekly",
                        lambda *a, **k: {"discovered": 0, "teardowns": 1, "sent": False})
    assert scout.main([]) == 1


def test_main_returns_0_when_sent(monkeypatch):
    monkeypatch.setattr(scout, "run_weekly",
                        lambda *a, **k: {"discovered": 0, "teardowns": 1, "sent": True})
    assert scout.main([]) == 0


def test_run_weekly_survives_discovery_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(scout.config, "CANDIDATES_FILE", tmp_path / "c.jsonl")
    monkeypatch.setattr(scout.config, "COVERED_FILE", tmp_path / "cov.jsonl")
    monkeypatch.setattr(scout.config, "BRIEFS_DIR", tmp_path / "briefs")

    # pre-stock backlog with one uncovered candidate
    recs = [backlog.new_candidate("p0.com", "P0", "https://p0.com/", "A", "seed", "2026-08-01")]
    backlog.save(recs, tmp_path / "c.jsonl")

    monkeypatch.setattr(scout, "_firecrawl", lambda: object())
    monkeypatch.setattr(scout, "_anthropic", lambda: object())

    def raising_discovery(*a, **k):
        raise RuntimeError("discovery API down")
    monkeypatch.setattr(scout.discovery, "run_discovery", raising_discovery)
    monkeypatch.setattr(scout.discovery, "meta_ad_library_boost", lambda *a, **k: 0)
    monkeypatch.setattr(scout.config, "load_grounding", lambda: "G")

    def fake_analyze(cand, fc, client, grounding):
        return {"name": cand["name"], "url": cand["url"], "bucket": "A",
                "content_hash": "h_" + cand["domain"], "standout": "x",
                "features": [], "os_takeaways": [], "jtbd": {}}
    monkeypatch.setattr(scout.teardown, "analyze", fake_analyze)

    sent = {}
    monkeypatch.setattr(scout.emailer, "send_email",
                        lambda subj, body, recip=None: sent.update(subj=subj) or True)

    result = scout.run_weekly(dry_run=False, today="2026-08-07")
    assert result["discovered"] == 0
    assert result["teardowns"] == 1
    assert result["sent"] is True

    covered = [r for r in backlog.load(tmp_path / "c.jsonl") if r["covered"]]
    assert len(covered) == 1
