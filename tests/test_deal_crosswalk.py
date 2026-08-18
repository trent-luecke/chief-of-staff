from lib.storage import LocalStorage
from lib.deal_crosswalk import domain_to_name, load_crosswalk


def test_domain_to_name():
    assert domain_to_name("michael.hine@port-vale.co.uk") == "Port Vale"
    assert domain_to_name("a@acme.com") == "Acme"


def test_domain_to_name_blanks_free_email_domains():
    # Personal/free-email domains have no meaningful account name — leave blank
    # so the deal is flagged for a human to name (via crosswalk), not "Gmail".
    assert domain_to_name("jcook.tpa@gmail.com") == ""
    assert domain_to_name("x@yahoo.com") == ""
    assert domain_to_name("X@Outlook.com") == ""
    # corporate domains still resolve
    assert domain_to_name("a@acme.com") == "Acme"


def test_load_crosswalk_defaults_empty(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    assert load_crosswalk(s) == {}


def test_load_crosswalk_reads_overrides(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write_json("deal_crosswalk.json", {"a@acme.com": "Acme Barbell Co"})
    assert load_crosswalk(s)["a@acme.com"] == "Acme Barbell Co"
