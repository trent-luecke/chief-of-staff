from scout import emailer

_TD = {
    "name": "Coachway", "url": "https://coachway.io/", "bucket": "B",
    "description": "Online coaching platform", "segment": "online coaches",
    "standout": "native-language localization",
    "features": ["workout builder", "meal planner"],
    "pricing": "EUR 69/mo", "traction": "100+ coaches (self-reported)",
    "maturity": "polished early startup",
    "os_takeaways": [{"feature": "meal planner", "tag": "🚫 Out of scope", "note": "OS focuses on programming"}],
    "jtbd": {"platform_jtbd": "run whole biz from one screen", "verdict": "📣 Positioning gap",
             "note": "OS consolidates but doesn't market it", "quoted_line": "whole week from one screen"},
}


def test_format_email_includes_standout_tags_and_jtbd():
    subject, body = emailer.format_email([_TD], "2026-08-07")
    assert "Coachway" in subject
    assert "native-language localization" in body     # standout headline
    assert "🚫 Out of scope" in body                   # taxonomy tag rendered
    assert "📣 Positioning gap" in body                # jtbd verdict rendered
    assert "whole week from one screen" in body        # quoted positioning line
    assert "<" in body and ">" in body                 # HTML


def test_format_email_empty_is_honest_not_blank():
    subject, body = emailer.format_email([], "2026-08-07")
    assert "no new" in body.lower() or "no fresh" in body.lower()
    assert len(body) > 0


def test_send_email_skips_without_password(monkeypatch):
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert emailer.send_email("s", "<p>b</p>", "trent@teambuildr.com") is False


def test_format_email_survives_null_fields():
    td = {
        "name": "Nullify", "url": "https://nullify.io/", "bucket": "A",
        "description": "desc", "segment": "seg", "standout": "wedge",
        "pricing": None, "traction": None, "maturity": "early",
        "features": None,
        "os_takeaways": None,
        "jtbd": None,
    }
    subject, body = emailer.format_email([td], "2026-08-07")
    assert subject
    assert body
