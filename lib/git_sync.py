# lib/git_sync.py
"""Git plumbing for the registry UI: read/write data files on origin/main.

The UI treats origin/main as the single source of truth. Reads come from the
committed blob (git show); writes land on main via a throwaway worktree, never
touching the user's checked-out branch.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
_TIMEOUT = 8


def _union_merge_lines(existing: str, incoming: str) -> str:
    """Return existing lines plus any incoming lines not already present, order-preserving.

    Used for append-only *.jsonl files so a concurrent writer's lines are never lost.
    """
    existing_lines = [l for l in existing.splitlines() if l.strip()]
    seen = set(existing_lines)
    merged = existing_lines + [l for l in incoming.splitlines() if l.strip() and l not in seen]
    return "\n".join(merged) + ("\n" if merged else "")


def fetch_main(timeout: int = _TIMEOUT) -> bool:
    """Update the local origin/main ref. Return True if reachable, False if offline."""
    try:
        r = subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(REPO_ROOT), capture_output=True, timeout=timeout,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def show_main(repo_rel_path: str) -> Optional[str]:
    """Return the content of repo_rel_path on origin/main, or None if absent/unreadable."""
    try:
        r = subprocess.run(
            ["git", "show", f"origin/main:{repo_rel_path}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def prune_worktrees() -> None:
    """Remove orphaned worktrees left by a hard crash. Best-effort."""
    try:
        subprocess.run(["git", "worktree", "prune"], cwd=str(REPO_ROOT), capture_output=True)
    except OSError:
        pass


def commit_files_to_main(files: dict, msg: str) -> dict:
    """Commit {repo_rel_path: content} to origin/main via a temp worktree, then push.

    *.jsonl files are union-merged with main's current lines (concurrency-safe);
    other files are overwritten. Never touches the checked-out branch.
    """
    if not files:
        return {"status": "ok", "detail": "no changes"}
    repo = str(REPO_ROOT)
    try:
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=repo, check=True, capture_output=True, timeout=_TIMEOUT,
        )
        with tempfile.TemporaryDirectory() as tmp:
            wt = tmp + "/wt"
            subprocess.run(
                ["git", "worktree", "add", "--detach", wt, "origin/main"],
                cwd=repo, check=True, capture_output=True,
            )
            try:
                for rel, content in files.items():
                    target = Path(wt) / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if rel.endswith(".jsonl"):
                        existing = target.read_text() if target.exists() else ""
                        target.write_text(_union_merge_lines(existing, content))
                    else:
                        target.write_text(content)
                subprocess.run(["git", "add"] + list(files.keys()), cwd=wt, check=True, capture_output=True)
                commit = subprocess.run(["git", "commit", "-m", msg], cwd=wt, capture_output=True, text=True)
                if commit.returncode != 0:
                    out = (commit.stdout + commit.stderr).strip()
                    if "nothing to commit" in out:
                        return {"status": "ok", "detail": "already up to date"}
                    return {"status": "commit_failed", "detail": out}
                push = subprocess.run(
                    ["git", "push", "origin", "HEAD:refs/heads/main"],
                    cwd=wt, capture_output=True, text=True,
                )
                if push.returncode != 0:
                    return {"status": "push_failed", "detail": push.stderr.strip()}
            finally:
                subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo, capture_output=True)
        return {"status": "ok", "detail": "committed and pushed to main"}
    except subprocess.TimeoutExpired:
        return {"status": "offline", "detail": "git fetch timed out"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
