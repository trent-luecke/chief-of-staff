# R2 Storage Abstraction — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `StorageBackend` abstraction over all `data/` runtime-state file I/O, defaulting to `LocalStorage` (zero behavior change), so a future Phase 2 PR can flip `r2.enabled: true` to move state out of git into Cloudflare R2.

**Architecture:** A `StorageBackend` protocol with `LocalStorage` and `R2Storage` implementations lives in `lib/storage.py`. A `build_storage(config)` factory is called once in each entry point and passed through the call chain. Every module that reads/writes runtime state under `data/` receives `storage` as a parameter. Human-authored files (`data/people/`, `data/projects.md`, `data/recurring.json`, `data/meeting_index.json`, `data/memory/decisions.md`) keep using raw `open()`. The `output/dashboard.html` file is not under `data/` so it also keeps raw `open()`.

**Tech Stack:** Python, boto3 (S3-compatible R2 client), python-frontmatter (already in requirements).

---

## File Structure

**New files:**
- `lib/storage.py` — StorageBackend protocol, LocalStorage, R2Storage, build_storage factory, storage_key helper
- `tests/test_storage.py` — Unit tests for LocalStorage and helpers

**Modified files — leaf modules (no entry-point dependencies):**
- `processors/state.py` — accept `storage` instead of `state_dir: str`
- `processors/issues.py` — accept `storage` instead of `issues_file: str`
- `lib/llm_logger.py` — `flush(run_type, storage)` instead of `(run_type, log_file)`
- `lib/captures.py` — runtime-state functions accept `storage`; `complete_project_next` keeps raw `open()`
- `processors/feedback.py` — `append_brief_feedback(storage, note)` instead of `(feedback_file, note)`
- `processors/brief_scorer.py` — `save_score(score, note, storage)`, `handle_score_command(query, storage)`
- `processors/retrieval_logger.py` — `log_retrieval(storage, ...)` instead of `(log_file, ...)`
- `lib/pipeline_activity.py` — all functions accept `storage` instead of path strings
- `processors/memory_observer.py` — all functions accept `storage`; `decisions.md` keeps raw `open()`
- `processors/memory_synthesizer.py` — accept `storage`; replace `Path.glob` + `shutil.move` with storage calls
- `processors/memory_retriever.py` — use `storage.list_keys` + `storage.read`
- `processors/retrieval_digest.py` — `load_scores(storage, since)`, `load_retrieval_logs(storage, since)`, `generate_digest(storage, ...)`
- `processors/weekly_synthesizer.py` — accept `storage`; reads obs + state through storage
- `processors/drafts.py` — `save_draft(draft, storage)`, `load_todays_drafts(storage)`
- `processors/vector_ingest.py` — all I/O through storage
- `processors/meeting_memory.py` — `load_meeting_index` stays raw; `append_session_notes` and `load_last_session_summary` accept `storage, key`
- `processors/meeting_prep.py` — `load_prep_state(storage)`, `save_prep_state(keys, storage)` with key `meeting_preps.json`
- `processors/query_tools.py` — pass `storage` to captures and issues calls

**Modified files — entry points:**
- `config.json` — add `storage.r2` block
- `requirements.txt` — add boto3
- `main.py` — build storage, pass through; replace health file write
- `pipeline.py` — update all function signatures; replace direct `open()` calls for pipeline cache, brief_message_id idempotency check
- `watcher.py` — build storage; replace watcher_state read/write
- `check_replies.py` — build storage; `load_brief_state`, `save_brief_state` use storage
- `ask.py` — build storage; pass to `handle_score_command` and `answer_query_with_tools`
- `weekly_synthesis.py` — build storage; `_save_synthesis` uses storage; pass to inner calls
- `nudger.py` — build storage; `load_pending_nudges`, `save_pending_nudges` use storage
- `reply_collector.py` — build storage; pending_nudges read/write uses storage; `append_session_notes` uses storage

---

## Storage Key Reference

All runtime-state keys (path relative to `data/`):

| Config path | Storage key |
|---|---|
| `data/state/state_{date}.json` | `state/state_{date}.json` |
| `data/state/brief_message_id.json` | `state/brief_message_id.json` |
| `data/state/health.json` | `state/health.json` |
| `data/state/brief_scores.jsonl` | `state/brief_scores.jsonl` |
| `data/state/retrieval_log.jsonl` | `state/retrieval_log.jsonl` |
| `data/memory/observations.jsonl` | `memory/observations.jsonl` |
| `data/memory/*.md` | `memory/{name}.md` |
| `data/memory/archive/*.md` | `memory/archive/{name}.md` |
| `data/pipeline_cache.json` | `pipeline_cache.json` |
| `data/pipeline_email_activity.json` | `pipeline_email_activity.json` |
| `data/issues.json` | `issues.json` |
| `data/vector_ingest_state.json` | `vector_ingest_state.json` |
| `data/logs/run_log.jsonl` | `logs/run_log.jsonl` |
| `data/weekly/{date}.md` | `weekly/{date}.md` |
| `data/watcher_state.json` | `watcher_state.json` |
| `data/captures.md` | `captures.md` |
| `data/brief_feedback.md` | `brief_feedback.md` |
| `data/drafts/{type}_{ts}.json` | `drafts/{type}_{ts}.json` |
| `data/meeting_preps.json` | `meeting_preps.json` |
| `data/pending_nudges.json` | `pending_nudges.json` |
| `data/meeting_memory/{name}.md` | `meeting_memory/{name}.md` |

**Human-authored files that keep using raw `open()` (never go through storage):**
- `data/people/*.md`
- `data/projects.md`
- `data/recurring.json`
- `data/meeting_index.json`
- `data/memory/decisions.md`
- `output/dashboard.html`

---

## Task 1: Create `lib/storage.py` and `tests/test_storage.py`

**Files:**
- Create: `lib/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_storage.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd chief-of-staff && python -m pytest tests/test_storage.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'lib.storage'`

- [ ] **Step 3: Create `lib/storage.py`**

```python
"""Storage abstraction — local filesystem or Cloudflare R2."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class LocalStorage:
    """Reads/writes to a local directory. Default backend for dev and local runs."""

    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)

    def _path(self, key: str) -> Path:
        return self.base_dir / key

    def read(self, key: str) -> str | None:
        p = self._path(key)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    def write(self, key: str, content: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def read_binary(self, key: str) -> bytes | None:
        p = self._path(key)
        if not p.exists():
            return None
        return p.read_bytes()

    def write_binary(self, key: str, content: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    def list_keys(self, prefix: str) -> list[str]:
        p = self._path(prefix)
        if not p.exists():
            return []
        return [str(f.relative_to(self.base_dir)) for f in p.rglob("*") if f.is_file()]

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def read_json(self, key: str, default: Any = None) -> Any:
        content = self.read(key)
        if content is None:
            return default
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return default

    def write_json(self, key: str, data: Any, indent: int = 2) -> None:
        self.write(key, json.dumps(data, indent=indent))

    def append_line(self, key: str, line: str) -> None:
        existing = self.read(key) or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        self.write(key, existing + line + "\n")


class R2Storage:
    """Reads/writes to Cloudflare R2 (S3-compatible). Fatal on errors — storage is a hard dependency."""

    def __init__(self, bucket: str, account_id: str, access_key_id: str, secret_access_key: str):
        import boto3
        self.bucket_name = bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def read(self, key: str) -> str | None:
        from botocore.exceptions import ClientError
        try:
            resp = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return resp["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def write(self, key: str, content: str) -> None:
        self.s3.put_object(Bucket=self.bucket_name, Key=key, Body=content.encode("utf-8"))

    def read_binary(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError
        try:
            resp = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return resp["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def write_binary(self, key: str, content: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket_name, Key=key, Body=content)

    def list_keys(self, prefix: str) -> list[str]:
        keys = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket_name, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.s3.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError:
            return False

    def read_json(self, key: str, default: Any = None) -> Any:
        content = self.read(key)
        if content is None:
            return default
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return default

    def write_json(self, key: str, data: Any, indent: int = 2) -> None:
        self.write(key, json.dumps(data, indent=indent))

    def append_line(self, key: str, line: str) -> None:
        existing = self.read(key) or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        self.write(key, existing + line + "\n")


def storage_key(config_path: str) -> str:
    """Strip 'data/' prefix from a config path to produce a storage key."""
    if config_path.startswith("data/"):
        return config_path[5:]
    return config_path


def build_storage(config: dict) -> LocalStorage | R2Storage:
    """Return R2Storage if configured and enabled, otherwise LocalStorage."""
    r2_cfg = config.get("storage", {}).get("r2", {})
    if not r2_cfg.get("enabled"):
        return LocalStorage(base_dir=config.get("data_dir", "data"))
    return R2Storage(
        bucket=r2_cfg["bucket"],
        account_id=r2_cfg["account_id"],
        access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd chief-of-staff && python -m pytest tests/test_storage.py -v
```

Expected: all 21 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/storage.py tests/test_storage.py
git commit -m "feat: add StorageBackend abstraction (LocalStorage + R2Storage)"
```

---

## Task 2: Add `boto3` dependency and `storage` config block

**Files:**
- Modify: `requirements.txt`
- Modify: `config.json`

- [ ] **Step 1: Add boto3 to requirements.txt**

Append to `requirements.txt`:
```
boto3>=1.34.0
```

- [ ] **Step 2: Add storage block to config.json**

Add this top-level key to `config.json` (alongside the existing keys):
```json
"storage": {
  "r2": {
    "enabled": false,
    "bucket": "chief-of-staff",
    "account_id": "YOUR_CLOUDFLARE_ACCOUNT_ID"
  }
}
```

- [ ] **Step 3: Verify import works**

```bash
cd chief-of-staff && python -c "from lib.storage import build_storage; import json; cfg = json.load(open('config.json')); s = build_storage(cfg); print(type(s).__name__)"
```

Expected: `LocalStorage`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt config.json
git commit -m "chore: add boto3 dep and storage config block (r2 disabled by default)"
```

---

## Task 3: Refactor `processors/state.py`

**Files:**
- Modify: `processors/state.py`

The two I/O functions change from accepting `state_dir: str` to accepting `storage`. The key pattern is `state/state_{date}.json`. Internal helper `_snapshot_path` is removed.

- [ ] **Step 1: Update `processors/state.py`**

Replace the file contents from `_snapshot_path` through end of `load_snapshot` with:

```python
def save_snapshot(snapshot: StateSnapshot, storage) -> None:
    key = f"state/state_{snapshot.date}.json"
    storage.write_json(key, asdict(snapshot))


def load_snapshot(target_date: date, storage) -> Optional[StateSnapshot]:
    key = f"state/state_{target_date.isoformat()}.json"
    data = storage.read_json(key)
    if data is None:
        return None
    try:
        return StateSnapshot(**data)
    except (TypeError, KeyError):
        return None
```

Remove `_snapshot_path` entirely (it's no longer used). Remove `import os` if it's now unused (check the full file — `os` was only used in `_snapshot_path`).

- [ ] **Step 2: Verify the module imports cleanly**

```bash
cd chief-of-staff && python -c "from processors.state import save_snapshot, load_snapshot, StateSnapshot; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add processors/state.py
git commit -m "refactor: processors/state.py — use StorageBackend instead of state_dir path"
```

---

## Task 4: Refactor `processors/issues.py`

**Files:**
- Modify: `processors/issues.py`

All four public functions change from accepting `issues_file: str` to accepting `storage`. The key is `"issues.json"`.

- [ ] **Step 1: Update `processors/issues.py`**

Replace the four I/O functions with:

```python
_KEY = "issues.json"


def load_issues(storage) -> IssueLog:
    data = storage.read_json(_KEY)
    if data is None:
        return IssueLog()
    try:
        return IssueLog(issues=[Issue(**i) for i in data.get("issues", [])])
    except (TypeError, KeyError):
        return IssueLog()


def save_issues(log: IssueLog, storage) -> None:
    storage.write_json(_KEY, {"issues": [asdict(i) for i in log.issues]})


def add_or_update_issue(
    storage,
    source: str,
    source_ref: str,
    channel: str,
    title: str,
    actions_needed: Optional[list[str]] = None,
    outside_parties: Optional[list[str]] = None,
) -> None:
    log = load_issues(storage)
    existing_refs = {i.source_ref for i in log.issues}

    if source_ref in existing_refs:
        for issue in log.issues:
            if issue.source_ref == source_ref:
                issue.last_seen_date = date.today().isoformat()
        save_issues(log, storage)
        return

    log.issues.append(Issue(
        id=str(uuid.uuid4())[:8],
        title=title,
        source=source,
        source_ref=source_ref,
        channel=channel,
        created_date=date.today().isoformat(),
        last_seen_date=date.today().isoformat(),
        status="open",
        actions_needed=actions_needed or [],
        outside_parties=outside_parties or [],
        resolved_date=None,
    ))
    save_issues(log, storage)


def auto_resolve_issues(storage, resolve_after_days: int = 3) -> None:
    log = load_issues(storage)
    cutoff = date.today() - timedelta(days=resolve_after_days)
    for issue in log.issues:
        if issue.status == "open":
            if date.fromisoformat(issue.last_seen_date) < cutoff:
                issue.status = "resolved"
                issue.resolved_date = date.today().isoformat()
    save_issues(log, storage)


def get_open_issues(storage) -> list[Issue]:
    log = load_issues(storage)
    return [i for i in log.issues if i.status in ("open", "monitoring")]
```

Remove `import json` and `import os` if they are now unused (check the file — they were only used in the I/O functions). Keep the dataclass imports.

- [ ] **Step 2: Verify**

```bash
cd chief-of-staff && python -c "from processors.issues import load_issues, save_issues, get_open_issues; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add processors/issues.py
git commit -m "refactor: processors/issues.py — use StorageBackend instead of issues_file path"
```

---

## Task 5: Refactor `lib/llm_logger.py`

**Files:**
- Modify: `lib/llm_logger.py`

`flush(run_type, log_file)` → `flush(run_type, storage)`. The key is hardcoded as `logs/run_log.jsonl`.

- [ ] **Step 1: Update `lib/llm_logger.py`**

Replace the `flush` function with:

```python
_LOG_KEY = "logs/run_log.jsonl"


def flush(run_type: str, storage) -> None:
    global _calls
    snapshot = list(_calls)
    _calls = []
    if not snapshot:
        return
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for call in snapshot:
            entry = {"timestamp": timestamp, "run_type": run_type, **call}
            storage.append_line(_LOG_KEY, json.dumps(entry))
    except Exception as e:
        print(f"WARNING: llm_logger flush failed: {e}", file=sys.stderr)
```

Remove the `import os` line (no longer needed). Keep `import json`, `import sys`, and the datetime imports.

- [ ] **Step 2: Verify**

```bash
cd chief-of-staff && python -c "from lib.llm_logger import flush, log_usage; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add lib/llm_logger.py
git commit -m "refactor: lib/llm_logger.py — flush takes storage instead of log_file path"
```

---

## Task 6: Refactor `lib/captures.py` and `processors/feedback.py`

**Files:**
- Modify: `lib/captures.py`
- Modify: `processors/feedback.py`

In `lib/captures.py`: `captures.md` and `brief_feedback.md` are runtime state → use storage. `complete_project_next` writes to `data/projects.md` which is human-authored → keep raw `open()`.

- [ ] **Step 1: Update `lib/captures.py`**

Replace `append_capture`, `load_recent_captures`, `complete_capture`, and `load_brief_feedback` with storage-based versions. Keep `complete_project_next` unchanged.

```python
from datetime import datetime
from typing import Optional

_CAPTURES_KEY = "captures.md"
_FEEDBACK_KEY = "brief_feedback.md"


def append_capture(storage, type_: str, target: Optional[str], content: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    target_str = f" {target} —" if target else ""
    line = f"## {timestamp} — [{type_}]{target_str} {content}\n"
    existing = storage.read(_CAPTURES_KEY) or ""
    storage.write(_CAPTURES_KEY, existing + line)


def load_recent_captures(storage, max_chars: int = 2000) -> str:
    content = storage.read(_CAPTURES_KEY) or ""
    return content[-max_chars:] if len(content) > max_chars else content


def complete_capture(storage, match_text: str) -> bool:
    content = storage.read(_CAPTURES_KEY)
    if content is None:
        return False
    lines = content.splitlines(keepends=True)
    match_lower = match_text.lower()
    new_lines = [l for l in lines if match_lower not in l.lower()]
    if len(new_lines) == len(lines):
        return False
    storage.write(_CAPTURES_KEY, "".join(new_lines))
    return True


def load_brief_feedback(storage, token_budget: int = 800) -> str:
    content = storage.read(_FEEDBACK_KEY) or ""
    max_chars = token_budget * 4
    return content[-max_chars:] if len(content) > max_chars else content


def complete_project_next(projects_file: str, match_text: str) -> bool:
    # projects.md is human-authored; keep raw open()
    import os
    if not os.path.exists(projects_file):
        return False
    try:
        with open(projects_file) as f:
            content = f.read()
        match_lower = match_text.lower()
        lines = content.splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            if line.startswith("**Next:**") and match_lower in line.lower():
                lines[i] = f"**Next:** ~~{line[len('**Next:** '):].rstrip()}~~ ✓\n"
                changed = True
                break
            if line.startswith("## Project:") and match_lower in line.lower():
                for j in range(i + 1, min(i + 8, len(lines))):
                    if lines[j].startswith("**Status:**"):
                        lines[j] = "**Status:** Complete\n"
                        changed = True
                        break
                break
        if not changed:
            return False
        with open(projects_file, "w") as f:
            f.writelines(lines)
        return True
    except OSError:
        return False
```

- [ ] **Step 2: Update `processors/feedback.py`**

Find `append_brief_feedback` and replace with:

```python
_FEEDBACK_KEY = "brief_feedback.md"


def append_brief_feedback(storage, note: str) -> None:
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"\n## {timestamp}\n{note.strip()}\n"
    existing = storage.read(_FEEDBACK_KEY) or ""
    storage.write(_FEEDBACK_KEY, existing + line)
```

Remove `import os` and `import re` from `processors/feedback.py` if they are now unused.

- [ ] **Step 3: Verify**

```bash
cd chief-of-staff && python -c "from lib.captures import append_capture, load_recent_captures; from processors.feedback import append_brief_feedback; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add lib/captures.py processors/feedback.py
git commit -m "refactor: captures and feedback — use StorageBackend instead of file paths"
```

---

## Task 7: Refactor `processors/brief_scorer.py` and `processors/retrieval_logger.py`

**Files:**
- Modify: `processors/brief_scorer.py`
- Modify: `processors/retrieval_logger.py`

Both are append-only log modules. Keys are hardcoded.

- [ ] **Step 1: Update `processors/brief_scorer.py`**

The file has a module-level constant `SCORES_FILE = "data/state/brief_scores.jsonl"`. Replace the I/O functions:

```python
_SCORES_KEY = "state/brief_scores.jsonl"


def save_score(
    score: int,
    note: Optional[str] = None,
    storage=None,
) -> None:
    if storage is None:
        return
    entry = {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "note": note,
    }
    storage.append_line(_SCORES_KEY, json.dumps(entry))


def handle_score_command(text: str, storage=None) -> Optional[str]:
    result = parse_score_command(text)
    if result is None:
        return None
    score, note = result
    if score < 1 or score > 5:
        return f"Score must be 1–5 (got {score})."
    save_score(score, note, storage)
    msg = f"Score {score}/5 logged."
    if note:
        msg += f" Note: {note}"
    return msg
```

Remove the `SCORES_FILE` constant (no longer needed). Remove `import os` if now unused.

- [ ] **Step 2: Update `processors/retrieval_logger.py`**

Replace `log_retrieval` with:

```python
_LOG_KEY = "state/retrieval_log.jsonl"


def log_retrieval(
    storage,
    date_str: str,
    trigger: str,
    query_text: str,
    retrieval_mode: str,
    pinned_memories: list[dict],
    memory_results: list[dict],
    observation_results: list[dict],
    token_budget: int,
    config_snapshot: dict,
) -> None:
    pinned_tokens = sum(m.get("tokens", 0) for m in pinned_memories)
    mem_tokens = sum(r.get("tokens", 0) for r in memory_results if r.get("included"))
    obs_tokens = sum(r.get("tokens", 0) for r in observation_results if r.get("included"))
    total = pinned_tokens + mem_tokens + obs_tokens
    included_count = (
        len(pinned_memories)
        + sum(1 for r in memory_results if r.get("included"))
        + sum(1 for r in observation_results if r.get("included"))
    )
    excluded_count = (
        sum(1 for r in memory_results if not r.get("included"))
        + sum(1 for r in observation_results if not r.get("included"))
    )
    entry = {
        "date": date_str,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "query_text_preview": query_text[:500],
        "query_text_tokens": len(query_text) // 4,
        "retrieval_mode": retrieval_mode,
        "pinned_memories": pinned_memories,
        "pinned_tokens_used": pinned_tokens,
        "memory_results": memory_results,
        "observation_results": observation_results,
        "token_budget": token_budget,
        "pinned_budget_used": pinned_tokens,
        "memory_budget_used": mem_tokens,
        "observation_budget_used": obs_tokens,
        "total_tokens_used": total,
        "budget_remaining": token_budget - total,
        "items_returned": included_count,
        "items_excluded": excluded_count,
        "config_snapshot": config_snapshot,
    }
    storage.append_line(_LOG_KEY, json.dumps(entry))
```

Remove `import os` from `retrieval_logger.py`.

- [ ] **Step 3: Verify**

```bash
cd chief-of-staff && python -c "from processors.brief_scorer import save_score, handle_score_command; from processors.retrieval_logger import log_retrieval; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add processors/brief_scorer.py processors/retrieval_logger.py
git commit -m "refactor: brief_scorer and retrieval_logger — use StorageBackend for JSONL appends"
```

---

## Task 8: Refactor `lib/pipeline_activity.py`

**Files:**
- Modify: `lib/pipeline_activity.py`

Five functions that take `cache_path` and/or `activity_path` strings are replaced with storage-based versions. Keys are hardcoded as module constants.

- [ ] **Step 1: Add key constants and update all I/O functions**

Add at the top of the file (after imports):
```python
_CACHE_KEY = "pipeline_cache.json"
_ACTIVITY_KEY = "pipeline_email_activity.json"
```

Replace `load_lead_email_index`, `load_lead_page_index`, `load_pipeline_activity`, `save_pipeline_activity`, `patch_pipeline_cache_last_contacted`, and `reconcile_activity_to_notion` with:

```python
def load_lead_email_index(storage) -> dict[str, str]:
    """Returns {email_lower: lead_name} for all non-closed/lost leads."""
    skip_statuses = {"Closed", "Lost"}
    data = storage.read_json(_CACHE_KEY, default={})
    return {
        r["email"].lower(): r["name"]
        for r in data.get("leads", [])
        if r.get("email") and r.get("status") not in skip_statuses
    }


def load_lead_page_index(storage) -> dict[str, str]:
    """Returns {email_lower: page_id} for all leads with a page_id."""
    data = storage.read_json(_CACHE_KEY, default={})
    return {
        r["email"].lower(): r["page_id"]
        for r in data.get("leads", [])
        if r.get("email") and r.get("page_id")
    }


def load_pipeline_activity(storage) -> dict:
    return storage.read_json(_ACTIVITY_KEY, default={"updated_at": None, "leads": {}})


def save_pipeline_activity(storage, data: dict) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    storage.write_json(_ACTIVITY_KEY, data)


def patch_pipeline_cache_last_contacted(storage, email: str, contact_date: str) -> None:
    """Updates last_contacted in the local pipeline cache for immediate brief accuracy."""
    data = storage.read_json(_CACHE_KEY)
    if data is None:
        return
    today = date.today()
    changed = False
    for lead in data.get("leads", []):
        if lead.get("email", "").lower() != email:
            continue
        existing = lead.get("last_contacted", "")
        if existing and existing >= contact_date:
            break
        lead["last_contacted"] = contact_date
        try:
            days = (today - date.fromisoformat(contact_date[:10])).days
        except (ValueError, TypeError):
            days = None
        lead["days_since_contact"] = days
        lead["stale"] = bool(days is not None and days >= 14)
        changed = True
        break
    if changed:
        storage.write_json(_CACHE_KEY, data)


def reconcile_activity_to_notion(storage) -> int:
    cache = storage.read_json(_CACHE_KEY)
    if cache is None:
        return 0

    activity = load_pipeline_activity(storage)
    activity_leads = activity.get("leads", {})
    page_index = load_lead_page_index(storage)
    updated = 0

    for lead in cache.get("leads", []):
        email = lead.get("email", "").lower()
        cache_date = lead.get("last_contacted") or ""
        activity_record = activity_leads.get(email, {})
        activity_date = activity_record.get("last_email_date", "")
        if not activity_date or activity_date <= cache_date:
            continue
        page_id = page_index.get(email)
        if not page_id:
            continue
        ok = update_notion_last_contacted(page_id, activity_date)
        if ok:
            patch_pipeline_cache_last_contacted(storage, email, activity_date)
            updated += 1

    return updated
```

Remove `import json` and `from pathlib import Path` if now unused (check — they were used in the old I/O). Keep `import os`, `import re`, `import requests`, datetime imports, `_EMAIL_RE` regex, and `extract_email`, `record_lead_contact`, `update_notion_last_contacted` functions (those don't do file I/O).

- [ ] **Step 2: Verify**

```bash
cd chief-of-staff && python -c "from lib.pipeline_activity import load_lead_email_index, load_pipeline_activity, save_pipeline_activity; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add lib/pipeline_activity.py
git commit -m "refactor: lib/pipeline_activity.py — use StorageBackend instead of path strings"
```

---

## Task 9: Refactor `processors/memory_observer.py`

**Files:**
- Modify: `processors/memory_observer.py`

`observations.jsonl` goes through storage. `decisions.md` is human-authored and keeps using raw `open()`.

- [ ] **Step 1: Update all I/O in `processors/memory_observer.py`**

Key constants:
```python
_OBS_KEY = "memory/observations.jsonl"
_DECISIONS_FILE = "data/memory/decisions.md"  # human-authored, raw open()
```

Replace `_load_known_decision_dates`, `_kpi_snapshot_exists_today`, and `observe`'s obs-file access. The `_read_decisions` function keeps raw `open()` since decisions.md is human-authored.

```python
_OBS_KEY = "memory/observations.jsonl"


def _load_known_decision_dates(storage) -> set[str]:
    known = set()
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            if obs.get("type") == "decision":
                known.add(obs.get("content", "").strip())
        except json.JSONDecodeError:
            continue
    return known


def _kpi_snapshot_exists_today(storage) -> bool:
    today = date.today().isoformat()
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            if obs.get("type") == "kpi_snapshot" and obs.get("date") == today:
                return True
        except json.JSONDecodeError:
            continue
    return False
```

For the `observe` function, change its signature to:
```python
def observe(storage, decisions_file: str, email_threads, still_open_ids, pipeline_leads, brief, issues, sales_data=None, demos_data=None, bugs=None, cancellations=None) -> None:
```

And replace the two file-access lines at the end of `observe` (the append to `obs_file`) with:
```python
    for obs in observations:
        storage.append_line(_OBS_KEY, json.dumps(obs))
```

Replace any call to `_load_known_decision_dates(obs_file)` with `_load_known_decision_dates(storage)`.
Replace any call to `_kpi_snapshot_exists_today(obs_file)` with `_kpi_snapshot_exists_today(storage)`.

The `_read_decisions(decisions_file, known_contents)` function keeps using raw `open()` and its signature is unchanged. The caller (`observe`) still passes `decisions_file` as a string.

- [ ] **Step 2: Verify**

```bash
cd chief-of-staff && python -c "from processors.memory_observer import observe; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add processors/memory_observer.py
git commit -m "refactor: memory_observer — use StorageBackend for observations; decisions.md stays raw"
```

---

## Task 10: Refactor `processors/memory_synthesizer.py`

**Files:**
- Modify: `processors/memory_synthesizer.py`

Replace `Path.glob` iteration, `open()` calls, and `shutil.move` with storage operations.

- [ ] **Step 1: Update `processors/memory_synthesizer.py`**

Add at the top after existing imports:
```python
_OBS_KEY = "memory/observations.jsonl"
```

Replace `_load_recent_observations` with:
```python
def _load_recent_observations(storage, lookback_days: int) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback_days)
    observations = []
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            obs_date = date.fromisoformat(obs.get("date", "2000-01-01"))
            if obs_date >= cutoff:
                observations.append(obs)
        except (json.JSONDecodeError, ValueError):
            continue
    return observations
```

Replace `_archive_expired_files` with:
```python
def _archive_expired_files(storage) -> None:
    for key in storage.list_keys("memory"):
        if not key.endswith(".md") or key.startswith("memory/archive/"):
            continue
        content = storage.read(key)
        if content is None:
            continue
        try:
            post = frontmatter.loads(content)
            if _is_expired(str(post.get("expires", "")), pinned=bool(post.get("pinned", False))):
                name = key.split("/")[-1]
                storage.write(f"memory/archive/{name}", content)
                storage.delete(key)
        except Exception:
            continue
```

Replace `_apply_abandonment_decay` with:
```python
def _apply_abandonment_decay(storage, abandon_threshold_days: int, abandon_ttl_days: int) -> None:
    cutoff = date.today() - timedelta(days=abandon_threshold_days)
    new_expires = (date.today() + timedelta(days=abandon_ttl_days)).isoformat()
    for key in storage.list_keys("memory"):
        if not key.endswith(".md") or key.startswith("memory/archive/"):
            continue
        content = storage.read(key)
        if content is None:
            continue
        try:
            post = frontmatter.loads(content)
            if post.get("pinned"):
                continue
            last_updated = post.get("updated", "")
            if not last_updated:
                continue
            try:
                updated_date = date.fromisoformat(str(last_updated)[:10])
            except ValueError:
                continue
            if updated_date < cutoff:
                current_expires = str(post.get("expires", ""))
                try:
                    current_exp_date = date.fromisoformat(current_expires)
                except ValueError:
                    current_exp_date = None
                candidate = date.today() + timedelta(days=abandon_ttl_days)
                if current_exp_date is None or candidate < current_exp_date:
                    post["expires"] = new_expires
                    storage.write(key, frontmatter.dumps(post))
        except Exception:
            continue
```

Update the `synthesize` function signature:
```python
def synthesize(storage, api_key: str, model: str, lookback_days: int = 30, default_ttl_days: int = 90, activity_extension_days: int = 30, abandon_threshold_days: int = 60, abandon_ttl_days: int = 14) -> None:
```

Inside `synthesize`, update the calls to use `storage` instead of path params, and replace any remaining `with open(...)` writes for memory `.md` files with:
```python
# Writing a synthesized memory file
storage.write(f"memory/{slug}.md", frontmatter.dumps(post))
```

Replace `Path(memory_dir).glob("*.md")` with:
```python
[key for key in storage.list_keys("memory") if key.endswith(".md") and not key.startswith("memory/archive/")]
```

Remove `import shutil` and `from pathlib import Path` if now unused.

- [ ] **Step 2: Verify**

```bash
cd chief-of-staff && python -c "from processors.memory_synthesizer import synthesize; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add processors/memory_synthesizer.py
git commit -m "refactor: memory_synthesizer — use StorageBackend; replace shutil.move with storage read+write+delete"
```

---

## Task 11: Refactor `processors/memory_retriever.py`, `processors/retrieval_digest.py`, `processors/weekly_synthesizer.py`

**Files:**
- Modify: `processors/memory_retriever.py`
- Modify: `processors/retrieval_digest.py`
- Modify: `processors/weekly_synthesizer.py`

- [ ] **Step 1: Update `processors/memory_retriever.py`**

The public functions `retrieve_memories` and `get_cold_start_message` currently take `memory_dir` and `obs_file` path strings. Replace with storage-based access.

Find where `retrieve_memories` is defined and update its signature:
```python
def retrieve_memories(storage, token_budget: int, pinecone_config: dict | None = None, query_signals: dict = None, log_file: str = None, trigger: str = "brief", run_date: str = None) -> str:
```

Replace any `Path(memory_dir).glob("*.md")` with:
```python
[key for key in storage.list_keys("memory") if key.endswith(".md") and not key.startswith("memory/archive/")]
```

Replace any `with open(mem_path) as f: post = frontmatter.load(f)` with:
```python
content = storage.read(key)
if content is None:
    continue
post = frontmatter.loads(content)
```

The `log_file` parameter is passed through to `log_retrieval`. Since `log_retrieval` now takes `storage`, remove `log_file` and pass `storage` instead:
```python
def retrieve_memories(storage, token_budget: int, pinecone_config: dict | None = None, query_signals: dict = None, trigger: str = "brief", run_date: str = None) -> str:
    # ...
    # Where retrieval is logged:
    from processors.retrieval_logger import log_retrieval
    log_retrieval(storage, ...)
```

For `get_cold_start_message`:
```python
_OBS_KEY = "memory/observations.jsonl"

def get_cold_start_message(storage, cold_start_days: int = 3) -> str | None:
    content = storage.read(_OBS_KEY) or ""
    lines = [l for l in content.splitlines() if l.strip()]
    count = len(lines)
    if count >= cold_start_days:
        return None
    return f"Memory system warming up — {count} of {cold_start_days} observations collected. Full context available soon."
```

- [ ] **Step 2: Update `processors/retrieval_digest.py`**

Replace `load_scores` and `load_retrieval_logs`:

```python
_SCORES_KEY = "state/brief_scores.jsonl"
_RETRIEVAL_LOG_KEY = "state/retrieval_log.jsonl"


def load_scores(storage, since: date) -> list[dict]:
    daily: dict[str, dict] = {}
    content = storage.read(_SCORES_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry_date = date.fromisoformat(entry["date"])
            if entry_date >= since:
                daily[entry["date"]] = entry
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return sorted(daily.values(), key=lambda x: x["date"])


def load_retrieval_logs(storage, since: date) -> list[dict]:
    logs = []
    content = storage.read(_RETRIEVAL_LOG_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry_date = date.fromisoformat(entry["date"])
            if entry_date >= since:
                logs.append(entry)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return logs
```

Update `generate_digest` signature to accept `storage` instead of `scores_file` and `retrieval_log_file`:
```python
def generate_digest(storage, api_key: str, model: str, config_snapshot: dict, run_date: date) -> str:
    since = run_date - timedelta(days=7)
    scores = load_scores(storage, since)
    logs = load_retrieval_logs(storage, since)
    # ... rest of function unchanged
```

- [ ] **Step 3: Update `processors/weekly_synthesizer.py`**

Replace `_load_week_observations` with:
```python
_OBS_KEY = "memory/observations.jsonl"


def _load_week_observations(storage, run_date: date) -> list[dict]:
    cutoff = run_date - timedelta(days=7)
    observations = []
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            obs_date = date.fromisoformat(obs.get("date", "2000-01-01"))
            if cutoff <= obs_date <= run_date:
                observations.append(obs)
        except (json.JSONDecodeError, ValueError):
            continue
    return observations
```

Replace `_load_week_state_delta`:
```python
def _load_week_state_delta(storage, run_date: date) -> tuple[int, int]:
    start_date = run_date - timedelta(days=7)
    start_snap = load_snapshot(start_date, storage)
    end_snap = load_snapshot(run_date, storage)
    if not start_snap or not end_snap:
        return 0, 0
    start_ids = set(start_snap.open_email_thread_ids)
    end_ids = set(end_snap.open_email_thread_ids)
    resolved_count = len(start_ids - end_ids)
    still_open_count = len(start_ids & end_ids)
    return resolved_count, still_open_count
```

Update `synthesize_week` signature:
```python
def synthesize_week(storage, api_key: str, model: str, run_date: date, log_file=None) -> WeeklySynthesis:
```

Update internal calls to use storage instead of path params. Remove `issues_file` and `captures_file` from `synthesize_week` if they were only used to load issues/captures — those will now be loaded via storage inside the function:
- `load_issues(storage)` instead of `load_issues(issues_file)`
- `load_recent_captures(storage)` instead of reading captures_file directly

- [ ] **Step 4: Verify**

```bash
cd chief-of-staff && python -c "from processors.memory_retriever import retrieve_memories; from processors.retrieval_digest import generate_digest; from processors.weekly_synthesizer import synthesize_week; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add processors/memory_retriever.py processors/retrieval_digest.py processors/weekly_synthesizer.py
git commit -m "refactor: memory_retriever, retrieval_digest, weekly_synthesizer — use StorageBackend"
```

---

## Task 12: Refactor `processors/drafts.py`

**Files:**
- Modify: `processors/drafts.py`

`save_draft` and `load_todays_drafts` use storage. Draft files live at `drafts/{type}_{timestamp}.json`.

- [ ] **Step 1: Find and read `save_draft` and `load_todays_drafts` in `processors/drafts.py`**

They currently use `drafts_dir` as a path. Replace with:

```python
_DRAFTS_PREFIX = "drafts"


def save_draft(draft: Draft, storage) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    key = f"{_DRAFTS_PREFIX}/{draft.draft_type}_{timestamp}.json"
    storage.write_json(key, {
        "subject": draft.subject,
        "body": draft.body,
        "to": draft.to,
        "draft_type": draft.draft_type,
        "context": draft.context,
        "created_date": draft.created_date,
    })
    return key


def load_todays_drafts(storage) -> list[Draft]:
    today = date.today().isoformat().replace("-", "")
    drafts = []
    for key in storage.list_keys(_DRAFTS_PREFIX):
        if today not in key:
            continue
        data = storage.read_json(key)
        if data is None:
            continue
        try:
            drafts.append(Draft(**data))
        except (TypeError, KeyError):
            continue
    return drafts
```

Remove `import os` and `from pathlib import Path` if now unused.

- [ ] **Step 2: Verify**

```bash
cd chief-of-staff && python -c "from processors.drafts import save_draft, load_todays_drafts; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add processors/drafts.py
git commit -m "refactor: processors/drafts.py — use StorageBackend instead of drafts_dir path"
```

---

## Task 13: Refactor `processors/vector_ingest.py`

**Files:**
- Modify: `processors/vector_ingest.py`

`load_ingest_state`, `save_ingest_state`, and the `ingest` function's `obs_file`, `memory_dir`, and `state_file` params are replaced with `storage`.

- [ ] **Step 1: Update `processors/vector_ingest.py`**

Key constants:
```python
_OBS_KEY = "memory/observations.jsonl"
_STATE_KEY = "vector_ingest_state.json"
```

Replace `load_ingest_state` and `save_ingest_state`:
```python
def load_ingest_state(storage) -> IngestState:
    data = storage.read_json(_STATE_KEY)
    if data is None:
        return IngestState()
    return IngestState(
        last_obs_line=data.get("last_obs_line", 0),
        memory_mtimes=data.get("memory_mtimes", {}),
        raw_record_ids=data.get("raw_record_ids", {}),
    )


def save_ingest_state(state: IngestState, storage) -> None:
    storage.write_json(_STATE_KEY, asdict(state))
```

Update the `ingest` function signature — remove `obs_file`, `memory_dir`, and `state_file` params, replace with `storage`:
```python
def ingest(storage, pinecone_api_key: str, voyage_api_key: str, index_name: str, embedding_model: str, obs_namespace: str = "observations", mem_namespace: str = "memories", raw_namespace: str = "raw_data", pipeline_leads=None, bugs=None, cancellations=None, sales_entries=None) -> None:
```

Inside `ingest`:
- Replace `with open(obs_file) as f: lines = f.readlines()` with:
  ```python
  content = storage.read(_OBS_KEY) or ""
  lines = content.splitlines()
  ```
- Replace `Path(memory_dir).glob("*.md")` with:
  ```python
  [key for key in storage.list_keys("memory") if key.endswith(".md") and not key.startswith("memory/archive/")]
  ```
- Replace `frontmatter.load(str(path))` with:
  ```python
  content = storage.read(key)
  post = frontmatter.loads(content)
  ```
- Replace `load_ingest_state(state_file)` with `load_ingest_state(storage)`
- Replace `save_ingest_state(state, state_file)` with `save_ingest_state(state, storage)`

For memory mtime tracking: `state.memory_mtimes.get(str(path))` uses the file path as a key. After refactor, use the storage key instead: `state.memory_mtimes.get(key)`.

Remove `from pathlib import Path` if now unused.

- [ ] **Step 2: Verify**

```bash
cd chief-of-staff && python -c "from processors.vector_ingest import ingest, load_ingest_state, save_ingest_state; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add processors/vector_ingest.py
git commit -m "refactor: vector_ingest — use StorageBackend for obs, memory files, and ingest state"
```

---

## Task 14: Refactor `processors/meeting_memory.py`, `processors/meeting_prep.py`, `processors/query_tools.py`

**Files:**
- Modify: `processors/meeting_memory.py`
- Modify: `processors/meeting_prep.py`
- Modify: `processors/query_tools.py`

- [ ] **Step 1: Update `processors/meeting_memory.py`**

`load_meeting_index` is human-authored config → keep raw `open()` unchanged.

Replace `append_session_notes` and `load_last_session_summary`:
```python
def append_session_notes(storage, key: str, session_date: str, notes: str) -> None:
    """key is like 'meeting_memory/standup.md'"""
    content = storage.read(key) or "# Meeting Memory\n\n## Session Log\n\n"
    entry = f"\n### {session_date}\n{notes.strip()}\n"
    if "## Session Log" in content:
        content = content + entry
    else:
        content = content + "\n## Session Log\n" + entry
    storage.write(key, content)


def load_last_session_summary(storage, key: str) -> str:
    """key is like 'meeting_memory/standup.md'"""
    content = storage.read(key)
    if not content:
        return ""
    lines = content.splitlines()
    # Find the last ### date header and return everything after it
    last_header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("### "):
            last_header_idx = i
    if last_header_idx is None:
        return ""
    return "\n".join(lines[last_header_idx + 1:]).strip()
```

- [ ] **Step 2: Update `processors/meeting_prep.py`**

`load_prep_state` and `save_prep_state` use key `meeting_preps.json`:
```python
_PREP_KEY = "meeting_preps.json"


def load_prep_state(storage) -> set:
    data = storage.read_json(_PREP_KEY, default={})
    return set(data.get("sent_keys", []))


def save_prep_state(sent_keys: set, storage) -> None:
    cutoff = date.today() - timedelta(days=7)

    def _key_date(k: str) -> date:
        try:
            return date.fromisoformat(k.rsplit("_", 1)[-1])
        except ValueError:
            return date.min

    recent = {k for k in sent_keys if _key_date(k) >= cutoff}
    storage.write_json(_PREP_KEY, {"sent_keys": sorted(recent)})
```

Remove `import os` if now unused.

- [ ] **Step 3: Update `processors/query_tools.py`**

`_tool_add_capture` and `_tool_complete_task` currently read config paths. Update to accept and pass `storage`:

```python
def _tool_add_capture(capture_type: str, text: str, storage) -> str:
    valid = {"todo", "idea", "note", "flag"}
    if capture_type not in valid:
        return f"Invalid capture type '{capture_type}'. Must be one of: {', '.join(sorted(valid))}."
    append_capture(storage, capture_type, None, text)
    return f"Captured [{capture_type}]: {text}"


def _tool_complete_task(description: str, storage, config: dict) -> str:
    projects_file = config.get("projects_file", "data/projects.md")
    hit_capture = complete_capture(storage, description)
    hit_project = complete_project_next(projects_file, description)
    if hit_capture or hit_project:
        parts = []
        if hit_capture:
            parts.append("removed from captures")
        if hit_project:
            parts.append("marked done in projects")
        return f"Completed '{description}' — {', '.join(parts)}."
    return f"No match found for '{description}' in captures or projects."
```

Also find any other tool functions in `query_tools.py` that call `load_issues` or `save_issues` and update them to pass `storage` instead of `issues_file`. Search the file for `load_issues(` and `save_issues(`.

- [ ] **Step 4: Verify**

```bash
cd chief-of-staff && python -c "from processors.meeting_memory import append_session_notes, load_last_session_summary; from processors.meeting_prep import load_prep_state, save_prep_state; from processors.query_tools import _tool_add_capture; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_memory.py processors/meeting_prep.py processors/query_tools.py
git commit -m "refactor: meeting_memory, meeting_prep, query_tools — use StorageBackend"
```

---

## Task 15: Thread storage through `main.py` and `pipeline.py`

**Files:**
- Modify: `main.py`
- Modify: `pipeline.py`

This is the largest task — it updates the core pipeline to pass `storage` through all three stages and replaces the remaining direct `open()` calls in pipeline.py.

- [ ] **Step 1: Update `main.py`**

In `_run_inner`, add storage construction and pass it through. Replace the health file write at the end:

```python
def _run_inner(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    from datetime import date, datetime, timezone
    from lib.health import RunHealth, timed
    from lib.storage import build_storage

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    storage = build_storage(config)

    health = RunHealth(
        run_date=date.today().isoformat(),
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    with timed() as total:
        collected = collect_signals(config, health, storage)
        ctx = process_context(config, collected, health, storage)
        generate_and_deliver(config, ctx, dry_run=dry_run, no_email=no_email, health=health, storage=storage)

    health.total_duration_ms = total.elapsed_ms
    health.compute_overall_status()

    try:
        storage.write_json("state/health.json", health.to_dict())
        status_icon = {"ok": "✅", "degraded": "⚠️", "failed": "❌"}.get(health.overall_status, "?")
        print(f"\n{status_icon} Run health: {health.overall_status} ({health.total_duration_ms}ms)")
    except Exception as e:
        print(f"⚠️ Health write error (non-fatal): {e}", file=sys.stderr)
```

In `run`, update the `flush` call to pass `storage`:
```python
def run(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    from lib.storage import build_storage
    storage = build_storage(config)
    from lib.llm_logger import flush
    try:
        _run_inner(config, dry_run=dry_run, no_email=no_email)
    finally:
        flush("daily_brief", storage)
```

Wait — there's a problem: `_run_inner` creates its own storage, and `run` creates another. Fix: create storage once in `run` and pass it to `_run_inner`.

Updated pattern:
```python
def run(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    from lib.storage import build_storage
    from lib.llm_logger import flush
    storage = build_storage(config)
    try:
        _run_inner(config, storage, dry_run=dry_run, no_email=no_email)
    finally:
        flush("daily_brief", storage)


def _run_inner(config: dict, storage, dry_run: bool = False, no_email: bool = False) -> None:
    from datetime import date, datetime, timezone
    from lib.health import RunHealth, timed

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    health = RunHealth(
        run_date=date.today().isoformat(),
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )

    with timed() as total:
        collected = collect_signals(config, health, storage)
        ctx = process_context(config, collected, health, storage)
        generate_and_deliver(config, ctx, dry_run=dry_run, no_email=no_email, health=health, storage=storage)

    health.total_duration_ms = total.elapsed_ms
    health.compute_overall_status()

    try:
        storage.write_json("state/health.json", health.to_dict())
        status_icon = {"ok": "✅", "degraded": "⚠️", "failed": "❌"}.get(health.overall_status, "?")
        print(f"\n{status_icon} Run health: {health.overall_status} ({health.total_duration_ms}ms)")
    except Exception as e:
        print(f"⚠️ Health write error (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 2: Update `pipeline.py` — function signatures**

Update all three stage function signatures:
```python
def collect_signals(config: dict, health: RunHealth, storage) -> CollectedData:
def process_context(config: dict, collected: CollectedData, health: RunHealth, storage) -> ProcessedContext:
def generate_and_deliver(config: dict, ctx: ProcessedContext, dry_run: bool = False, no_email: bool = False, health: RunHealth = None, storage = None) -> None:
```

Also update helpers that need storage:
```python
def _save_brief_message_id(storage, message_id: str, thread_id: str, subject: str) -> None:
    storage.write_json("state/brief_message_id.json", {
        "message_id": message_id,
        "thread_id": thread_id,
        "subject": subject,
        "date": date.today().isoformat(),
        "processed_reply_ids": [],
    })

def _scan_outbound_pipeline_contacts(config: dict, storage) -> int:
    lead_index = load_lead_email_index(storage)
    if not lead_index:
        return 0
    page_index = load_lead_page_index(storage)
    activity = load_pipeline_activity(storage)
    # ... rest unchanged except:
    # patch_pipeline_cache_last_contacted(cache_path, ...) → patch_pipeline_cache_last_contacted(storage, ...)
    # save_pipeline_activity(activity_path, activity) → save_pipeline_activity(storage, activity)
    # reconcile_activity_to_notion(cache_path, activity_path) → reconcile_activity_to_notion(storage)

def generate_pipeline_drafts(config: dict, storage, trial_leads: list) -> None:
    # save_draft(draft, drafts_dir) → save_draft(draft, storage)

def generate_daily_drafts(config: dict, storage, today_events) -> None:
    # save_draft(draft, drafts_dir) → save_draft(draft, storage)
```

- [ ] **Step 3: Update `collect_signals` body**

In `collect_signals`, replace the issues section:
```python
# OLD
auto_resolve_issues(config["issues_file"], resolve_after_days=config.get("issue_auto_resolve_days", 3))
data.open_issues = get_open_issues(config["issues_file"])

# NEW
auto_resolve_issues(storage, resolve_after_days=config.get("issue_auto_resolve_days", 3))
data.open_issues = get_open_issues(storage)
```

Replace the pipeline section's raw `open()`:
```python
# OLD
with open(cache_path) as f:
    _cache = json.load(f)

# NEW (uses storage, key derived from cache_path)
_cache = storage.read_json("pipeline_cache.json") or {}
```

Update `_scan_outbound_pipeline_contacts(config, cache_path, activity_path)` to `_scan_outbound_pipeline_contacts(config, storage)`.

- [ ] **Step 4: Update `process_context` body**

```python
# Drafts
generate_daily_drafts(config, storage, collected.today_events)
generate_pipeline_drafts(config, storage, collected.trial_leads)
ctx.todays_drafts = load_todays_drafts(storage)

# State snapshot
ctx.previous_state = load_snapshot(yesterday, storage)

# Captures + feedback
ctx.captures_context = load_recent_captures(storage)
ctx.brief_feedback_context = load_brief_feedback(storage)

# Memory retrieval — remove log_file param, pass storage
ctx.memory_context = retrieve_memories(
    storage=storage,
    token_budget=memory_cfg.get("retrieval_token_budget", 1500),
    pinecone_config=_pinecone_cfg,
    query_signals={...},
    trigger="brief",
    run_date=date.today().isoformat(),
)
ctx.memory_cold_start_msg = get_cold_start_message(
    storage=storage,
    cold_start_days=memory_cfg.get("cold_start_days", 3),
)

# Meeting prep — load_meeting_index stays raw (human-authored)
meeting_configs = load_meeting_index(config.get("meeting_index_file", "data/meeting_index.json"))
# build_meeting_prep needs storage for load_last_session_summary:
ctx.meeting_prep = build_meeting_prep(collected.today_events, meeting_configs, storage)
```

Update `build_meeting_prep` to accept and pass storage:
```python
def build_meeting_prep(today_events, meeting_configs, storage) -> list[str]:
    prep = []
    for event in today_events:
        config = find_meeting_for_event(event, meeting_configs)
        if not config:
            continue
        key = config.memory_file.removeprefix("data/")
        last_summary = load_last_session_summary(storage, key)
        if last_summary:
            preview = last_summary[:200] + ("..." if len(last_summary) > 200 else "")
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — Last session: {preview}")
        else:
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — No prior session notes")
    return prep
```

- [ ] **Step 5: Update `generate_and_deliver` body**

Replace the email idempotency check (currently uses raw `open()`):
```python
# OLD
state_path = os.path.join(config["state_dir"], "brief_message_id.json")
if os.path.exists(state_path):
    with open(state_path) as f:
        _prev = json.load(f)
    if _prev.get("date") == date.today().isoformat():
        ...

# NEW
_prev = storage.read_json("state/brief_message_id.json")
if _prev and _prev.get("date") == date.today().isoformat():
    ...
```

Replace `_save_brief_message_id(config, msg_id, thread_id, subject)` with `_save_brief_message_id(storage, msg_id, thread_id, subject)`.

Replace `save_snapshot(snapshot, config["state_dir"])` with `save_snapshot(snapshot, storage)`.

Replace `observe(obs_file=..., decisions_file=..., ...)` with:
```python
observe(
    storage=storage,
    decisions_file=memory_cfg.get("decisions_file", "data/memory/decisions.md"),
    email_threads=collected.email_threads,
    ...
)
```

Replace `synthesize(obs_file=..., memory_dir=..., archive_dir=..., ...)` with:
```python
synthesize(
    storage=storage,
    api_key=api_key,
    model=config["ai_model"],
    ...
)
```

Replace `vector_ingest(obs_file=..., memory_dir=..., ..., state_file=..., ...)` with:
```python
vector_ingest(
    storage=storage,
    pinecone_api_key=pinecone_key,
    voyage_api_key=voyage_key,
    index_name=vector_cfg["index_name"],
    embedding_model=vector_cfg["embedding_model"],
    ...
)
```

Remove unused `cache_path` and `activity_path` variables from collect_signals.

- [ ] **Step 6: Verify the full pipeline**

```bash
cd chief-of-staff && python -c "from pipeline import collect_signals, process_context, generate_and_deliver; print('ok')"
```

Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add main.py pipeline.py
git commit -m "refactor: thread StorageBackend through main.py and pipeline.py"
```

---

## Task 16: Thread storage through `watcher.py`

**Files:**
- Modify: `watcher.py`

- [ ] **Step 1: Update `watcher.py`**

Add storage construction at the top of `run()`. Replace `load_last_run`/`save_last_run` with storage-based versions. Update all calls to refactored modules.

Replace `load_last_run` and `save_last_run`:
```python
_WATCHER_STATE_KEY = "watcher_state.json"


def load_last_run(storage) -> datetime | None:
    data = storage.read_json(_WATCHER_STATE_KEY)
    if data is None:
        return None
    try:
        ts = data.get("last_run")
        if ts:
            return datetime.fromisoformat(ts)
    except ValueError:
        pass
    return None


def save_last_run(storage) -> None:
    storage.write_json(_WATCHER_STATE_KEY, {"last_run": datetime.now(timezone.utc).isoformat()})
```

In `run()`:
```python
def run() -> None:
    if not is_active_hours():
        print("Outside active hours — skipping watcher run.")
        return

    config = load_config()
    from lib.storage import build_storage
    storage = build_storage(config)

    pipeline_cfg = config.get("pipeline", {})

    last_run = load_last_run(storage)
    # ... lookback_hours calculation unchanged ...

    lead_index = load_lead_email_index(storage) if pipeline_cfg.get("enabled") else {}
    activity = load_pipeline_activity(storage)
    # ...

    # For pipeline contacts:
    updated = record_lead_contact(activity, sender_email, lead_name, thread)
    if updated:
        patch_pipeline_cache_last_contacted(storage, recipient_email, contact_date)
        ok = update_notion_last_contacted(page_id, contact_date)
    # ...
    if pipeline_updated:
        save_pipeline_activity(storage, activity)

    # Issues:
    add_or_update_issue(storage, source="gmail", ...)
    # ...
    auto_resolve_issues(storage, resolve_after_days=config.get("issue_auto_resolve_days", 3))
    save_last_run(storage)
```

Remove `issues_file`, `cache_path`, `activity_path`, `state_path` variables (no longer needed as path strings).

- [ ] **Step 2: Verify**

```bash
cd chief-of-staff && python -c "import watcher; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add watcher.py
git commit -m "refactor: watcher.py — use StorageBackend for watcher state, issues, pipeline activity"
```

---

## Task 17: Thread storage through `check_replies.py` and `ask.py`

**Files:**
- Modify: `check_replies.py`
- Modify: `ask.py`

- [ ] **Step 1: Update `check_replies.py`**

Replace `load_brief_state` and `save_brief_state` with storage-based versions. Remove the path parameter from both.

```python
def load_brief_state(storage) -> dict | None:
    return storage.read_json("state/brief_message_id.json")


def save_brief_state(storage, state: dict) -> None:
    storage.write_json("state/brief_message_id.json", state)
```

In `main()`:
```python
def main() -> None:
    config = load_config()
    from lib.storage import build_storage
    from lib.llm_logger import flush
    storage = build_storage(config)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    user_email = config["email"]

    state = load_brief_state(storage)
    # ...
    # All save_brief_state(config["state_dir"], state) → save_brief_state(storage, state)
    # append_capture(captures_file, ...) → append_capture(storage, ...)
    # append_brief_feedback(feedback_file, ...) → append_brief_feedback(storage, ...)

    try:
        # ... reply processing loop unchanged except for above substitutions ...
    finally:
        flush("email_reply", storage)
```

Remove `captures_file` and `feedback_file` local variables (no longer needed).

- [ ] **Step 2: Update `ask.py`**

```python
def _main_inner(query: str, chat_id: str, bot_token: str, config: dict, storage) -> None:
    score_response = handle_score_command(query, storage=storage)
    if score_response is not None:
        if bot_token:
            send_message(bot_token, chat_id, score_response)
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    # ...
    answer = answer_query_with_tools(
        api_key=api_key,
        model=config["ai_model"],
        query=query,
        config=config,
        storage=storage,
    )
    # ...
```

Add storage construction in the entry point and pass it through. Also check `processors/query.py` — `answer_query_with_tools` likely needs `storage` passed to the tool execution functions.

Look at `processors/query.py` for `answer_query_with_tools`. It calls tool functions from `processors/query_tools.py`. Those tools now accept `storage`. Update `answer_query_with_tools(api_key, model, query, config, storage)` and pass `storage` to each tool call inside it.

In `ask.py`:
```python
def main() -> None:
    config = load_config()
    from lib.storage import build_storage
    from lib.llm_logger import flush
    storage = build_storage(config)

    query = os.environ.get("QUERY_TEXT", "").strip()
    chat_id = os.environ.get("QUERY_CHAT_ID", "")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if not query:
        print("No query text provided.", file=sys.stderr)
        sys.exit(1)

    try:
        _main_inner(query, chat_id, bot_token, config, storage)
    finally:
        flush("ask", storage)
```

- [ ] **Step 3: Verify**

```bash
cd chief-of-staff && python -c "import check_replies; import ask; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add check_replies.py ask.py
git commit -m "refactor: check_replies.py and ask.py — use StorageBackend"
```

---

## Task 18: Thread storage through `weekly_synthesis.py`, `nudger.py`, `reply_collector.py`

**Files:**
- Modify: `weekly_synthesis.py`
- Modify: `nudger.py`
- Modify: `reply_collector.py`

- [ ] **Step 1: Update `weekly_synthesis.py`**

Replace `_save_synthesis` and `_main_inner`:
```python
def _save_synthesis(storage, synthesis: WeeklySynthesis, run_date: date) -> None:
    key = f"weekly/{run_date.isoformat()}.md"
    lines = [
        f"# Weekly Synthesis — {run_date.isoformat()}",
        "",
        synthesis.executive_summary,
        "",
    ]
    if synthesis.patterns:
        lines += ["## Patterns", *[f"- {p}" for p in synthesis.patterns], ""]
    if synthesis.resolved_this_week:
        lines += ["## Resolved This Week", *[f"- {r}" for r in synthesis.resolved_this_week], ""]
    if synthesis.carry_forwards:
        lines += ["## Carry-Forwards", *[f"- {c}" for c in synthesis.carry_forwards], ""]
    if synthesis.meta_observation:
        lines += ["## Meta Observation", synthesis.meta_observation, ""]
    storage.write(key, "\n".join(lines))
    print(f"Saved: {key}")
```

In `_main_inner`:
```python
def _main_inner(config: dict, run_date, storage) -> None:
    # ...
    synthesis = synthesize_week(
        storage=storage,
        api_key=api_key,
        model=config["ai_model"],
        run_date=run_date,
    )
    _save_synthesis(storage, synthesis, run_date)
    # ...
    digest = generate_digest(
        storage=storage,
        api_key=api_key,
        model=config["ai_model"],
        config_snapshot={...},
        run_date=run_date,
    )
```

In `main()`:
```python
def main() -> None:
    config = load_config()
    run_date = date.today()
    from lib.storage import build_storage
    from lib.llm_logger import flush
    storage = build_storage(config)
    try:
        _main_inner(config, run_date, storage)
    finally:
        flush("weekly_synthesis", storage)
```

- [ ] **Step 2: Update `nudger.py`**

Replace `load_pending_nudges` and `save_pending_nudges`:
```python
_NUDGES_KEY = "pending_nudges.json"


def load_pending_nudges(storage) -> list[dict]:
    return storage.read_json(_NUDGES_KEY, default=[])


def save_pending_nudges(nudges: list[dict], storage) -> None:
    storage.write_json(_NUDGES_KEY, nudges)
```

In `run()`:
```python
def run() -> None:
    config = load_config()
    from lib.storage import build_storage
    storage = build_storage(config)
    # ...
    pending = load_pending_nudges(storage)
    # ...
    sent_preps = load_prep_state(storage) if prep_enabled else set()
    # ...
    save_pending_nudges(pending, storage)
    if prep_enabled:
        save_prep_state(sent_preps, storage)
```

Remove `pending_file` and `prep_state_file` variables.

- [ ] **Step 3: Update `reply_collector.py`**

Replace the pending file read/write with storage calls. Update the `append_session_notes` call to use storage:

```python
def run() -> None:
    config = load_config()
    from lib.storage import build_storage
    storage = build_storage(config)
    profile = config.get("gmail_profile", "work")

    pending = storage.read_json("pending_nudges.json", default=[])
    if not pending:
        return

    cutoff = datetime.now() - timedelta(days=7)
    still_pending = []

    for nudge in pending:
        sent_at = datetime.fromisoformat(nudge["sent_at"])
        if sent_at < cutoff:
            continue

        thread_id = nudge.get("thread_id")
        memory_file = nudge.get("memory_file")
        if not thread_id or not memory_file:
            still_pending.append(nudge)
            continue

        count = get_thread_message_count(thread_id, profile)
        if count < 2:
            still_pending.append(nudge)
            continue

        reply_text = get_latest_reply_text(thread_id, profile)
        if reply_text.strip():
            key = memory_file.removeprefix("data/")
            append_session_notes(storage, key, nudge["session_date"], reply_text)
            print(f"  Captured notes for: {nudge['meeting_name']}")
        else:
            still_pending.append(nudge)

    storage.write_json("pending_nudges.json", still_pending)
    print("✅ Reply collector complete.")
```

- [ ] **Step 4: Verify all three**

```bash
cd chief-of-staff && python -c "import weekly_synthesis; import nudger; import reply_collector; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add weekly_synthesis.py nudger.py reply_collector.py
git commit -m "refactor: weekly_synthesis, nudger, reply_collector — use StorageBackend"
```

---

## Task 19: Verification Pass

- [ ] **Step 1: Search for remaining raw `open()` calls in runtime-state files**

```bash
cd chief-of-staff && grep -rn 'open("data/' --include="*.py" | grep -v "# human-authored" | grep -v "projects_file\|recurring_file\|people_dir\|meeting_index\|decisions.md"
```

Review any hits. They should only be in:
- `collectors/local_data.py` (loads `projects.md` and `recurring.json` — human-authored, expected)
- `collectors/pipeline.py` (reads `pipeline_cache.json` — if any raw open() remains, fix it)
- Any scripts/ utilities that don't need to be migrated yet

- [ ] **Step 2: Run the full pipeline dry-run**

```bash
cd chief-of-staff && python main.py --no-email 2>&1 | tail -20
```

Expected: Brief generates successfully. `data/` files are written in the same locations as before. No errors about missing arguments.

- [ ] **Step 3: Verify `data/` files still written correctly by LocalStorage**

```bash
ls -la chief-of-staff/data/state/
ls -la chief-of-staff/data/memory/
```

Expected: `state_{today}.json`, `health.json`, `brief_message_id.json` (if email was sent), and memory files are present.

- [ ] **Step 4: Confirm no behavior change by running tests**

```bash
cd chief-of-staff && python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: phase 1 verification — all runtime state I/O goes through StorageBackend"
```

---

## Phase 2 Checklist (separate PR, not part of this plan)

When ready to flip to R2:
1. Create Cloudflare R2 bucket named `chief-of-staff`
2. Generate R2 API token (read/write on that bucket)
3. Add `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` as GitHub Secrets
4. Write `scripts/migrate_to_r2.py` — reads every runtime file from `data/` and writes to R2
5. Update `config.json`: set `storage.r2.enabled: true` and fill in `account_id`
6. Remove `git add data/ && git commit && git push` from all GitHub Actions workflows
7. Add `data/` to `.gitignore` (except human-authored content)
8. Verify end-to-end on R2 before removing git commit step
