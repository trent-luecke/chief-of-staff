from lib.email_norm import normalize_email


def test_lowercases_and_trims():
    assert normalize_email("  Coach@Acme.com ") == "coach@acme.com"


def test_strips_plus_tags():
    assert normalize_email("jane+demo@acme.com") == "jane@acme.com"


def test_drops_internal_domain():
    assert normalize_email("trent@teambuildr.com") is None


def test_rejects_empty_and_malformed():
    assert normalize_email("") is None
    assert normalize_email(None) is None
    assert normalize_email("not-an-email") is None
