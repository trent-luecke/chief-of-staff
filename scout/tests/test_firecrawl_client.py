from scout.firecrawl_client import FirecrawlClient


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_search_parses_results(monkeypatch):
    payload = {"data": [
        {"url": "https://a.com", "title": "A", "markdown": "# A"},
        {"url": "https://b.com", "title": "B", "markdown": "# B"},
    ]}
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(200, payload))
    fc = FirecrawlClient("key")
    results = fc.search("gym software", limit=2)
    assert [r["url"] for r in results] == ["https://a.com", "https://b.com"]


def test_search_returns_empty_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr("scout.firecrawl_client.requests.post", boom)
    fc = FirecrawlClient("key")
    assert fc.search("x") == []


def test_scrape_returns_markdown(monkeypatch):
    payload = {"data": {"markdown": "# Hello", "metadata": {}}}
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(200, payload))
    fc = FirecrawlClient("key")
    assert fc.scrape("https://a.com") == "# Hello"


def test_scrape_returns_none_on_error(monkeypatch):
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(500, {}))
    fc = FirecrawlClient("key")
    assert fc.scrape("https://a.com") is None


def test_scrape_with_links_parses_markdown_and_links(monkeypatch):
    payload = {"data": {"markdown": "# Home",
                        "links": ["https://a.com/pricing", "https://a.com/about"]}}
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(200, payload))
    fc = FirecrawlClient("key")
    md, links = fc.scrape_with_links("https://a.com/")
    assert md == "# Home"
    assert links == ["https://a.com/pricing", "https://a.com/about"]


def test_scrape_with_links_requests_links_format(monkeypatch):
    captured = {}

    def fake_post(*a, **k):
        captured.update(k.get("json", {}))
        return _FakeResp(200, {"data": {"markdown": "x", "links": []}})

    monkeypatch.setattr("scout.firecrawl_client.requests.post", fake_post)
    FirecrawlClient("key").scrape_with_links("https://a.com/")
    assert "markdown" in captured["formats"]
    assert "links" in captured["formats"]


def test_scrape_with_links_returns_empty_on_error(monkeypatch):
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(500, {}))
    fc = FirecrawlClient("key")
    md, links = fc.scrape_with_links("https://a.com/")
    assert md is None
    assert links == []


def test_scrape_with_links_tolerates_missing_links_key(monkeypatch):
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(200, {"data": {"markdown": "# H"}}))
    fc = FirecrawlClient("key")
    md, links = fc.scrape_with_links("https://a.com/")
    assert md == "# H"
    assert links == []


def test_search_retries_on_429(monkeypatch):
    calls = []
    payload = {"data": [{"url": "https://a.com", "title": "A", "markdown": "# A"}]}

    def fake_post(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResp(429, {})
        return _FakeResp(200, payload)

    monkeypatch.setattr("scout.firecrawl_client.requests.post", fake_post)
    monkeypatch.setattr("scout.firecrawl_client.time.sleep", lambda s: None)
    fc = FirecrawlClient("key")
    results = fc.search("gym software")
    assert len(calls) == 2
    assert [r["url"] for r in results] == ["https://a.com"]
