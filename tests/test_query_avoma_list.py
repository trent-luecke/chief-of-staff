import importlib.util
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "query_avoma", Path(__file__).resolve().parent.parent / ".claude/skills/query-avoma/query_avoma.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


def _resp(payload):
    return SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)


def test_list_follows_pagination(monkeypatch, capsys):
    page1 = {"results": [{"subject": "Other gym demo", "start_at": "2026-08-01", "uuid": "u1",
                          "attendees": [{"name": "X", "email": "x@other.com"}]}],
             "next": "https://api.avoma.com/v1/meetings?page=2"}
    page2 = {"results": [{"subject": "Example demo", "start_at": "2026-08-07", "uuid": "u2",
                          "attendees": [{"name": "Pat", "email": "owner@examplegym.com"}]}],
             "next": None}
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _resp(page1 if len(calls) == 1 else page2)

    monkeypatch.setattr(qa.requests, "get", fake_get)
    monkeypatch.setattr(qa, "_headers", lambda: {})
    qa.cmd_list(Namespace(date=None, from_date="2026-02-10T00:00:00Z", to_date="2026-08-16T23:59:59Z",
                          title=None, attendee="owner@examplegym.com"))
    out = capsys.readouterr().out
    assert len(calls) == 2 and "Example demo" in out and out.startswith("1 meeting(s)")


def test_list_waits_and_retries_on_429(monkeypatch, capsys):
    ok = {"results": [{"subject": "Example demo", "start_at": "2026-08-07", "uuid": "u2",
                       "attendees": [{"name": "Pat", "email": "owner@examplegym.com"}]}], "next": None}
    limited = SimpleNamespace(status_code=429, headers={"Retry-After": "2"}, json=lambda: {},
                              raise_for_status=lambda: (_ for _ in ()).throw(AssertionError("raised on 429")))
    seq = [limited, SimpleNamespace(status_code=200, headers={}, json=lambda: ok, raise_for_status=lambda: None)]
    slept = []
    monkeypatch.setattr(qa.requests, "get", lambda url, **kw: seq.pop(0))
    monkeypatch.setattr(qa, "_headers", lambda: {})
    monkeypatch.setattr(qa.time, "sleep", lambda s: slept.append(s))
    qa.cmd_list(Namespace(date=None, from_date="a", to_date="b", title=None, attendee="examplegym"))
    assert slept == [2] and "Example demo" in capsys.readouterr().out


def test_list_asks_for_big_pages(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(qa.requests, "get", lambda url, **kw: (seen.append(kw.get("params")), _resp({"results": [], "next": None}))[1])
    monkeypatch.setattr(qa, "_headers", lambda: {})
    qa.cmd_list(Namespace(date=None, from_date="a", to_date="b", title=None, attendee=None))
    assert seen[0]["page_size"] == 100


def test_transcript_without_recording_says_so_instead_of_crashing(monkeypatch, capsys):
    meeting = {"subject": "Demo", "start_at": "s", "end_at": "e", "attendees": []}
    missing = SimpleNamespace(status_code=404, json=lambda: {"message": "Transcription not found"})
    seq = [SimpleNamespace(status_code=200, json=lambda: meeting), missing]
    monkeypatch.setattr(qa.requests, "get", lambda url, **kw: seq.pop(0))
    monkeypatch.setattr(qa, "_headers", lambda: {})
    qa.cmd_transcript(Namespace(uuid="u1"))
    assert "No transcript for this meeting" in capsys.readouterr().out
