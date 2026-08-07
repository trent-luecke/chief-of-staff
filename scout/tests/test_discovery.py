from scout import discovery, backlog


def test_extract_domain_strips_www_and_path():
    assert discovery.extract_domain("https://www.Coachway.io/pricing?x=1") == "coachway.io"
    assert discovery.extract_domain("http://xoda.com") == "xoda.com"


def test_extract_domain_collapses_subdomains():
    assert discovery.extract_domain("https://portal.gymcatch.com/x") == "gymcatch.com"
    assert discovery.extract_domain("https://learn.goteamup.com") == "goteamup.com"
    assert discovery.extract_domain("https://blog.trainerize.com/x") == "trainerize.com"
    assert discovery.extract_domain("https://app.foo.co.uk") == "foo.co.uk"


def test_is_excluded_substring():
    ex = ["mindbody", "trainerize"]
    assert discovery.is_excluded("app.mindbody.com", ex) is True
    assert discovery.is_excluded("coachway.io", ex) is False


class _FakeFC:
    def __init__(self, results):
        self._results = results
    def search(self, query, limit=8):
        return self._results
    def scrape(self, url):
        return None


def _fake_client_scoring(novelty, icp, is_platform=True):
    class _Resp:
        content = [type("C", (), {"text": (
            f'{{"novelty": {novelty}, "icp": {icp}, '
            f'"is_platform": {"true" if is_platform else "false"}}}'
        )})()]
    class _Msgs:
        def create(self, **k): return _Resp()
    class _Client:
        messages = _Msgs()
    return _Client()


def test_run_discovery_adds_new_scored_filtered(monkeypatch):
    fc = _FakeFC([
        {"url": "https://coachway.io/", "title": "Coachway", "markdown": "online coaching"},
        {"url": "https://mindbody.com/", "title": "Mindbody", "markdown": "big incumbent"},
        {"url": "https://coachway.io/pricing", "title": "dup", "markdown": "dup"},
    ])
    client = _fake_client_scoring(0.8, 0.7)
    cfg = {"search_queries": ["q"], "search_limit": 8, "exclude_domains": ["mindbody"]}
    records = []
    added = discovery.run_discovery(cfg, records, fc, client, "GROUNDING", "2026-08-06")
    assert added == 1                                  # mindbody excluded, dup collapsed
    assert records[0]["domain"] == "coachway.io"
    assert records[0]["novelty_score"] == 0.8
    assert records[0]["icp_relevance"] == 0.7


def test_run_discovery_skips_already_known(monkeypatch):
    fc = _FakeFC([{"url": "https://coachway.io/", "title": "C", "markdown": "x"}])
    client = _fake_client_scoring(0.5, 0.5)
    cfg = {"search_queries": ["q"], "search_limit": 8, "exclude_domains": []}
    records = [backlog.new_candidate("coachway.io", "C", "https://coachway.io/", "B", "seed", "2026-08-01")]
    added = discovery.run_discovery(cfg, records, fc, client, "G", "2026-08-06")
    assert added == 0


def test_score_candidate_handles_bad_json():
    class _Resp:
        content = [type("C", (), {"text": "not json"})()]
    class _Msgs:
        def create(self, **k): return _Resp()
    class _Client:
        messages = _Msgs()
    assert discovery.score_candidate(_Client(), "n", "u", "s", "G") == {
        "novelty": 0.0, "icp": 0.0, "is_platform": True,
    }


def test_score_candidate_returns_dict_with_is_platform():
    client = _fake_client_scoring(0.8, 0.7, is_platform=True)
    score = discovery.score_candidate(client, "n", "u", "s", "G")
    assert score["novelty"] == 0.8
    assert score["icp"] == 0.7
    assert score["is_platform"] is True


def test_run_discovery_drops_aggregator_hosts(monkeypatch):
    fc = _FakeFC([
        {"url": "https://producthunt.com/posts/coachway", "title": "Coachway on PH", "markdown": "launch post"},
        {"url": "https://coachway.io/", "title": "Coachway", "markdown": "online coaching"},
    ])
    client = _fake_client_scoring(0.8, 0.7)
    cfg = {"search_queries": ["q"], "search_limit": 8, "exclude_domains": []}
    records = []
    added = discovery.run_discovery(cfg, records, fc, client, "GROUNDING", "2026-08-06")
    assert added == 1
    assert records[0]["domain"] == "coachway.io"


def test_meta_boost_never_raises(monkeypatch):
    class _BoomFC:
        def scrape(self, url): raise RuntimeError("blocked")
        def search(self, *a, **k): raise RuntimeError("blocked")
    cfg = {"meta_ad_library_queries": ["gym software"]}
    # must swallow and return 0, never propagate
    assert discovery.meta_ad_library_boost(cfg, [], _BoomFC(), "2026-08-06") == 0


def test_looks_like_article():
    assert discovery.looks_like_article("https://x.com/blog/best-gym-software-2022") is True
    assert discovery.looks_like_article(
        "https://x.com/", "The Best Gym Management Software: Our 2022 Review"
    ) is True
    assert discovery.looks_like_article("https://x.com/reviews/foo") is True
    assert discovery.looks_like_article("https://coachway.io/") is False
    assert discovery.looks_like_article("https://gymdesk.com/pricing") is False


def test_run_discovery_skips_articles(monkeypatch):
    fc = _FakeFC([
        {"url": "https://blog.example.com/best-gym-apps-2023",
         "title": "Best Gym Apps 2023", "markdown": "roundup"},
        {"url": "https://coachway.io/", "title": "Coachway", "markdown": "online coaching"},
    ])
    client = _fake_client_scoring(0.8, 0.7, is_platform=True)
    cfg = {"search_queries": ["q"], "search_limit": 8, "exclude_domains": []}
    records = []
    added = discovery.run_discovery(cfg, records, fc, client, "GROUNDING", "2026-08-06")
    assert added == 1
    assert records[0]["domain"] == "coachway.io"


def test_run_discovery_drops_non_platform(monkeypatch):
    fc = _FakeFC([
        {"url": "https://somesite.com/", "title": "Some Site", "markdown": "a normal looking url"},
    ])
    client = _fake_client_scoring(0.8, 0.7, is_platform=False)
    cfg = {"search_queries": ["q"], "search_limit": 8, "exclude_domains": []}
    records = []
    added = discovery.run_discovery(cfg, records, fc, client, "GROUNDING", "2026-08-06")
    assert added == 0
    assert records == []


def test_rebuild_backlog():
    records = [
        backlog.new_candidate("reddit.com", "Reddit", "https://reddit.com/r/fitness",
                              "A", "websearch", "2026-08-01"),
        backlog.new_candidate("portal.gymcatch.com", "GymCatch", "https://portal.gymcatch.com/x",
                              "A", "websearch", "2026-08-01"),
        backlog.new_candidate("coachway.io", "Coachway", "https://coachway.io/blog/x",
                              "A", "websearch", "2026-08-01"),
        backlog.new_candidate("obscure-newco.io", "Obscure Newco", "https://obscure-newco.io/",
                              "A", "websearch", "2026-08-01"),
        backlog.new_candidate("done.com", "Done", "https://done.com/",
                              "A", "websearch", "2026-07-01"),
    ]
    records[4]["covered"] = True
    records[4]["url"] = "https://blog.done.com/should-not-change"

    # dedup case: a second uncovered entry collapsing to the same domain as coachway.io
    records.append(backlog.new_candidate("coachway.io", "Coachway dup", "https://www.coachway.io/pricing",
                                          "A", "websearch", "2026-08-02"))

    kept, dropped = discovery.rebuild_backlog(records, exclude=["reddit"])

    by_domain = {r["domain"]: r for r in records}
    assert "reddit.com" not in by_domain
    assert by_domain["gymcatch.com"]["url"] == "https://gymcatch.com/"
    assert by_domain["gymcatch.com"]["domain"] == "gymcatch.com"
    assert "coachway.io" in by_domain
    # obscure/unrecognized-brand domains are KEPT — no name-judging happens here anymore
    assert "obscure-newco.io" in by_domain
    assert by_domain["done.com"]["covered"] is True
    assert by_domain["done.com"]["url"] == "https://blog.done.com/should-not-change"  # covered untouched

    # dedup: only one coachway.io survives
    assert sum(1 for r in records if r["domain"] == "coachway.io") == 1

    assert dropped == 2  # reddit (excluded), dup coachway
    assert kept == len(records)


def test_prune_articles():
    records = [
        backlog.new_candidate("blogsite.com", "Best Gym Software Review 2022", "https://blogsite.com/",
                              "A", "websearch", "2026-08-01"),
        backlog.new_candidate("coachway.io", "Coachway", "https://coachway.io/",
                              "A", "websearch", "2026-08-01"),
        backlog.new_candidate("oldarticle.com", "Best Gym Software Review 2022", "https://oldarticle.com/",
                              "A", "websearch", "2026-07-01"),
    ]
    records[2]["covered"] = True
    removed = discovery.prune_articles(records)
    assert removed == 1
    domains = {r["domain"] for r in records}
    assert domains == {"coachway.io", "oldarticle.com"}
