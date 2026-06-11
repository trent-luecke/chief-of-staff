# tests/test_git_sync_commit.py
import subprocess
from pathlib import Path
import pytest
import lib.git_sync as gs


def _run(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A working repo whose origin is a local bare remote with a main branch."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _run(["git", "init", "--bare", "-b", "main", str(origin)], tmp_path)
    _run(["git", "init", "-b", "main", str(work)], tmp_path)
    _run(["git", "config", "user.email", "t@example.com"], work)
    _run(["git", "config", "user.name", "Test"], work)
    _run(["git", "remote", "add", "origin", str(origin)], work)
    # seed main with a data dir + a .gitignore that ignores data/secret.json
    (work / "data").mkdir()
    (work / "data" / "tasks.jsonl").write_text('{"id":"a"}\n')
    (work / ".gitignore").write_text("data/*\n!data/tasks.jsonl\n")
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "seed"], work)
    _run(["git", "push", "origin", "main"], work)
    monkeypatch.setattr(gs, "REPO_ROOT", work)
    return work


def _on_main(repo, rel):
    r = subprocess.run(["git", "show", f"origin/main:{rel}"],
                       cwd=str(repo), capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def test_commit_allowed_jsonl_unions_onto_main(repo):
    res = gs.commit_files_to_main({"data/tasks.jsonl": '{"id":"a"}\n{"id":"b"}\n'}, "add b")
    assert res["status"] == "ok"
    assert _on_main(repo, "data/tasks.jsonl") == '{"id":"a"}\n{"id":"b"}\n'


def test_commit_gitignored_file_returns_ignored_and_does_not_persist(repo):
    res = gs.commit_files_to_main({"data/secret.json": "{}"}, "try secret")
    assert res["status"] == "ignored"
    assert "secret.json" in res["detail"]
    assert _on_main(repo, "data/secret.json") is None  # nothing persisted


def test_commit_can_unignore_and_seed_in_one_commit(repo):
    # mirrors the real seeding: include an updated .gitignore that un-ignores the file
    files = {
        ".gitignore": "data/*\n!data/tasks.jsonl\n!data/secret.json\n",
        "data/secret.json": '{"seeded": true}',
    }
    res = gs.commit_files_to_main(files, "seed + unignore")
    assert res["status"] == "ok"
    assert _on_main(repo, "data/secret.json") == '{"seeded": true}'
    assert "!data/secret.json" in _on_main(repo, ".gitignore")


def test_no_orphan_worktree_after_commit(repo):
    gs.commit_files_to_main({"data/tasks.jsonl": '{"id":"a"}\n{"id":"c"}\n'}, "add c")
    wl = subprocess.run(["git", "worktree", "list"], cwd=str(repo), capture_output=True, text=True).stdout
    # only the main working tree should remain (no leftover temp worktree)
    assert wl.count("\n") == 1
