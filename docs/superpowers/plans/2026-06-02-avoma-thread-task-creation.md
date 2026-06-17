# Avoma Thread Task Creation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Trent select action items from an Avoma call thread in Slack ("add 1, 3") and have them land in the single shared task pool via `lib/tasks.add_task`, tagged `source="avoma"` with a call back-reference.

**Architecture:** A new deterministic routing branch in `processors/avoma_phase2.run_phase2` detects task-selection syntax by regex (no Claude call needed), reads `action_items` from the already-persisted `transcript_json`, calls `lib/tasks.add_task` for each selected item, then `_sync_canvas`. The only new schema change is an optional `metadata` field on the task dict in `lib/tasks`. No new state files, no new endpoints, no Avoma-specific storage.

**Tech Stack:** Python 3.11, existing `lib/tasks.py`, `processors/avoma_phase2.py`, `processors/query_tools._sync_canvas`, `lib/slack_post.post_to_thread`, pytest.

---

## Investigation Summary (read before touching code)

### Current Phase 2 routing in `processors/avoma_phase2.run_phase2`

```
if pending_correction and trigger in _CONFIRMATIONS → apply correction
if pending_correction and trigger in _REJECTIONS   → cancel correction
else                                                → _handle_fresh_message (Claude)
```

Task selection goes in as a **third branch before `_handle_fresh_message`**:

```
if pending_correction and trigger in _CONFIRMATIONS → apply correction
if pending_correction and trigger in _REJECTIONS   → cancel correction
if _is_task_selection(trigger)                      → _handle_task_selection   ← NEW
else                                                → _handle_fresh_message (Claude)
```

### What action items look like in state

Phase 1 stores `transcript_json["action_items"]` as a `list[str]` in
`state/avoma_thread_state.json`. Phase 1 also posts them to Slack as numbered lines:

```
*Action Items*
1. Send pricing deck to Sarah
2. Schedule follow-up for next Tuesday
3. Get IT contact from their side
```

The indices Trent uses in the thread map 1-for-1 to this list.

### `lib/tasks.add_task` current signature

```python
def add_task(storage, title: str, source: str = "telegram", due_date: Optional[str] = None) -> dict
```

Task dict today: `id`, `title`, `status`, `created_at`, `due_date`, `source`, `completed_at`.  
**No `metadata` field.** Adding it (optional, defaults to `{}`) is backward-compatible — existing
callers pass nothing and get an empty dict.

### `_sync_canvas` lives in `processors/query_tools`

```python
def _sync_canvas(config: dict, storage) -> None:
```

Uses `os.environ.get("SLACK_USER_TOKEN", "")`. **`SLACK_USER_TOKEN` is NOT present in
`.github/workflows/avoma_slack_trigger.yml`** — the workflow only sets `SLACK_BOT_TOKEN`.
Without this secret the canvas sync silently skips (already non-fatal). It must be added
to the workflow env for canvas updates to actually fire.

### Existing source values

`"telegram"`, `"gmail"`, `"slack"`, `"notion"` are all live. `"avoma"` is referenced in
script logs/wanderer but **not yet used as a task source**. It's the right value here.

### Telegram pending_avoma_tasks — NOT reused here

`state/pending_avoma_tasks.json` (keyed by Telegram message ID) exists in `ask.py` for a
different proposal flow. The Slack thread flow doesn't need a pending state: "add 1, 3"
is itself the confirmation. Read, create tasks, ack — no staging needed.

### One-ledger invariant

All paths must call `add_task(storage, ...)`, which writes to `data/tasks.json`.
No Avoma-specific task file. The only way this invariant can be violated is if someone
adds a write to a separate JSON outside `lib/tasks`. Don't.

---

## Task metadata shape

```python
{
    "avoma_uuid": "uuid-abc123",         # Avoma call UUID; links to transcript
    "thread_ts":  "1717308000.123456",   # Slack thread_ts; links back to the thread
    "call_title": "Demo - Acme Corp",    # human-readable call name
    "call_date":  "2026-06-01",          # ISO date extracted from start_at[:10]
}
```

Stored at `task["metadata"]`. Flat; no nesting. Queryable by `avoma_uuid` to reconstruct
the task → call → person chain.

---

## File Map

| File | Change |
|------|--------|
| `lib/tasks.py` | Add `metadata: Optional[dict] = None` param; include in task dict |
| `processors/avoma_phase2.py` | New imports, `_TASK_ADD_PATTERN`, `_is_task_selection`, `_parse_task_indices`, `_handle_task_selection`; update `run_phase2` routing |
| `.github/workflows/avoma_slack_trigger.yml` | Add `SLACK_USER_TOKEN: ${{ secrets.SLACK_USER_TOKEN }}` to env block |
| `tests/test_tasks.py` | New file — tests for metadata field on `add_task` |
| `tests/test_avoma_phase2.py` | New tests for task-selection path |

---

## Task 1: Add `metadata` field to `add_task`

**Files:**
- Modify: `lib/tasks.py:16-29`
- Create: `tests/test_tasks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tasks.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_tasks.py -v
```

Expected: `FAILED` — `add_task() got an unexpected keyword argument 'metadata'`

- [ ] **Step 3: Implement**

In `lib/tasks.py`, update the `add_task` function:

```python
def add_task(storage, title: str, source: str = "telegram", due_date: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
    data = _load(storage)
    task = {
        "id": f"t-{uuid.uuid4().hex[:6]}",
        "title": title,
        "status": "open",
        "created_at": date.today().isoformat(),
        "due_date": due_date,
        "source": source,
        "completed_at": None,
        "metadata": metadata or {},
    }
    data["tasks"].append(task)
    _save(storage, data)
    return task
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_tasks.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Run full test suite to check no regressions**

```
pytest --tb=short -q
```

Expected: all passing (existing callers don't pass `metadata`, default is `{}`)

- [ ] **Step 6: Commit**

```bash
git add lib/tasks.py tests/test_tasks.py
git commit -m "feat: add optional metadata field to add_task"
```

---

## Task 2: Task-selection routing in Phase 2

**Files:**
- Modify: `processors/avoma_phase2.py`
- Modify: `tests/test_avoma_phase2.py`

### 2a — Tests first

- [ ] **Step 1: Write failing tests — add to `tests/test_avoma_phase2.py`**

Add these cases after the existing four tests. They use the same `_storage`, `_state_record`, `_config` helpers already in that file.

```python
# ---- Task-selection tests ----

def _state_record_with_actions(action_items):
    return {
        "phase": 2,
        "avoma_uuid": "uuid-abc",
        "processed_at": "2026-06-02T14:00:00+00:00",
        "output_ts": "ts.999",
        "phase1_output": "some output",
        "transcript_json": {
            "uuid": "uuid-abc",
            "title": "Demo - Acme Corp",
            "start_at": "2026-06-01T15:00:00Z",
            "action_items": action_items,
        },
        "pending_correction": None,
    }


def test_task_selection_add_single(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions(["Send pricing deck", "Schedule follow-up", "Get IT contact"])

    with patch("processors.avoma_phase2.post_to_thread") as mock_post, \
         patch("processors.avoma_phase2._sync_canvas") as mock_canvas:
        run_phase2("t.123", "add 2", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    tasks = get_open_tasks(s)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Schedule follow-up"
    assert tasks[0]["source"] == "avoma"
    assert tasks[0]["metadata"]["avoma_uuid"] == "uuid-abc"
    assert tasks[0]["metadata"]["thread_ts"] == "t.123"
    assert tasks[0]["metadata"]["call_title"] == "Demo - Acme Corp"
    assert tasks[0]["metadata"]["call_date"] == "2026-06-01"
    mock_canvas.assert_called_once()
    mock_post.assert_called_once()
    assert "1 task" in mock_post.call_args[0][3].lower()


def test_task_selection_add_multiple_comma(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions(["Send pricing deck", "Schedule follow-up", "Get IT contact"])

    with patch("processors.avoma_phase2.post_to_thread") as mock_post, \
         patch("processors.avoma_phase2._sync_canvas"):
        run_phase2("t.123", "add 1, 3", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    tasks = get_open_tasks(s)
    assert len(tasks) == 2
    titles = {t["title"] for t in tasks}
    assert titles == {"Send pricing deck", "Get IT contact"}
    assert "2 task" in mock_post.call_args[0][3].lower()


def test_task_selection_add_with_and(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions(["Send pricing deck", "Schedule follow-up", "Get IT contact"])

    with patch("processors.avoma_phase2.post_to_thread"), \
         patch("processors.avoma_phase2._sync_canvas"):
        run_phase2("t.123", "add 1 and 3", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    tasks = get_open_tasks(s)
    assert len(tasks) == 2


def test_task_selection_add_all(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    items = ["Send pricing deck", "Schedule follow-up", "Get IT contact"]
    rec = _state_record_with_actions(items)

    with patch("processors.avoma_phase2.post_to_thread"), \
         patch("processors.avoma_phase2._sync_canvas"):
        run_phase2("t.123", "add all", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    assert len(get_open_tasks(s)) == 3


def test_task_selection_out_of_range_skipped(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions(["Only one item"])

    with patch("processors.avoma_phase2.post_to_thread") as mock_post, \
         patch("processors.avoma_phase2._sync_canvas"):
        run_phase2("t.123", "add 1, 5", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    # index 5 is out of range — only item 1 added
    assert len(get_open_tasks(s)) == 1
    assert "1 task" in mock_post.call_args[0][3].lower()


def test_task_selection_no_action_items(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions([])

    with patch("processors.avoma_phase2.post_to_thread") as mock_post, \
         patch("processors.avoma_phase2._sync_canvas") as mock_canvas:
        run_phase2("t.123", "add 1", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    assert len(get_open_tasks(s)) == 0
    mock_canvas.assert_not_called()
    # bot still acks
    mock_post.assert_called_once()
    assert "no" in mock_post.call_args[0][3].lower() or "0" in mock_post.call_args[0][3]


def test_task_selection_does_not_intercept_question(tmp_path):
    """'add me to the call' should NOT be detected as task selection."""
    from processors.avoma_phase2 import _is_task_selection
    assert not _is_task_selection("add me to the call")
    assert not _is_task_selection("add something about pricing")
    assert not _is_task_selection("can you add a note")


def test_task_selection_pattern_variants():
    from processors.avoma_phase2 import _is_task_selection
    assert _is_task_selection("add 1")
    assert _is_task_selection("Add 1")
    assert _is_task_selection("add 1, 3")
    assert _is_task_selection("add 1 and 3")
    assert _is_task_selection("add 1 2 3")
    assert _is_task_selection("add all")
    assert _is_task_selection("ADD ALL")
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_avoma_phase2.py -v
```

Expected: new tests fail (`ImportError` or `AssertionError` — `_is_task_selection` not yet defined)

### 2b — Implementation

- [ ] **Step 3: Implement task-selection path in `processors/avoma_phase2.py`**

Add at the top of the file, after existing imports:

```python
import re

from lib.tasks import add_task
from processors.query_tools import _sync_canvas
```

After the `_REJECTIONS` frozenset, add:

```python
_TASK_ADD_PATTERN = re.compile(
    r"^add\s+(all|\d[\d,\s]*(?:and\s+\d[\d,\s]*)*)$",
    re.IGNORECASE,
)


def _is_task_selection(text: str) -> bool:
    return bool(_TASK_ADD_PATTERN.match(text.strip()))


def _parse_task_indices(trigger_text: str, action_items: list) -> list[str]:
    """Return the action item strings selected by a 'add N [, M ...]' message."""
    m = re.match(r"^add\s+(.+)$", trigger_text.strip(), re.IGNORECASE)
    if not m:
        return []
    arg = m.group(1).strip().lower()
    if arg == "all":
        return list(action_items)
    # Normalise "and" to space so "1 and 3" → "1   3"
    arg = arg.replace("and", " ")
    indices = [int(n) - 1 for n in re.split(r"[,\s]+", arg) if n.strip().isdigit()]
    return [action_items[i] for i in indices if 0 <= i < len(action_items)]
```

Add the handler function (after `_parse_task_indices`):

```python
def _handle_task_selection(
    thread_ts: str,
    trigger_text: str,
    state_record: dict,
    slack_bot_token: str,
    channel_id: str,
    storage,
    config: dict,
) -> None:
    transcript_json = state_record.get("transcript_json", {})
    action_items = transcript_json.get("action_items") or []
    selected = _parse_task_indices(trigger_text, action_items)

    if not selected:
        post_to_thread(slack_bot_token, channel_id, thread_ts, "No tasks added (no matching action items).")
        return

    metadata = {
        "avoma_uuid": state_record.get("avoma_uuid"),
        "thread_ts": thread_ts,
        "call_title": transcript_json.get("title", ""),
        "call_date": (transcript_json.get("start_at") or "")[:10],
    }
    for item in selected:
        add_task(storage, item, source="avoma", metadata=metadata)

    _sync_canvas(config, storage)

    count = len(selected)
    noun = "task" if count == 1 else "tasks"
    items_display = "\n".join(f"  ✓ {t}" for t in selected)
    post_to_thread(
        slack_bot_token, channel_id, thread_ts,
        f"Added {count} {noun}, canvas synced.\n{items_display}",
    )
```

Update `run_phase2` to insert the new branch (full replacement of the function body):

```python
def run_phase2(
    thread_ts: str,
    trigger_text: str,
    state_record: dict,
    slack_bot_token: str,
    channel_id: str,
    storage,
    config: dict,
    anthropic_api_key: str,
) -> None:
    """Handle a Phase 2 message. Routes to pending correction check or fresh Claude call."""
    pending = state_record.get("pending_correction")
    trigger_lower = trigger_text.strip().lower()

    if pending and trigger_lower in _CONFIRMATIONS:
        _apply_correction(pending, state_record, storage, slack_bot_token, channel_id, thread_ts)
        clear_pending_correction(storage, thread_ts)
        return

    if pending and trigger_lower in _REJECTIONS:
        post_to_thread(slack_bot_token, channel_id, thread_ts, "Correction cancelled.")
        clear_pending_correction(storage, thread_ts)
        return

    if _is_task_selection(trigger_text):
        _handle_task_selection(thread_ts, trigger_text, state_record, slack_bot_token, channel_id, storage, config)
        return

    _handle_fresh_message(thread_ts, trigger_text, state_record, slack_bot_token, channel_id, storage, config, anthropic_api_key)
```

- [ ] **Step 4: Run the new tests to verify they pass**

```
pytest tests/test_avoma_phase2.py -v
```

Expected: all 12 tests passing (4 original + 8 new)

- [ ] **Step 5: Run full test suite**

```
pytest --tb=short -q
```

Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add processors/avoma_phase2.py tests/test_avoma_phase2.py
git commit -m "feat: add task-selection path to Avoma Phase 2 handler"
```

---

## Task 3: Add `SLACK_USER_TOKEN` to the Avoma workflow

**Files:**
- Modify: `.github/workflows/avoma_slack_trigger.yml`

**Why this is required:** `_sync_canvas` reads `os.environ.get("SLACK_USER_TOKEN", "")`. The
canvas API requires a user token (not a bot token). Without it the sync silently skips —
the tasks are added to `data/tasks.json` correctly but the Slack Canvas never updates.

- [ ] **Step 1: Add the secret to the workflow env block**

In `.github/workflows/avoma_slack_trigger.yml`, find the `env:` block under the
`Run Avoma Slack processor` step and add one line:

```yaml
      - name: Run Avoma Slack processor
        env:
          AVOMA_THREAD_TS: ${{ inputs.thread_ts }}
          AVOMA_CHANNEL_ID: ${{ inputs.channel_id }}
          AVOMA_TRIGGER_TEXT: ${{ inputs.trigger_text }}
          AVOMA_API_KEY: ${{ secrets.AVOMA_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
          SLACK_USER_TOKEN: ${{ secrets.SLACK_USER_TOKEN }}   # ← add this line
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
        run: python scripts/avoma_slack_processor.py
```

Verify the `SLACK_USER_TOKEN` secret exists in GitHub repo settings → Secrets and variables
→ Actions. It was set up for the canvas feature — it should already be there.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/avoma_slack_trigger.yml
git commit -m "chore: add SLACK_USER_TOKEN to avoma slack trigger workflow for canvas sync"
```

---

## Self-Review

### Spec coverage

| Requirement | Addressed |
|-------------|-----------|
| Trent selects action items by replying in-thread ("add 1 and 3") | ✓ Task 2 — `_is_task_selection` + `_handle_task_selection` |
| Model never auto-injects all action items | ✓ Detection is opt-in syntax only; falls through to Claude otherwise |
| Selected items route to `add_task(source="avoma")` | ✓ `_handle_task_selection` calls `add_task(storage, item, source="avoma", metadata=...)` |
| `_sync_canvas` triggered after task addition | ✓ Called in `_handle_task_selection`; SLACK_USER_TOKEN wired in Task 3 |
| Bot confirms in-thread ("Added 2 tasks, canvas synced.") | ✓ `post_to_thread` call with count + item list |
| Back-reference metadata on each task | ✓ `metadata = {avoma_uuid, thread_ts, call_title, call_date}` — Task 1 adds field |
| How selection is distinguished from corrections / questions | ✓ Deterministic regex before `_handle_fresh_message`; "add me to the call" does NOT match; pattern requires "add" + digits/all |
| `add_task` signature and existing source values confirmed | ✓ Investigation section documents current state |
| One ledger — no Avoma silo | ✓ All paths write to `data/tasks.json` via `lib/tasks.add_task`. No new state file. Invariant called out explicitly |
| Same endpoint (Avoma Slack bridge) | ✓ Extension of Phase 2 — same Cloudflare Worker → same Actions workflow → same processor |

### Placeholder scan

No TBD, TODO, or "fill in details" in any step. Every code block is complete and runnable.

### Type consistency

- `add_task` gains `metadata: Optional[dict] = None` — all callers tested
- `_handle_task_selection` signature matches how it's called in `run_phase2`
- `_is_task_selection(text: str) -> bool` — called with `trigger_text` (str) in routing, tested directly
- `_parse_task_indices(trigger_text: str, action_items: list) -> list[str]` — called with same in `_handle_task_selection`

### One flag not in scope but worth noting

The `run_phase2` signature doesn't pass `config` today — wait, yes it does: `config: dict` is already parameter 7. `_handle_task_selection` receives `config` and forwards it to `_sync_canvas(config, storage)`. No signature changes needed anywhere outside `lib/tasks.py`.

### Canvas sync note for the executor

`_sync_canvas` is imported from `processors.query_tools` — a private function (leading underscore). This is fine since both modules are in `processors/`. If `_sync_canvas` is ever promoted to `lib/` in a future refactor, update the import in `avoma_phase2.py` at that time.
