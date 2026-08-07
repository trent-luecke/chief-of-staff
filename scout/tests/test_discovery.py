from scout import discovery, backlog


def test_extract_domain_strips_www_and_path():
    assert discovery.extract_domain("https://www.Coachway.io/pricing?x=1") == "coachway.io"
    assert discovery.extract_domain("http://xoda.com") == "xoda.com"


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


def _fake_client_scoring(novelty, icp):
    class _Resp:
        content = [type("C", (), {"text": f'{{"novelty": {novelty}, "icp": {icp}}}'})()]
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
    assert discovery.score_candidate(_Client(), "n", "u", "s", "G") == (0.0, 0.0)


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
