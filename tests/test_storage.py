import json
import pytest
from lib.storage import LocalStorage, build_storage, storage_key


def test_read_write_roundtrip(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write("foo/bar.txt", "hello")
    assert s.read("foo/bar.txt") == "hello"
    assert (tmp_path / "foo" / "bar.txt").exists()


def test_read_missing_returns_none(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    assert s.read("missing.json") is None


def test_exists(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    assert not s.exists("foo.json")
    s.write("foo.json", "{}")
    assert s.exists("foo.json")


def test_delete(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write("x.txt", "data")
    s.delete("x.txt")
    assert not s.exists("x.txt")


def test_delete_missing_is_noop(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.delete("does_not_exist.txt")  # must not raise


def test_list_keys(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write("dir/a.txt", "a")
    s.write("dir/b.txt", "b")
    assert sorted(s.list_keys("dir")) == ["dir/a.txt", "dir/b.txt"]


def test_list_keys_missing_prefix(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    assert s.list_keys("nonexistent") == []


def test_read_write_binary(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write_binary("bin/data.bin", b"\x00\x01\x02")
    assert s.read_binary("bin/data.bin") == b"\x00\x01\x02"


def test_read_binary_missing(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    assert s.read_binary("missing.bin") is None


def test_read_json(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write("d.json", '{"k": 1}')
    assert s.read_json("d.json") == {"k": 1}


def test_read_json_missing_returns_default(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    assert s.read_json("missing.json", default=[]) == []


def test_read_json_corrupt_returns_default(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write("bad.json", "not-json")
    assert s.read_json("bad.json", default=42) == 42


def test_write_json(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.write_json("d.json", {"a": 1})
    assert json.loads((tmp_path / "d.json").read_text()) == {"a": 1}


def test_append_line(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.append_line("log.jsonl", '{"a":1}')
    s.append_line("log.jsonl", '{"b":2}')
    lines = (tmp_path / "log.jsonl").read_text().strip().split("\n")
    assert lines == ['{"a":1}', '{"b":2}']


def test_append_line_creates_file(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    s.append_line("new.jsonl", "first")
    assert (tmp_path / "new.jsonl").read_text() == "first\n"


def test_storage_key_strips_prefix():
    assert storage_key("data/foo/bar.json") == "foo/bar.json"
    assert storage_key("data/state/health.json") == "state/health.json"
    assert storage_key("foo/bar.json") == "foo/bar.json"  # no prefix → unchanged


def test_build_storage_returns_local_when_r2_disabled(tmp_path):
    config = {"storage": {"r2": {"enabled": False}}, "data_dir": str(tmp_path)}
    assert isinstance(build_storage(config), LocalStorage)


def test_build_storage_returns_local_when_no_storage_config(tmp_path):
    config = {"data_dir": str(tmp_path)}
    assert isinstance(build_storage(config), LocalStorage)


def test_local_storage_base_dir_is_data_by_default():
    s = LocalStorage()
    assert str(s.base_dir) == "data"
