# tests/test_fetch_rep_name.py
import collectors.avoma as av
from collectors.avoma import AvomaTranscript, DEMO_REP_ROSTER


def test_fetch_sets_rep_name_from_speakers(monkeypatch):
    meeting = {"uuid": "u1", "subject": "Acme demo", "start_at": "2026-06-10T15:00:00Z",
               "transcript_ready": True, "attendees": [{"name": "Acme", "email": "a@acme.com"}]}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"results": [meeting], "next": None}
    monkeypatch.setattr(av.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(av, "_fetch_transcript",
                        lambda key, uuid: ([{"name": "Ryan Allwein", "is_rep": True}], [{"speaker_id": "1", "transcript": "hi"}]))
    monkeypatch.setattr(av, "_analyze_with_claude",
                        lambda *a, **k: {"os_interested": True, "call_type": "demo", "summary": "s",
                                         "features_covered": [], "gaps": [], "objections": [],
                                         "buying_signals": [], "competitors": [],
                                         "onboarding_completed": [], "onboarding_next_steps": [], "action_items": []})

    out = av.fetch_recent_meetings("k", "ak", "m", lookback_hours=72,
                                   rep_roster=DEMO_REP_ROSTER, filter_internal=False)
    assert len(out) == 1
    assert out[0].rep_name == "Ryan Allwein"
