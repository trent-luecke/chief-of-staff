# Cowork Notion-Sync — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-apply the nightly Avoma digest's structured pipeline/onboarding updates to the Notion trackers via a local in-app Cowork routine, eliminating manual re-entry — Phase 1 (core sync; the onboarding confirm loop is Phase 2).

**Architecture:** The cloud `avoma_sync.py` already builds structured `pipeline_updates`/`onboarding_updates`; we append each to a git-tracked JSONL queue (`data/notion_updates_queue.jsonl`) instead of only flattening them into Slack. A local scheduled Cowork routine reads the queue off `origin/main`, applies each entry to Notion via the managed `notion-os-pipeline-updater` / `notion-os-onboarding-updater` skills (the only path with the in-app claude.ai Notion connector), dedups on a laptop-local seen-set, and posts one Slack summary.

**Tech Stack:** Python 3.11+, pytest, `git` plumbing (`lib/git_sync.py`), `lib/slack_post.py`, the `scheduled-tasks` MCP (in-app runner).

## Global Constraints

- **Registry/queue stores are git-anchored, never R2.** The queue file `data/notion_updates_queue.jsonl` lives on `origin/main`; the consumer reads it via `git show origin/main:…` (`lib/git_sync.show_main`), never the working tree.
- **Producer writes are non-fatal.** A queue-write failure must never fail the nightly `avoma_sync` job (wrap like the existing demo-push try/except).
- **Only the in-app Cowork run can write Notion.** The managed updater skills require the app's claude.ai connector; no Python code writes Notion directly, and the Telegram/cloud bot only *enqueues*.
- **Queue is append-only JSONL with `merge=union` for the concurrent writers** (the nightly producer's append and the `queue_notion_update` tool's append) — these must never read-modify-write the whole file, so they can't clobber each other. The single nightly producer additionally performs one sanctioned maintenance rewrite to prune >30-day lines (`prune_file`); no other writer rewrites the file, and the consumer never writes it at all.
- **Consumer is read-only toward git.** It pulls the queue and tracks applied ids in a laptop-local, gitignored seen-set (`data/state/notion_updates_seen.json`); it never commits.
- **Control model:** apply-all-then-report for every update **except** creating a brand-new onboarding record (unmatched onboarding customers are held for the Phase 2 confirm loop; in Phase 1 they are listed for manual add).
- **Cron:** `31 8 * * 1-5` (8:31am CT, local).

---

### Task 1: Queue plumbing (`lib/notion_queue.py`) + file/git migration

Creates the JSONL queue substrate shared by the producer, the manual tool, and the consumer, and migrates the empty `.json` array file to `.jsonl`.

**Files:**
- Create: `lib/notion_queue.py`
- Create: `tests/test_notion_queue.py`
- Modify: `.gitignore` (allow-list line for the queue)
- Modify: `.gitattributes` (union merge driver)
- Delete: `data/notion_updates_queue.json` — Create: `data/notion_updates_queue.jsonl`

**Interfaces:**
- Produces:
  - `DEFAULT_QUEUE_PATH: str = "data/notion_updates_queue.jsonl"`
  - `append_entries(queue_path: str, entries: list[dict]) -> int` — append each as one JSON line; returns count; no-op on `[]`.
  - `parse_jsonl(text: str) -> list[dict]` — parse JSONL, skip blank/corrupt lines.
  - `read_queue(queue_path: str) -> list[dict]` — parse file, `[]` if missing.
  - `prune_text(text: str, max_age_days: int, now: datetime) -> str` — drop entries older than cutoff (keep missing/unparseable timestamps).
  - `prune_file(queue_path: str, max_age_days: int = 30, now: datetime | None = None) -> int` — rewrite file dropping stale lines; returns removed count.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_notion_queue.py
import json
from datetime import datetime, timezone, timedelta
from lib.notion_queue import (
    append_entries, parse_jsonl, read_queue, prune_text, prune_file, DEFAULT_QUEUE_PATH,
)


def test_default_path_is_jsonl():
    assert DEFAULT_QUEUE_PATH == "data/notion_updates_queue.jsonl"


def test_append_entries_writes_one_line_each(tmp_path):
    p = tmp_path / "q.jsonl"
    n = append_entries(str(p), [{"id": "a"}, {"id": "b"}])
    assert n == 2
    lines = p.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "a"


def test_append_entries_appends_not_overwrites(tmp_path):
    p = tmp_path / "q.jsonl"
    append_entries(str(p), [{"id": "a"}])
    append_entries(str(p), [{"id": "b"}])
    assert [e["id"] for e in read_queue(str(p))] == ["a", "b"]


def test_append_entries_empty_is_noop(tmp_path):
    p = tmp_path / "q.jsonl"
    assert append_entries(str(p), []) == 0
    assert not p.exists()


def test_parse_jsonl_skips_blank_and_corrupt():
    text = '{"id": "a"}\n\n  \nnot json\n{"id": "b"}\n'
    assert [e["id"] for e in parse_jsonl(text)] == ["a", "b"]


def test_read_queue_missing_file_is_empty(tmp_path):
    assert read_queue(str(tmp_path / "nope.jsonl")) == []


def test_prune_text_drops_old_keeps_recent_and_undated():
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    old = (now - timedelta(days=40)).isoformat()
    recent = (now - timedelta(days=5)).isoformat()
    text = (
        json.dumps({"id": "old", "timestamp": old}) + "\n"
        + json.dumps({"id": "recent", "timestamp": recent}) + "\n"
        + json.dumps({"id": "undated"}) + "\n"
    )
    kept = [e["id"] for e in parse_jsonl(prune_text(text, 30, now))]
    assert "old" not in kept
    assert "recent" in kept and "undated" in kept


def test_prune_file_rewrites_and_returns_removed(tmp_path):
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    old = (now - timedelta(days=40)).isoformat()
    p = tmp_path / "q.jsonl"
    append_entries(str(p), [{"id": "old", "timestamp": old}, {"id": "keep"}])
    removed = prune_file(str(p), 30, now)
    assert removed == 1
    assert [e["id"] for e in read_queue(str(p))] == ["keep"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notion_queue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.notion_queue'`

- [ ] **Step 3: Write the implementation**

```python
# lib/notion_queue.py
"""Append-only JSONL queue for Notion updates (data/notion_updates_queue.jsonl).

Written by the nightly avoma_sync producer and the Telegram queue_notion_update
tool; drained by the local Cowork routine, which dedups on `id` via a laptop-
local seen-set and never mutates this file. JSONL + a merge=union git driver
means concurrent appends never clobber each other.
"""
import json
import os
from datetime import datetime, timezone

DEFAULT_QUEUE_PATH = "data/notion_updates_queue.jsonl"


def _dumps(entry: dict) -> str:
    return json.dumps(entry, separators=(",", ":"))


def append_entries(queue_path: str, entries: list[dict]) -> int:
    if not entries:
        return 0
    os.makedirs(os.path.dirname(queue_path) or ".", exist_ok=True)
    with open(queue_path, "a") as f:
        for e in entries:
            f.write(_dumps(e) + "\n")
    return len(entries)


def parse_jsonl(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_queue(queue_path: str) -> list[dict]:
    try:
        with open(queue_path) as f:
            return parse_jsonl(f.read())
    except FileNotFoundError:
        return []


def prune_text(text: str, max_age_days: int, now: datetime) -> str:
    kept = []
    for e in parse_jsonl(text):
        ts = e.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
        except (ValueError, AttributeError):
            dt = None
        if dt is not None and (now - dt).days > max_age_days:
            continue
        kept.append(e)
    return "".join(_dumps(e) + "\n" for e in kept)


def prune_file(queue_path: str, max_age_days: int = 30, now: datetime | None = None) -> int:
    try:
        with open(queue_path) as f:
            text = f.read()
    except FileNotFoundError:
        return 0
    now = now or datetime.now(timezone.utc)
    before = len(parse_jsonl(text))
    pruned = prune_text(text, max_age_days, now)
    after = len(parse_jsonl(pruned))
    if after != before:
        with open(queue_path, "w") as f:
            f.write(pruned)
    return before - after
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notion_queue.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Migrate the queue file and git config**

Migrate the empty array file to JSONL and wire git:

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
git rm --quiet data/notion_updates_queue.json
: > data/notion_updates_queue.jsonl   # empty JSONL file
```

Edit `.gitignore` — change the allow-list line for the queue from `.json` to `.jsonl`:

```diff
-!data/notion_updates_queue.json
+!data/notion_updates_queue.jsonl
```

Append to `.gitattributes` (below the existing union lines):

```
data/notion_updates_queue.jsonl merge=union
```

- [ ] **Step 6: Verify git sees the new file and the ignore rule**

Run: `git check-ignore -v data/notion_updates_queue.jsonl; git status --porcelain data/`
Expected: `git check-ignore` prints nothing and exits non-zero (file is NOT ignored); `git status` shows the `.json` deletion and the new `.jsonl` staged/untracked.

- [ ] **Step 7: Commit**

```bash
git add lib/notion_queue.py tests/test_notion_queue.py .gitignore .gitattributes data/notion_updates_queue.jsonl
git add -u data/notion_updates_queue.json
git commit -m "feat(notion-queue): JSONL queue helpers + migrate queue file to .jsonl"
```

---

### Task 2: Producer hook in `avoma_sync.py`

Emit one normalized queue entry per pipeline/onboarding update on each nightly run, prune stale lines, and add the file to the workflow commit-back.

**Files:**
- Modify: `scripts/avoma_sync.py` (add `build_queue_entries`; tag updates with `call_uuid`; append+prune in `main`)
- Modify: `tests/test_avoma_sync.py` (add `build_queue_entries` tests)
- Modify: `.github/workflows/avoma_sync.yml` (commit-back `git add`)

**Interfaces:**
- Consumes: `lib.notion_queue.append_entries`, `prune_file`, `DEFAULT_QUEUE_PATH`.
- Produces: `build_queue_entries(pipeline_updates: list[dict], onboarding_updates: list[dict], now: str | None = None) -> list[dict]` — maps avoma update dicts to queue entries with keys: `id, timestamp, source="avoma", target, name, call_date, action="update", summary` plus pipeline (`inferred_status, is_new_lead, account_owner, buying_signals, objections`) or onboarding (`onboarding_completed, onboarding_next_steps, status_update`) fields. `id = "avoma:<call_uuid>"` when present, else `"avoma:<name>:<call_date>"`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_avoma_sync.py

def test_build_queue_entries_pipeline_shape():
    from scripts.avoma_sync import build_queue_entries
    pu = [{
        "lead_name": "Acme Corp", "call_type": "demo", "call_date": "2026-06-06",
        "inferred_status": "In-Trial / Post Demo", "summary": "Strong interest.",
        "is_new_lead": True, "account_owner": "Chris",
        "buying_signals": ["timeline"], "objections": [], "call_uuid": "u-123",
    }]
    entries = build_queue_entries(pu, [], now="2026-06-06T12:00:00Z")
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == "avoma:u-123"
    assert e["source"] == "avoma" and e["target"] == "pipeline"
    assert e["name"] == "Acme Corp" and e["action"] == "update"
    assert e["inferred_status"] == "In-Trial / Post Demo"
    assert e["is_new_lead"] is True and e["account_owner"] == "Chris"
    assert e["timestamp"] == "2026-06-06T12:00:00Z"


def test_build_queue_entries_onboarding_shape():
    from scripts.avoma_sync import build_queue_entries
    ou = [{
        "customer_name": "Alina Bushma", "call_date": "2026-08-12",
        "onboarding_completed": ["Scheduling walkthrough"],
        "onboarding_next_steps": ["Explore independently"],
        "status_update": "In progress", "summary": "Engaged.", "call_uuid": "u-9",
    }]
    entries = build_queue_entries([], ou, now="2026-08-12T12:00:00Z")
    e = entries[0]
    assert e["id"] == "avoma:u-9" and e["target"] == "onboarding"
    assert e["name"] == "Alina Bushma"
    assert e["onboarding_completed"] == ["Scheduling walkthrough"]
    assert e["status_update"] == "In progress"


def test_build_queue_entries_id_fallback_without_uuid():
    from scripts.avoma_sync import build_queue_entries
    pu = [{"lead_name": "No UUID Co", "call_date": "2026-06-06", "call_type": "demo",
           "inferred_status": "Post Demo", "summary": "", "is_new_lead": False,
           "account_owner": None, "buying_signals": [], "objections": []}]
    entries = build_queue_entries(pu, [], now="2026-06-06T12:00:00Z")
    assert entries[0]["id"] == "avoma:No UUID Co:2026-06-06"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_avoma_sync.py -k build_queue_entries -v`
Expected: FAIL with `ImportError: cannot import name 'build_queue_entries'`

- [ ] **Step 3: Add `build_queue_entries` to `scripts/avoma_sync.py`**

Insert after `build_slack_message` (before `def main()`):

```python
def build_queue_entries(
    pipeline_updates: list[dict],
    onboarding_updates: list[dict],
    now: str | None = None,
) -> list[dict]:
    """Map avoma update dicts to normalized Notion-queue entries (source=avoma)."""
    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    entries: list[dict] = []
    for u in pipeline_updates:
        uid = u.get("call_uuid")
        name, cd = u["lead_name"], u["call_date"]
        entries.append({
            "id": f"avoma:{uid}" if uid else f"avoma:{name}:{cd}",
            "timestamp": now,
            "source": "avoma",
            "target": "pipeline",
            "name": name,
            "call_date": cd,
            "action": "update",
            "inferred_status": u.get("inferred_status"),
            "is_new_lead": u.get("is_new_lead", False),
            "account_owner": u.get("account_owner"),
            "buying_signals": u.get("buying_signals", []),
            "objections": u.get("objections", []),
            "summary": u.get("summary", ""),
        })
    for u in onboarding_updates:
        uid = u.get("call_uuid")
        name, cd = u["customer_name"], u["call_date"]
        entries.append({
            "id": f"avoma:{uid}" if uid else f"avoma:{name}:{cd}",
            "timestamp": now,
            "source": "avoma",
            "target": "onboarding",
            "name": name,
            "call_date": cd,
            "action": "update",
            "onboarding_completed": u.get("onboarding_completed", []),
            "onboarding_next_steps": u.get("onboarding_next_steps", []),
            "status_update": u.get("status_update", ""),
            "summary": u.get("summary", ""),
        })
    return entries
```

The module already imports `from datetime import date, datetime`; add `timezone`:

```diff
-from datetime import date, datetime
+from datetime import date, datetime, timezone
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_avoma_sync.py -k build_queue_entries -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Tag updates with `call_uuid` and enqueue in `main()`**

In the `for t in new_transcripts:` loop, add `"call_uuid": getattr(t, "uuid", None)` to BOTH appended dicts:

```diff
             pipeline_updates.append({
                 "lead_name": lead_name,
                 "call_type": t.call_type,
                 "call_date": call_date,
+                "call_uuid": getattr(t, "uuid", None),
                 "inferred_status": _infer_pipeline_status(t),
```

```diff
             onboarding_updates.append({
                 "customer_name": lead_name,
                 "call_date": call_date,
+                "call_uuid": getattr(t, "uuid", None),
                 "onboarding_completed": completed,
```

Then, immediately after the `_patch_cache_last_contacted` block (before `# Build and send Slack DM`), add the non-fatal enqueue:

```python
    # ── Enqueue structured updates for the local Cowork → Notion routine ──
    try:
        from lib.notion_queue import append_entries, prune_file, DEFAULT_QUEUE_PATH
        queue_path = str(_ROOT / config.get("notion_queue_path", DEFAULT_QUEUE_PATH))
        entries = build_queue_entries(pipeline_updates, onboarding_updates)
        appended = append_entries(queue_path, entries)
        prune_file(queue_path, max_age_days=30)
        print(f"   Notion queue: appended {appended} entr{'y' if appended == 1 else 'ies'}.")
    except Exception as e:
        print(f"⚠️  Notion queue write error (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 6: Run the full avoma test file**

Run: `python -m pytest tests/test_avoma_sync.py -v`
Expected: PASS (all existing + 3 new)

- [ ] **Step 7: Add the queue file to the workflow commit-back**

In `.github/workflows/avoma_sync.yml`, in the `Commit data changes` step:

```diff
           git add data/pipeline_cache.json 2>/dev/null || true
           git add data/state/avoma_sync_seen.json 2>/dev/null || true
+          git add data/notion_updates_queue.jsonl 2>/dev/null || true
           git diff --staged --quiet || git commit -m "chore: avoma sync data [skip ci]"
```

- [ ] **Step 8: Commit**

```bash
git add scripts/avoma_sync.py tests/test_avoma_sync.py .github/workflows/avoma_sync.yml
git commit -m "feat(avoma-sync): enqueue structured pipeline/onboarding updates to Notion queue"
```

---

### Task 3: Migrate the `queue_notion_update` tool to JSONL append

Replace the read-array→mutate→write-whole-array logic (a lost-write/conflict bug) with a single JSONL append via `lib.notion_queue`, and point the default path at `.jsonl`.

**Files:**
- Modify: `processors/query_tools.py` (`_tool_queue_notion_update`)
- Modify: `config.json` (add `notion_queue_path`)
- Create: `tests/test_query_tools_queue.py`

**Interfaces:**
- Consumes: `lib.notion_queue.append_entries`, `read_queue`, `DEFAULT_QUEUE_PATH`.
- Produces (unchanged signature): `_tool_queue_notion_update(person, action, config, note="", stage="", follow_up_date="", reason="") -> str`. Now writes one JSONL line shaped `{id, timestamp, source:"manual", target:"pipeline", name:person, action, [note|stage|follow_up_date|reason]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_query_tools_queue.py
import json
from processors.query_tools import _tool_queue_notion_update
from lib.notion_queue import read_queue


def test_queue_tool_appends_jsonl_line(tmp_path):
    q = tmp_path / "q.jsonl"
    cfg = {"notion_queue_path": str(q)}
    _tool_queue_notion_update("Jane Doe", "add_note", cfg, note="Called, left VM")
    entries = read_queue(str(q))
    assert len(entries) == 1
    e = entries[0]
    assert e["source"] == "manual" and e["target"] == "pipeline"
    assert e["name"] == "Jane Doe" and e["action"] == "add_note"
    assert e["note"] == "Called, left VM"
    assert e["id"] and e["timestamp"]


def test_queue_tool_two_calls_dont_clobber(tmp_path):
    q = tmp_path / "q.jsonl"
    cfg = {"notion_queue_path": str(q)}
    _tool_queue_notion_update("A Corp", "update_stage", cfg, stage="Trial")
    _tool_queue_notion_update("B Corp", "add_note", cfg, note="hi")
    assert [e["name"] for e in read_queue(str(q))] == ["A Corp", "B Corp"]


def test_queue_tool_delete_requires_reason(tmp_path):
    q = tmp_path / "q.jsonl"
    cfg = {"notion_queue_path": str(q)}
    msg = _tool_queue_notion_update("X", "delete_record", cfg)
    assert "reason is required" in msg
    assert read_queue(str(q)) == []


def test_queue_tool_rejects_bad_action(tmp_path):
    cfg = {"notion_queue_path": str(tmp_path / "q.jsonl")}
    msg = _tool_queue_notion_update("X", "frobnicate", cfg)
    assert "Invalid action" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_query_tools_queue.py -v`
Expected: FAIL — `test_queue_tool_appends_jsonl_line` errors/asserts because the current tool writes a JSON array to the default `.json` path and entries lack `source`/`target`/`name`.

- [ ] **Step 3: Rewrite `_tool_queue_notion_update`**

Replace the body of `_tool_queue_notion_update` in `processors/query_tools.py`:

```python
def _tool_queue_notion_update(
    person: str,
    action: str,
    config: dict,
    note: str = "",
    stage: str = "",
    follow_up_date: str = "",
    reason: str = "",
) -> str:
    import uuid
    from datetime import datetime, timezone
    from lib.notion_queue import append_entries, DEFAULT_QUEUE_PATH

    valid_actions = {"add_note", "update_stage", "set_follow_up", "delete_record"}
    if action not in valid_actions:
        return f"Invalid action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}."
    if action == "delete_record" and not reason:
        return "reason is required for delete_record actions."

    queue_path = config.get("notion_queue_path", DEFAULT_QUEUE_PATH)
    entry: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
        "target": "pipeline",
        "name": person,
        "action": action,
    }
    if note:
        entry["note"] = note
    if stage:
        entry["stage"] = stage
    if follow_up_date:
        entry["follow_up_date"] = follow_up_date
    if reason:
        entry["reason"] = reason

    append_entries(queue_path, [entry])

    action_desc = {
        "add_note": f"note queued for {person}",
        "update_stage": f"stage update to '{stage}' queued for {person}",
        "set_follow_up": f"follow-up date {follow_up_date} queued for {person}",
        "delete_record": f"delete record queued for {person} (reason: {reason})",
    }[action]
    return f"Notion queue: {action_desc}. Cowork will apply this on its next scheduled run."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_query_tools_queue.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Set the config path**

In `config.json`, add a top-level key (next to other top-level keys like `ai_model`):

```json
  "notion_queue_path": "data/notion_updates_queue.jsonl",
```

Verify JSON is still valid:

Run: `python -c "import json; json.load(open('config.json')); print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add processors/query_tools.py tests/test_query_tools_queue.py config.json
git commit -m "feat(query-tools): queue_notion_update appends JSONL (fixes lost-write on concurrent queue writes)"
```

---

### Task 4: Consumer helper CLI (`scripts/notion_sync_consumer.py`)

The deterministic scaffolding the routine calls around the LLM Notion-write steps: read fresh queue entries off `origin/main`, mark ids applied, hold unmatched onboarding entries, and post the Slack summary.

**Files:**
- Create: `scripts/notion_sync_consumer.py`
- Create: `tests/test_notion_sync_consumer.py`

**Interfaces:**
- Consumes: `lib.git_sync.fetch_main`, `lib.git_sync.show_main`, `lib.notion_queue.parse_jsonl`, `lib.slack_post.open_dm`, `lib.slack_post.post_message`.
- Produces (module-level, importable for tests):
  - `fresh_entries() -> list[dict]` — queue on `origin/main` minus seen-set.
  - `mark_seen(ids: list[str]) -> int` — add ids to seen-set; returns newly-added count.
  - `record_pending(entry: dict) -> None` — append entry (with `status:"pending"`) to the pending store.
  - `build_summary(payload: dict, today: str) -> str` — `payload = {applied: list, flagged: list[str], pending: list[dict]}`; returns Slack text, or `""` when nothing was synced.
  - CLI subcommands: `fresh-entries`, `mark-seen <id>…`, `record-pending [--json]`, `summary --today <d> [--json] [--dry-run]`.
- Module constants (monkeypatched in tests): `SEEN_PATH`, `PENDING_PATH`, `QUEUE_REPO_PATH`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_notion_sync_consumer.py
import json
import scripts.notion_sync_consumer as c


def test_fresh_entries_subtracts_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "SEEN_PATH", tmp_path / "seen.json")
    (tmp_path / "seen.json").write_text(json.dumps(["avoma:seen"]))
    queue_text = (
        json.dumps({"id": "avoma:seen", "target": "pipeline"}) + "\n"
        + json.dumps({"id": "avoma:fresh", "target": "onboarding"}) + "\n"
    )
    monkeypatch.setattr(c, "fetch_main_ref", lambda: True)
    monkeypatch.setattr(c, "read_main_queue", lambda: queue_text)
    fresh = c.fresh_entries()
    assert [e["id"] for e in fresh] == ["avoma:fresh"]


def test_mark_seen_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "SEEN_PATH", tmp_path / "seen.json")
    assert c.mark_seen(["a", "b"]) == 2
    assert c.mark_seen(["b", "c"]) == 1  # only c is new
    assert c._load_seen() == {"a", "b", "c"}


def test_record_pending_appends_with_status(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "PENDING_PATH", tmp_path / "pending.jsonl")
    c.record_pending({"id": "avoma:x", "name": "Alina", "target": "onboarding"})
    lines = (tmp_path / "pending.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["name"] == "Alina" and row["status"] == "pending"


def test_build_summary_silent_when_nothing_synced():
    assert c.build_summary({"applied": [], "flagged": [], "pending": []}, "2026-08-13") == ""


def test_build_summary_lists_flagged_and_pending():
    payload = {
        "applied": ["Acme Corp", "Beta LLC"],
        "flagged": ["Created new pipeline record: Beta LLC"],
        "pending": [{"name": "Alina Bushma"}],
    }
    text = c.build_summary(payload, "2026-08-13")
    assert "Notion Sync — 2026-08-13" in text
    assert "Created new pipeline record: Beta LLC" in text
    assert "Alina Bushma" in text
    assert "Synced 2 update(s)" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notion_sync_consumer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.notion_sync_consumer'`

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""Deterministic helpers for the local Cowork → Notion sync routine.

The routine (an in-app scheduled task) calls these subcommands around the LLM
steps that write to Notion via the updater skills:

  fresh-entries    → JSON list of queue entries not yet applied (reads origin/main)
  mark-seen <id>…  → record ids as applied (laptop-local seen-set)
  record-pending   → hold an unmatched onboarding entry for the confirm loop
  summary          → post the morning Slack summary

Never writes to git. The seen-set and pending store are laptop-local (gitignored
under data/state/).
"""
import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from lib.notion_queue import parse_jsonl  # noqa: E402

QUEUE_REPO_PATH = "data/notion_updates_queue.jsonl"
SEEN_PATH = _ROOT / "data" / "state" / "notion_updates_seen.json"
PENDING_PATH = _ROOT / "data" / "state" / "onboarding_pending_confirm.jsonl"


def fetch_main_ref() -> bool:
    from lib.git_sync import fetch_main
    return fetch_main()


def read_main_queue() -> str:
    from lib.git_sync import show_main
    return show_main(QUEUE_REPO_PATH) or ""


def _load_seen() -> set[str]:
    try:
        return set(json.loads(SEEN_PATH.read_text()))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


def fresh_entries() -> list[dict]:
    fetch_main_ref()
    text = read_main_queue()
    seen = _load_seen()
    return [e for e in parse_jsonl(text) if e.get("id") not in seen]


def mark_seen(ids: list[str]) -> int:
    seen = _load_seen()
    before = len(seen)
    seen.update(i for i in ids if i)
    _save_seen(seen)
    return len(seen) - before


def record_pending(entry: dict) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {**entry, "status": "pending"}
    with open(PENDING_PATH, "a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def build_summary(payload: dict, today: str) -> str:
    applied = payload.get("applied", [])
    flagged = payload.get("flagged", [])
    pending = payload.get("pending", [])
    if not applied and not pending:
        return ""  # silent no-op
    lines = [f"📥 Notion Sync — {today}"]
    if flagged:
        lines.append("\n*⚠️ Review these:*")
        lines.extend(f"• {f}" for f in flagged)
    if pending:
        lines.append("\n*New onboarding customers with no record (add manually — auto-confirm lands in Phase 2):*")
        lines.extend(f"• {p.get('name')}" for p in pending)
    lines.append(f"\n_Synced {len(applied)} update(s) to Notion._")
    return "\n".join(lines)


def _post_summary(payload: dict, today: str, dry_run: bool) -> None:
    text = build_summary(payload, today)
    if not text:
        print("(nothing synced — no summary posted)")
        return
    if dry_run:
        print(text)
        return
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    with open(_ROOT / "config.json") as f:
        config = json.load(f)
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    user_id = config.get("avoma", {}).get("slack_user_id", "")
    from lib.slack_post import open_dm, post_message
    channel = open_dm(token, user_id)
    post_message(token, channel, text)
    print("Slack summary posted.")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fresh-entries")
    ms = sub.add_parser("mark-seen")
    ms.add_argument("ids", nargs="+")
    rp = sub.add_parser("record-pending")
    rp.add_argument("--json", help="entry JSON; reads stdin if omitted")
    su = sub.add_parser("summary")
    su.add_argument("--today", required=True)
    su.add_argument("--json", help="payload JSON; reads stdin if omitted")
    su.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.cmd == "fresh-entries":
        print(json.dumps(fresh_entries()))
    elif args.cmd == "mark-seen":
        print(f"marked {mark_seen(args.ids)} new id(s) seen")
    elif args.cmd == "record-pending":
        record_pending(json.loads(args.json or sys.stdin.read()))
        print("pending recorded")
    elif args.cmd == "summary":
        _post_summary(json.loads(args.json or sys.stdin.read()), args.today, args.dry_run)


if __name__ == "__main__":
    main()
```

> Note: tests patch `fetch_main_ref` and `read_main_queue` (thin wrappers) so no git or network runs in unit tests.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notion_sync_consumer.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Smoke-test the CLI end to end (dry run)**

Run:
```bash
echo '{"applied":["Acme"],"flagged":["Created new pipeline record: Acme"],"pending":[{"name":"Alina Bushma"}]}' \
  | python scripts/notion_sync_consumer.py summary --today 2026-08-13 --dry-run
```
Expected: prints the formatted summary including "Acme", the flagged line, and "Alina Bushma".

- [ ] **Step 6: Commit**

```bash
git add scripts/notion_sync_consumer.py tests/test_notion_sync_consumer.py
git commit -m "feat(notion-sync): consumer CLI (fresh-entries, mark-seen, record-pending, summary)"
```

---

### Task 5: Routine prompt + rollout (create task, supervised pre-approval, enable cron)

Author the versioned routine prompt, create the in-app scheduled task, do the one supervised run to pre-approve the toolset, verify against a known day, then enable the weekday cron. This task has no unit test — it ends with a manual verification checklist.

**Files:**
- Create: `scripts/cowork/notion_sync_prompt.md` (canonical routine prompt, versioned in-repo)

**Interfaces:**
- Consumes: `scripts/notion_sync_consumer.py` CLI; managed skills `notion-os-pipeline-updater`, `notion-os-onboarding-updater`.

- [ ] **Step 1: Write the routine prompt**

Create `scripts/cowork/notion_sync_prompt.md` with the exact self-contained prompt (a fresh scheduled run has no conversation memory):

````markdown
Automated morning task: apply the queued Avoma call updates to the Notion trackers, then post one Slack summary. Work autonomously; do not ask questions. Repo root: /Users/trentluecke/dev/Claude-Projects/chief-of-staff (cd there first).

1. Get fresh queue entries:
   `python scripts/notion_sync_consumer.py fresh-entries`
   Parse the JSON list. If it is empty, STOP — do nothing else, post nothing.

2. Track four lists as you go: applied (names), flagged (strings), pending (entries), processed_ids.

3. For EACH entry, add its `id` to processed_ids, then:
   - If `target` == "pipeline": invoke the `notion-os-pipeline-updater` skill, passing the entry object as the call payload. It updates the record (or creates one if the lead is new). On success add `name` to applied; if `is_new_lead` is true, add "Created new pipeline record: <name>" to flagged; if `inferred_status` implies a stage change, add "Status → <inferred_status>: <name>" to flagged.
   - If `target` == "onboarding": invoke the `notion-os-onboarding-updater` skill with the entry as payload to update the EXISTING record. If it reports NO matching record exists, do NOT create one — instead run:
       `python scripts/notion_sync_consumer.py record-pending --json '<entry as compact JSON>'`
     and add the entry to pending. If it did update an existing record, add `name` to applied.

4. Mark everything processed so it is never reapplied:
   `python scripts/notion_sync_consumer.py mark-seen <space-separated processed_ids>`

5. Post the summary (build the payload JSON from your lists):
   `python scripts/notion_sync_consumer.py summary --today <YYYY-MM-DD today> --json '{"applied": [...], "flagged": [...], "pending": [...]}'`

Rules: only READ/WRITE the specific Notion records named in the entries. Never touch other records. If a single entry errors, skip it (do NOT mark it seen) and continue; note it in flagged as "ERROR applying <name>".
````

- [ ] **Step 2: Commit the prompt**

```bash
git add scripts/cowork/notion_sync_prompt.md
git commit -m "feat(cowork): versioned Notion-sync routine prompt"
```

- [ ] **Step 3: Seed one real queue entry for the supervised test**

So the first run has something to apply, append one entry for a KNOWN, already-existing pipeline lead (pick a real name from `data/pipeline_cache.json`) to origin/main. From the repo:

```bash
python - <<'PY'
import json, subprocess, uuid
from datetime import datetime, timezone
name = "REPLACE_WITH_REAL_PIPELINE_LEAD"
entry = {"id": f"test:{uuid.uuid4()}", "timestamp": datetime.now(timezone.utc).isoformat(),
         "source": "manual", "target": "pipeline", "name": name, "action": "add_note",
         "note": "Cowork sync smoke test — safe to ignore."}
print(json.dumps(entry))
PY
```
Append the printed line to `data/notion_updates_queue.jsonl`, commit, and push to `origin/main` (the consumer reads from there):
```bash
git add data/notion_updates_queue.jsonl
git commit -m "test: seed queue entry for cowork sync smoke test"
git push origin main
```

- [ ] **Step 4: Create the scheduled task (supervised, immediate)**

Using the `scheduled-tasks` MCP `create_scheduled_task`, create task `notion-sync` with `description` "Apply queued Avoma updates to Notion + Slack summary", `cronExpression` `31 8 * * 1-5`, and `prompt` = the full contents of `scripts/cowork/notion_sync_prompt.md`.

Then **"Run now"** on the `notion-sync` task to trigger it immediately while you watch.

- [ ] **Step 5: Approve every tool prompt (the pre-approval pass)**

As the run executes, approve each permission prompt it raises: `Bash` (running the consumer CLI), the `notion-os-pipeline-updater` skill + its Notion write tools, and the Slack post. Approvals persist to the task for all future runs. This is the mandatory one-time pre-approval.

- [ ] **Step 6: Verify the run (manual checklist)**

- [ ] The seeded pipeline lead's Notion record shows the smoke-test note / updated Last-Contacted.
- [ ] A Slack DM summary arrived, listing the applied update.
- [ ] `data/state/notion_updates_seen.json` now contains the seeded entry's `id`.
- [ ] Running the task a SECOND time (Run now) applies nothing and posts no summary (idempotency holds — the entry is now seen).

If any check fails, fix the routine prompt or the consumer, re-commit, recreate the task prompt, and re-run before proceeding.

- [ ] **Step 7: Clean up the smoke-test note and confirm the cron**

Remove the smoke-test note from the seeded Notion record by hand. Confirm the `notion-sync` task's schedule is `31 8 * * 1-5` (enabled) so it runs weekday mornings. Leave the task enabled.

- [ ] **Step 8: Final commit / branch wrap**

```bash
git add -A
git commit -m "chore(cowork-notion-sync): phase 1 rollout complete" || true
```

---

## Rollout order & done criteria

Tasks 1→5 in order (each is independently testable; 1–4 are TDD, 5 is manual).

**Ordering dependency (critical):** Tasks 1–4 must be **merged to `origin/main`** before starting Task 5. The consumer reads the queue via `git show origin/main:data/notion_updates_queue.jsonl`, and the nightly producer commits the queue to `origin/main` — so the `.jsonl` file, the `.gitignore` un-ignore, and the `.gitattributes` union driver all have to exist on `main` first. Merge the branch (PR or local merge + `git push`), then do Task 5's seed/supervised-run against `main`. (Pushing `main` here is the routine sync path — it triggers no workflow; see CLAUDE.md "Pushing main is routine.")

**Phase 1 is done when:** the nightly `avoma_sync` populates the queue on `origin/main`, and the weekday `notion-sync` Cowork routine applies pipeline + onboarding *updates* to Notion and posts a Slack summary, with unmatched onboarding customers listed for manual add. The onboarding **confirm loop** (`confirm_onboarding_create` tool + `create_onboarding` handling) is **Phase 2** — out of scope here.

## Deferred to Phase 2 (not in this plan)

- `confirm_onboarding_create` tool in `processors/query_tools.py`.
- Consumer handling of `action == "create_onboarding"` queue entries.
- Summary wording change from "add manually" to the Telegram confirm phrase.
