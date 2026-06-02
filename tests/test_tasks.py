import pytest
from lib.storage import LocalStorage
from lib.tasks import add_task, get_open_tasks


def _storage(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_add_task_no_metadata(tmp_path):
    s = _storage(tmp_path)
    task = add_task(s, "Send deck")
    assert task["metadata"] == {}
    assert task["source"] == "telegram"


def test_add_task_with_metadata(tmp_path):
    s = _storage(tmp_path)
    meta = {"avoma_uuid": "uuid-abc", "thread_ts": "ts.123", "call_title": "Demo - Acme", "call_date": "2026-06-01"}
    task = add_task(s, "Follow up with Acme", source="avoma", metadata=meta)
    assert task["metadata"] == meta
    assert task["source"] == "avoma"


def test_add_task_metadata_persisted(tmp_path):
    s = _storage(tmp_path)
    meta = {"avoma_uuid": "uuid-xyz"}
    add_task(s, "Check in", source="avoma", metadata=meta)
    tasks = get_open_tasks(s)
    assert tasks[0]["metadata"] == meta
