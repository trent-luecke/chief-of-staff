import json

from scout import teardown, backlog


def test_content_hash_stable_and_normalized():
    assert teardown.content_hash("  Hello  World ") == teardown.content_hash("hello world")
    assert teardown.content_hash("a") != teardown.content_hash("b")


class _FakeFC:
    def __init__(self, pages):  # pages: dict[url_substr] -> markdown
        self.pages = pages
    def scrape(self, url):
        for key, md in self.pages.items():
            if key in url:
                return md
        return None


_TEARDOWN_JSON = {
    "description": "Online coaching platform",
    "segment": "online coaches",
    "standout": "native-language localization",
    "features": ["workout builder", "meal planner"],
    "pricing": "EUR 69/mo",
    "traction": "self-reported 100+ coaches",
    "maturity": "polished early startup",
    "os_takeaways": [{"feature": "meal planner", "tag": "🚫 Out of scope", "note": "OS focuses on programming"}],
    "jtbd": {"platform_jtbd": "run whole coaching biz from one screen",
             "verdict": "📣 Positioning gap",
             "note": "OS also consolidates but doesn't say so",
             "quoted_line": "a client's whole week from one screen"},
    "is_platform": True,
}


class _ToolUseBlock:
    type = "tool_use"
    name = "emit_teardown"
    def __init__(self, data):
        self.input = data


def _fake_client(captured):
    class _Resp:
        content = [_ToolUseBlock(_TEARDOWN_JSON)]
    class _Msgs:
        def create(self, **k):
            captured.append(k)
            return _Resp()
    class _Client:
        messages = _Msgs()
    return _Client()


def test_analyze_returns_teardown_and_injects_grounding():
    cand = backlog.new_candidate("coachway.io", "Coachway", "https://coachway.io/", "B", "seed", "2026-08-06")
    fc = _FakeFC({"coachway.io": "# Coachway\nonline coaching for everyone"})
    captured = []
    client = _fake_client(captured)
    result = teardown.analyze(cand, fc, client, "OS_GROUNDING_MARKER")
    assert result["name"] == "Coachway"
    assert result["standout"] == "native-language localization"
    assert result["jtbd"]["verdict"] == "📣 Positioning gap"
    assert result["content_hash"]
    # grounding text MUST be present in the prompt sent to Claude
    sent = json.dumps(captured[0])
    assert "OS_GROUNDING_MARKER" in sent


def test_analyze_returns_none_when_scrape_fails():
    cand = backlog.new_candidate("dead.com", "Dead", "https://dead.com/", "A", "seed", "2026-08-06")
    fc = _FakeFC({})  # scrape returns None for everything
    result = teardown.analyze(cand, fc, _fake_client([]), "G")
    assert result is None


def _fake_client_returning_text(text, captured=None):
    captured = captured if captured is not None else []
    class _TextBlock:
        type = "text"
        def __init__(self, t):
            self.text = t
    class _Resp:
        content = [_TextBlock(text)]
    class _Msgs:
        def create(self, **k):
            captured.append(k)
            return _Resp()
    class _Client:
        messages = _Msgs()
    return _Client()


def test_analyze_returns_none_when_no_tool_use():
    cand = backlog.new_candidate("array.io", "Array", "https://array.io/", "A", "seed", "2026-08-06")
    fc = _FakeFC({"array.io": "# Array\nsome real markdown"})
    client = _fake_client_returning_text("sorry, I can't help with that")
    result = teardown.analyze(cand, fc, client, "G")
    assert result is None


def test_analyze_flags_non_platform():
    cand = backlog.new_candidate("listicle.com", "Listicle", "https://listicle.com/", "A", "seed", "2026-08-06")
    fc = _FakeFC({"listicle.com": "# Best Gym Apps 2026\na roundup of platforms"})
    non_platform_json = dict(_TEARDOWN_JSON, is_platform=False)

    class _Resp:
        content = [_ToolUseBlock(non_platform_json)]
    class _Msgs:
        def create(self, **k):
            return _Resp()
    class _Client:
        messages = _Msgs()

    result = teardown.analyze(cand, fc, _Client(), "G")
    assert result is not None
    assert result["is_platform"] is False
