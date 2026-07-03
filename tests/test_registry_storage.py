"""registry_storage() — git-anchored store for registry entity files.

tasks.jsonl / notes.jsonl / projects_registry.json live on origin/main (written
by the Registry UI and the Slack /task //note workflows). Runtime jobs must read
them from the checked-out working tree, never from R2, regardless of
storage.r2.enabled.
"""
from lib.storage import registry_storage, LocalStorage


def test_registry_storage_is_local_even_when_r2_enabled(tmp_path):
    config = {
        "data_dir": str(tmp_path),
        "storage": {"r2": {"enabled": True, "bucket": "b", "account_id": "a"}},
    }
    s = registry_storage(config)
    assert isinstance(s, LocalStorage)
    assert str(s.base_dir) == str(tmp_path)


def test_registry_storage_defaults_to_data_dir():
    s = registry_storage({})
    assert isinstance(s, LocalStorage)
    assert str(s.base_dir) == "data"
