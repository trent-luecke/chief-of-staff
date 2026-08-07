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
