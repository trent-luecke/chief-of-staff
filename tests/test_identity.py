from lib import identity


def test_slugify_basic():
    assert identity.slugify("Trent Luecke") == "trent-luecke"
    assert identity.slugify("Patrick LaBat — TGMC") == "patrick-labat-tgmc"


def test_unique_id_appends_suffix():
    assert identity.unique_id("jane-smith", set()) == "jane-smith"
    assert identity.unique_id("jane-smith", {"jane-smith"}) == "jane-smith-2"
    assert identity.unique_id("jane-smith", {"jane-smith", "jane-smith-2"}) == "jane-smith-3"


def test_is_internal():
    assert identity.is_internal("q@teambuildr.com", ["teambuildr.com"]) is True
    assert identity.is_internal("lead@acme.com", ["teambuildr.com"]) is False
    assert identity.is_internal("", ["teambuildr.com"]) is False
    assert identity.is_internal("noatsign", ["teambuildr.com"]) is False


def test_name_from_email():
    assert identity.name_from_email("jane.smith@acme.com") == "Jane Smith"
    assert identity.name_from_email("mike_jones@x.io") == "Mike Jones"
    assert identity.name_from_email("bob@x.io") == "Bob"


def _people():
    return [
        {"id": "trent-luecke", "canonical_name": "Trent Luecke",
         "aliases": ["Trent Luecke", "trent@teambuildr.com", "Trent"],
         "email": "trent@teambuildr.com", "type": "internal"},
        {"id": "jane-smith", "canonical_name": "Jane Smith",
         "aliases": ["Jane Smith", "jane@acme.com"],
         "email": "jane@acme.com", "type": "lead"},
    ]


def test_build_lookup_indexes_emails_and_names():
    email_index, alias_list = identity.build_lookup(_people())
    assert email_index["trent@teambuildr.com"] == "trent-luecke"
    assert email_index["jane@acme.com"] == "jane-smith"
    assert ("trent-luecke", "trent") in alias_list


def test_find_by_email_case_insensitive():
    email_index, _ = identity.build_lookup(_people())
    assert identity.find_by_email("JANE@ACME.COM", email_index) == "jane-smith"
    assert identity.find_by_email("nobody@x.io", email_index) is None
    assert identity.find_by_email("", email_index) is None


def test_find_by_name_exact_and_fuzzy_and_miss():
    _, alias_list = identity.build_lookup(_people())
    assert identity.find_by_name("Jane Smith", alias_list)[0] == "jane-smith"
    # fuzzy: minor variation still clears threshold
    assert identity.find_by_name("Jane  Smith", alias_list)[0] == "jane-smith"
    # unrelated name → no match
    assert identity.find_by_name("Zachary Quinto", alias_list)[0] is None


def test_resolve_email_priority_then_name():
    email_index, alias_list = identity.build_lookup(_people())
    # email wins even if name is blank
    assert identity.resolve("", "jane@acme.com", email_index, alias_list) == "jane-smith"
    # falls back to name when email misses
    assert identity.resolve("Jane Smith", "unknown@x.io", email_index, alias_list) == "jane-smith"
    # total miss
    assert identity.resolve("Nobody", "nobody@x.io", email_index, alias_list) is None


def test_load_people_defaults_empty(tmp_path):
    from lib.storage import LocalStorage
    storage = LocalStorage(base_dir=str(tmp_path))
    assert identity.load_people(storage) == []
    storage.write_json("people_registry.json", {"version": 1, "people": _people()})
    assert len(identity.load_people(storage)) == 2
