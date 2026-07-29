import pipeline


def test_email_disabled_by_config_default():
    # default config (no brief.email_enabled) -> disabled
    assert pipeline._email_enabled({}) is False
    assert pipeline._email_enabled({"brief": {}}) is False
    assert pipeline._email_enabled({"brief": {"email_enabled": False}}) is False


def test_email_enabled_when_config_true():
    assert pipeline._email_enabled({"brief": {"email_enabled": True}}) is True
