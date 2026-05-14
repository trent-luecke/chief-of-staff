# Bot as Trusted Orchestrator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add write confirmations, a Notion update queue, brief customization, and Telegram-gated code changes to the chief-of-staff Telegram bot.

**Architecture:** Four capability additions sharing `processors/query_tools.py` as the primary file, with supporting changes to `processors/query.py` (system prompt), `lib/captures.py` and `processors/brief.py` and `pipeline.py` (brief prefs injection), `ask.py` (approve/reject routing), and `.github/workflows/ask.yml` (data persistence). New data files (`data/notion_updates_queue.json`, `data/brief_prefs.md`) are committed to git via a new ask.yml step so Cowork can read them. `data/pending_change.json` is gitignored and lives on local disk within a single GitHub Actions run — the propose-and-approve cycle completes in two separate runs, so it must survive between runs via the ask.yml data commit step (see Task 7 note).

**Tech Stack:** Python 3.11, Anthropic SDK, difflib (stdlib), tempfile + subprocess (stdlib), GitHub Actions

---

## File Map

**Modified:**
- `processors/query.py` — `_SYSTEM_PROMPT` updated to require explicit write receipts
- `processors/query_tools.py` — 3 new tools, updated write-tool descriptions, new `execute_tool` branches, new `CHANGE_WHITELIST` and `PENDING_CHANGE_PATH` constants
- `lib/captures.py` — new `load_brief_prefs(config)` function
- `processors/brief.py` — `brief_prefs_context` param added to `_build_prompt` and `generate_brief`
- `pipeline.py` — `ProcessedContext` gets `brief_prefs_context` field; `process_context` loads it; `generate_and_deliver` passes it
- `ask.py` — `import subprocess`, `PENDING_CHANGE_PATH` import, `_handle_pending_change` function, approve/reject routing in `_main_inner`
- `.github/workflows/ask.yml` — `permissions: contents: write`, git config step, data commit/push step
- `.gitignore` — add `data/pending_change.json`

**Created:**
- `data/notion_updates_queue.json` — initialized as `[]`
- `tests/test_orchestrator.py` — all new tests

---

## Important note on `pending_change.json` persistence

`propose_code_change` runs in GitHub Actions run #1 and writes `data/pending_change.json` to local disk. The "approve" message arrives as run #2 — a fresh checkout with no local `pending_change.json`. For the approve to work, `pending_change.json` must be committed to git between runs.

**Resolution:** Remove it from `.gitignore`. Add it to the data commit step in `ask.yml`. The spec said "gitignored" to avoid cluttering the repo with machine-written state, but that assumption conflicts with the ephemeral runner. Committing it is the correct fix — it's a small, transient file and the data commit step (`[skip ci]`) keeps it quiet.

---

### Task 1: System prompt and write-tool descriptions

**Files:**
- Modify: `processors/query.py:94-103`
- Modify: `processors/query_tools.py:338-534` (TOOL_SCHEMAS descriptions)
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Create test file with failing test**

```python
# tests/test_orchestrator.py
"""Tests for bot-as-orchestrator capabilities."""

import json
import os
import tempfile

import pytest
from lib.storage import LocalStorage
from processors.query_tools import execute_tool


def _config(tmp_dir: str) -> dict:
    return {
        "data_dir": tmp_dir,
        "captures_file": os.path.join(tmp_dir, "captures.md"),
        "projects_file": os.path.join(tmp_dir, "projects.md"),
        "people_dir": os.path.join(tmp_dir, "people"),
        "issues_file": os.path.join(tmp_dir, "issues.json"),
        "pipeline": {"cache_path": os.path.join(tmp_dir, "pipeline_cache.json")},
        "email": "trent@teambuildr.com",
        "notion_queue_path": os.path.join(tmp_dir, "notion_updates_queue.json"),
        "brief_prefs_path": os.path.join(tmp_dir, "brief_prefs.md"),
    }


def test_system_prompt_requires_receipt():
    from processors.query import _SYSTEM_PROMPT
    prompt_lower = _SYSTEM_PROMPT.lower()
    assert "receipt" in prompt_lower or "here's what i wrote" in prompt_lower or "here's what" in prompt_lower
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_orchestrator.py::test_system_prompt_requires_receipt -v
```
Expected: FAIL

- [ ] **Step 3: Update `_SYSTEM_PROMPT` in `processors/query.py`**

Replace this line in `_SYSTEM_PROMPT` (currently line 98):
```python
# Old:
"When you take a write action, confirm briefly what you did. For config changes, state explicitly what you changed and what it was before. Answer in plain text, 500 characters or fewer unless the query needs more detail."
```

With:
```python
# New:
"When you take one or more write actions, respond with an explicit receipt block:\n\nDone. Here's what I wrote:\n  → [destination]: [content paraphrase]\n  → [destination]: [content paraphrase]\n\nThis will [downstream effect].\n\nDestinations: file path for people notes (e.g. people/jake-torres.md), 'captures', 'Notion queue', 'projects', 'config'. Downstream effects: 'surface in tomorrow's brief', 'queryable from this bot', 'applied to Notion by Cowork on its next scheduled run'. Read-only tools (search_gmail, get_calendar_events, get_person_profile, get_pipeline_lead) need no receipt. Answer in plain text, 500 characters or fewer unless the query needs more detail."
```

- [ ] **Step 4: Run test — verify it passes**

```bash
pytest tests/test_orchestrator.py::test_system_prompt_requires_receipt -v
```
Expected: PASS

- [ ] **Step 5: Update write-tool descriptions in `TOOL_SCHEMAS`**

For each write tool (`add_capture`, `complete_task`, `add_people_note`, `create_person_profile`, `update_project_next_action`, `create_project`, `resolve_issue`, `update_config`, `add_to_backlog`, `create_email_draft`, `set_reminder`), append to the `"description"` string: `" After calling, include a receipt entry in your response naming the destination and content written."`

Example — `add_capture` before:
```python
"description": "Add a todo, idea, note, or flag to the captures file.",
```
After:
```python
"description": "Add a todo, idea, note, or flag to the captures file. After calling, include a receipt entry in your response naming the destination and content written.",
```

Apply the same append to all 11 write tools.

- [ ] **Step 6: Commit**

```bash
git add processors/query.py processors/query_tools.py tests/test_orchestrator.py
git commit -m "feat: system prompt and tool descriptions require write receipts"
```

---

### Task 2: Add `queue_notion_update` tool

**Files:**
- Modify: `processors/query_tools.py`
- Create: `data/notion_updates_queue.json`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_orchestrator.py`:

```python
# ── Task 2: queue_notion_update ──────────────────────────────────────────────

def test_queue_notion_update_add_note():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "queue_notion_update",
            {"person": "Jake Torres", "action": "add_note", "note": "Pricing concern raised"},
            config, storage=storage,
        )
        assert "Jake Torres" in result
        assert "cowork" in result.lower() or "next scheduled" in result.lower()
        with open(config["notion_queue_path"]) as f:
            queue = json.load(f)
        assert len(queue) == 1
        assert queue[0]["person"] == "Jake Torres"
        assert queue[0]["action"] == "add_note"
        assert queue[0]["note"] == "Pricing concern raised"
        assert "id" in queue[0]
        assert "timestamp" in queue[0]


def test_queue_notion_update_delete_requires_reason():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "queue_notion_update",
            {"person": "Jake Torres", "action": "delete_record"},
            config, storage=storage,
        )
        assert "reason" in result.lower()
        assert not os.path.exists(config["notion_queue_path"])


def test_queue_notion_update_invalid_action():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "queue_notion_update",
            {"person": "Jake Torres", "action": "explode"},
            config, storage=storage,
        )
        assert "invalid action" in result.lower()


def test_queue_notion_update_appends_multiple():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        execute_tool("queue_notion_update", {"person": "Alice", "action": "add_note", "note": "First"}, config, storage=storage)
        execute_tool("queue_notion_update", {"person": "Bob", "action": "update_stage", "stage": "Trial"}, config, storage=storage)
        with open(config["notion_queue_path"]) as f:
            queue = json.load(f)
        assert len(queue) == 2
        assert queue[1]["person"] == "Bob"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_orchestrator.py::test_queue_notion_update_add_note tests/test_orchestrator.py::test_queue_notion_update_delete_requires_reason tests/test_orchestrator.py::test_queue_notion_update_invalid_action tests/test_orchestrator.py::test_queue_notion_update_appends_multiple -v
```
Expected: FAIL with `"Unknown tool: 'queue_notion_update'"`

- [ ] **Step 3: Implement `_tool_queue_notion_update` in `processors/query_tools.py`**

Add after `_tool_add_to_backlog` (before `_tool_search_gmail`):

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

    valid_actions = {"add_note", "update_stage", "set_follow_up", "delete_record"}
    if action not in valid_actions:
        return f"Invalid action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}."
    if action == "delete_record" and not reason:
        return "reason is required for delete_record actions."

    queue_path = config.get("notion_queue_path", "data/notion_updates_queue.json")
    try:
        with open(queue_path) as f:
            queue = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        queue = []

    entry: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "person": person,
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

    queue.append(entry)
    os.makedirs(os.path.dirname(queue_path) or ".", exist_ok=True)
    with open(queue_path, "w") as f:
        json.dump(queue, f, indent=2)

    action_desc = {
        "add_note": f"note queued for {person}",
        "update_stage": f"stage update to '{stage}' queued for {person}",
        "set_follow_up": f"follow-up date {follow_up_date} queued for {person}",
        "delete_record": f"delete record queued for {person} (reason: {reason})",
    }[action]
    return f"Notion queue: {action_desc}. Cowork will apply this on its next scheduled run."
```

- [ ] **Step 4: Add schema to `TOOL_SCHEMAS` (append before closing `]`)**

```python
    {
        "name": "queue_notion_update",
        "description": (
            "Queue an update to a Notion pipeline record. Cowork applies queued updates on its next scheduled run. "
            "Supported actions: add_note (append note to record), update_stage (change deal stage), "
            "set_follow_up (set a follow-up date), delete_record (delete the record — requires reason field). "
            "After calling, include a receipt entry naming the person, action queued, and that Cowork will apply it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person": {"type": "string", "description": "Name of the person whose Notion pipeline record to update"},
                "action": {
                    "type": "string",
                    "enum": ["add_note", "update_stage", "set_follow_up", "delete_record"],
                    "description": "Action to queue",
                },
                "note": {"type": "string", "description": "Note text (for add_note)"},
                "stage": {"type": "string", "description": "New deal stage (for update_stage)"},
                "follow_up_date": {"type": "string", "description": "Follow-up date YYYY-MM-DD (for set_follow_up)"},
                "reason": {"type": "string", "description": "Reason for deletion — required for delete_record"},
            },
            "required": ["person", "action"],
        },
    },
```

- [ ] **Step 5: Add dispatch branch in `execute_tool` (before the `else` clause)**

```python
        elif name == "queue_notion_update":
            return _tool_queue_notion_update(
                person=input_["person"],
                action=input_["action"],
                config=config,
                note=input_.get("note", ""),
                stage=input_.get("stage", ""),
                follow_up_date=input_.get("follow_up_date", ""),
                reason=input_.get("reason", ""),
            )
```

- [ ] **Step 6: Initialize the queue file**

```bash
echo "[]" > data/notion_updates_queue.json
```

- [ ] **Step 7: Run tests — verify they pass**

```bash
pytest tests/test_orchestrator.py::test_queue_notion_update_add_note tests/test_orchestrator.py::test_queue_notion_update_delete_requires_reason tests/test_orchestrator.py::test_queue_notion_update_invalid_action tests/test_orchestrator.py::test_queue_notion_update_appends_multiple -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add processors/query_tools.py data/notion_updates_queue.json tests/test_orchestrator.py
git commit -m "feat: add queue_notion_update tool for Cowork pipeline sync"
```

---

### Task 3: Add `set_brief_preference` tool and `load_brief_prefs`

**Files:**
- Modify: `processors/query_tools.py`
- Modify: `lib/captures.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_orchestrator.py`:

```python
# ── Task 3: set_brief_preference ─────────────────────────────────────────────
from lib.captures import load_brief_prefs


def test_set_brief_preference_writes_to_file():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "set_brief_preference",
            {"preference": "Skip the gym scout section this week"},
            config, storage=storage,
        )
        assert "preference" in result.lower() or "brief" in result.lower()
        with open(config["brief_prefs_path"]) as f:
            content = f.read()
        assert "Skip the gym scout section this week" in content


def test_set_brief_preference_appends_multiple():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        execute_tool("set_brief_preference", {"preference": "First pref"}, config, storage=storage)
        execute_tool("set_brief_preference", {"preference": "Second pref"}, config, storage=storage)
        with open(config["brief_prefs_path"]) as f:
            content = f.read()
        assert "First pref" in content
        assert "Second pref" in content


def test_load_brief_prefs_returns_empty_when_missing():
    with tempfile.TemporaryDirectory() as tmp:
        config = {"brief_prefs_path": os.path.join(tmp, "brief_prefs.md")}
        result = load_brief_prefs(config)
        assert result == ""


def test_load_brief_prefs_returns_content():
    with tempfile.TemporaryDirectory() as tmp:
        prefs_path = os.path.join(tmp, "brief_prefs.md")
        with open(prefs_path, "w") as f:
            f.write("## 2026-05-14\n- Skip gym scout\n")
        config = {"brief_prefs_path": prefs_path}
        result = load_brief_prefs(config)
        assert "Skip gym scout" in result
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_orchestrator.py -k "brief_pref" -v
```
Expected: FAIL

- [ ] **Step 3: Implement `_tool_set_brief_preference` in `processors/query_tools.py`**

Add after `_tool_queue_notion_update`:

```python
def _tool_set_brief_preference(preference: str, config: dict) -> str:
    prefs_path = config.get("brief_prefs_path", "data/brief_prefs.md")
    today = date.today().isoformat()
    header = f"## {today}"
    try:
        with open(prefs_path) as f:
            content = f.read()
    except FileNotFoundError:
        content = ""

    if header in content:
        idx = content.index(header) + len(header)
        next_section = content.find("\n##", idx)
        if next_section == -1:
            content = content.rstrip("\n") + f"\n- {preference}\n"
        else:
            content = content[:next_section] + f"\n- {preference}" + content[next_section:]
    else:
        content = content.rstrip("\n") + f"\n\n{header}\n- {preference}\n"

    os.makedirs(os.path.dirname(prefs_path) or ".", exist_ok=True)
    with open(prefs_path, "w") as f:
        f.write(content)
    return f"Brief preference set: {preference}. Takes effect in tomorrow's brief."
```

- [ ] **Step 4: Add schema to `TOOL_SCHEMAS`**

```python
    {
        "name": "set_brief_preference",
        "description": (
            "Set a preference that controls what appears in the morning brief. Preferences are freeform text "
            "and take effect in the next brief run. Examples: 'skip gym scout section this week', "
            "'always lead with pipeline follow-ups', 'remind me about Jake Torres tomorrow'. "
            "To clear or override a preference, call this with a correcting statement "
            "e.g. 'remove the gym scout skip'. "
            "After calling, include a receipt entry naming the preference set and when it takes effect."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "preference": {"type": "string", "description": "Freeform preference instruction for the morning brief"},
            },
            "required": ["preference"],
        },
    },
```

- [ ] **Step 5: Add dispatch branch in `execute_tool`**

```python
        elif name == "set_brief_preference":
            return _tool_set_brief_preference(input_["preference"], config)
```

- [ ] **Step 6: Add `load_brief_prefs` to `lib/captures.py`**

Append to `lib/captures.py`:

```python
def load_brief_prefs(config: dict, token_budget: int = 600) -> str:
    prefs_path = config.get("brief_prefs_path", "data/brief_prefs.md")
    try:
        with open(prefs_path) as f:
            content = f.read()
    except FileNotFoundError:
        return ""
    max_chars = token_budget * 4
    return content[-max_chars:] if len(content) > max_chars else content
```

- [ ] **Step 7: Run tests — verify they pass**

```bash
pytest tests/test_orchestrator.py -k "brief_pref" -v
```
Expected: PASS (4 tests)

- [ ] **Step 8: Commit**

```bash
git add processors/query_tools.py lib/captures.py tests/test_orchestrator.py
git commit -m "feat: add set_brief_preference tool and load_brief_prefs"
```

---

### Task 4: Wire brief_prefs into the daily brief

**Files:**
- Modify: `pipeline.py` — `ProcessedContext` dataclass, `process_context`, `generate_and_deliver`
- Modify: `processors/brief.py` — `_build_prompt` and `generate_brief`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_orchestrator.py`:

```python
# ── Task 4: brief prefs in daily brief ───────────────────────────────────────

def test_build_prompt_includes_brief_prefs():
    from processors.brief import _build_prompt
    result = _build_prompt(
        today_events=[], tomorrow_events=[], email_threads=[], projects=[],
        due_tasks=[], loop_summary=None, open_issues=[], drafts=[],
        meeting_prep=[], inbox_text="",
        brief_prefs_context="- Skip gym scout section\n- Lead with pipeline",
    )
    assert "Skip gym scout section" in result
    assert "Lead with pipeline" in result
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/test_orchestrator.py::test_build_prompt_includes_brief_prefs -v
```
Expected: FAIL with `TypeError: _build_prompt() got an unexpected keyword argument 'brief_prefs_context'`

- [ ] **Step 3: Add `brief_prefs_context` field to `ProcessedContext` in `pipeline.py`**

Find the `ProcessedContext` dataclass. Add the field after `brief_feedback_context`:

```python
    brief_prefs_context: str = ""
```

- [ ] **Step 4: Load brief_prefs in `process_context` in `pipeline.py`**

After `ctx.brief_feedback_context = load_brief_feedback(storage)` (around line 707), add:

```python
        from lib.captures import load_brief_prefs
        ctx.brief_prefs_context = load_brief_prefs(config)
```

- [ ] **Step 5: Pass `brief_prefs_context` to `generate_brief` in `pipeline.py`**

Find the `generate_brief(...)` call in `generate_and_deliver`. Add the kwarg:

```python
                    brief_prefs_context=ctx.brief_prefs_context,
```

- [ ] **Step 6: Add `brief_prefs_context` to `_build_prompt` signature in `processors/brief.py`**

Add to the `_build_prompt` function signature after `brief_feedback_context: str = ""`:

```python
    brief_prefs_context: str = "",
```

- [ ] **Step 7: Inject into `_build_prompt` body**

In `_build_prompt`, after the `brief_feedback_context` block (the block ending around line 120), add:

```python
    if brief_prefs_context:
        sections += [
            "## Active Brief Preferences (follow these when writing the brief)",
            brief_prefs_context,
            "",
        ]
```

- [ ] **Step 8: Add `brief_prefs_context` to `generate_brief` signature and pass-through**

Add to `generate_brief` signature after `brief_feedback_context: str = ""`:

```python
    brief_prefs_context: str = "",
```

And add to the `_build_prompt(...)` call inside `generate_brief`:

```python
        brief_prefs_context=brief_prefs_context,
```

- [ ] **Step 9: Run test — verify it passes**

```bash
pytest tests/test_orchestrator.py::test_build_prompt_includes_brief_prefs -v
```
Expected: PASS

- [ ] **Step 10: Run brief test suite — verify no regressions**

```bash
pytest test_brief.py test_brief_extended.py -v
```
Expected: All pass

- [ ] **Step 11: Commit**

```bash
git add pipeline.py processors/brief.py tests/test_orchestrator.py
git commit -m "feat: inject brief preferences into daily brief prompt"
```

---

### Task 5: Add `propose_code_change` tool

**Files:**
- Modify: `processors/query_tools.py` — new constants, new function, schema, dispatch
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_orchestrator.py`:

```python
# ── Task 5: propose_code_change ───────────────────────────────────────────────
from unittest.mock import patch, MagicMock


def test_propose_code_change_rejects_non_whitelisted_file():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "propose_code_change",
            {"file": "cloudflare/telegram-bridge.js", "description": "test", "new_content": "x"},
            config, storage=storage,
        )
        assert "whitelist" in result.lower() or "not on the" in result.lower()


def test_propose_code_change_rejects_syntax_error():
    with tempfile.TemporaryDirectory() as tmp:
        bad_python = "def broken(\n  print('hello')\n"
        config = _config(tmp)
        storage = LocalStorage(tmp)
        pending_path = os.path.join(tmp, "pending_change.json")
        with patch("processors.query_tools.PENDING_CHANGE_PATH", pending_path):
            with patch("processors.query_tools.CHANGE_WHITELIST", frozenset({"processors/query.py"})):
                result = execute_tool(
                    "propose_code_change",
                    {"file": "processors/query.py", "description": "break it", "new_content": bad_python},
                    config, storage=storage,
                )
        assert "syntax" in result.lower() or "failed" in result.lower()
        assert not os.path.exists(pending_path)


def test_propose_code_change_blocks_if_pending_exists():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        pending_path = os.path.join(tmp, "pending_change.json")
        with open(pending_path, "w") as f:
            json.dump({"file": "main.py", "description": "old change", "new_content": "# old"}, f)
        with patch("processors.query_tools.PENDING_CHANGE_PATH", pending_path):
            result = execute_tool(
                "propose_code_change",
                {"file": "main.py", "description": "new change", "new_content": "# new"},
                config, storage=storage,
            )
        assert "pending" in result.lower()
        assert "approve" in result.lower() or "reject" in result.lower()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_orchestrator.py::test_propose_code_change_rejects_non_whitelisted_file tests/test_orchestrator.py::test_propose_code_change_rejects_syntax_error tests/test_orchestrator.py::test_propose_code_change_blocks_if_pending_exists -v
```
Expected: FAIL with `"Unknown tool: 'propose_code_change'"`

- [ ] **Step 3: Add constants to `processors/query_tools.py`** (after `SAFE_CONFIG_KEYS`):

```python
CHANGE_WHITELIST = frozenset({
    "processors/query_tools.py",
    "processors/query.py",
    "main.py",
    "config.json",
})

PENDING_CHANGE_PATH = "data/pending_change.json"
```

- [ ] **Step 4: Implement `_tool_propose_code_change` in `processors/query_tools.py`** (add before `execute_tool`):

```python
def _tool_propose_code_change(file: str, description: str, new_content: str) -> str:
    import difflib
    import subprocess
    import tempfile as _tempfile
    from datetime import datetime, timezone

    if file not in CHANGE_WHITELIST:
        allowed = ", ".join(sorted(CHANGE_WHITELIST))
        return f"File '{file}' is not on the change whitelist. Allowed: {allowed}."

    if os.path.exists(PENDING_CHANGE_PATH):
        try:
            with open(PENDING_CHANGE_PATH) as f:
                existing = json.load(f)
            return (
                f"Pending change already exists for '{existing.get('file', '?')}': "
                f"{existing.get('description', '?')}. Approve or reject it first."
            )
        except Exception:
            pass  # Corrupt file — overwrite

    try:
        with open(file) as f:
            old_content = f.read()
    except FileNotFoundError:
        old_content = ""

    if file.endswith(".py"):
        with _tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(new_content)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["python", "-m", "py_compile", tmp_path],
                capture_output=True, text=True,
            )
        finally:
            os.unlink(tmp_path)
        if result.returncode != 0:
            error = result.stderr.replace(tmp_path, file)
            return f"Syntax check failed — change not sent:\n{error.strip()}"

    diff_lines = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{file}",
        tofile=f"b/{file}",
    ))
    diff_text = "".join(diff_lines) if diff_lines else "(no changes detected)"

    pending = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file": file,
        "description": description,
        "diff": diff_text,
        "new_content": new_content,
    }
    os.makedirs(os.path.dirname(PENDING_CHANGE_PATH) or ".", exist_ok=True)
    with open(PENDING_CHANGE_PATH, "w") as f:
        json.dump(pending, f, indent=2)

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("QUERY_CHAT_ID", "")
    if bot_token and chat_id:
        from lib.telegram import send_message
        MAX_DIFF = 3500
        diff_display = diff_text[:MAX_DIFF]
        if len(diff_text) > MAX_DIFF:
            diff_display += f"\n... (truncated at {MAX_DIFF} chars)"
        msg = (
            f"Proposed change to `{file}`:\n"
            f"_{description}_\n\n"
            f"```\n{diff_display}\n```\n\n"
            f"Reply 'approve' or 'reject'."
        )
        send_message(bot_token, chat_id, msg)

    return f"Proposed change to {file} sent to Telegram for your approval. Reply 'approve' or 'reject'."
```

- [ ] **Step 5: Add schema to `TOOL_SCHEMAS`**

```python
    {
        "name": "propose_code_change",
        "description": (
            "Propose a change to a whitelisted system file. Reads the current file, runs a Python syntax check "
            "on the new content (for .py files), and sends the unified diff to Telegram for approval. "
            "You must provide the COMPLETE new file content — not a partial patch. "
            "Whitelisted files: processors/query_tools.py, processors/query.py, main.py, config.json. "
            "Only one pending change is allowed at a time. The user replies 'approve' or 'reject' to proceed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Relative path to the file (must be on the whitelist)"},
                "description": {"type": "string", "description": "One-sentence description of what the change does"},
                "new_content": {"type": "string", "description": "Complete new content for the file (full file, not a patch)"},
            },
            "required": ["file", "description", "new_content"],
        },
    },
```

- [ ] **Step 6: Add dispatch branch in `execute_tool`**

```python
        elif name == "propose_code_change":
            return _tool_propose_code_change(
                file=input_["file"],
                description=input_["description"],
                new_content=input_["new_content"],
            )
```

- [ ] **Step 7: Run tests — verify they pass**

```bash
pytest tests/test_orchestrator.py::test_propose_code_change_rejects_non_whitelisted_file tests/test_orchestrator.py::test_propose_code_change_rejects_syntax_error tests/test_orchestrator.py::test_propose_code_change_blocks_if_pending_exists -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add processors/query_tools.py tests/test_orchestrator.py
git commit -m "feat: add propose_code_change tool with syntax check and Telegram diff"
```

---

### Task 6: Approve/reject routing in ask.py

**Files:**
- Modify: `ask.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_orchestrator.py`:

```python
# ── Task 6: approve/reject routing ───────────────────────────────────────────
import subprocess as _subprocess
from unittest.mock import patch, MagicMock, call


def _write_pending_change(path: str, file_rel: str, new_content: str, description: str = "test change") -> None:
    with open(path, "w") as f:
        json.dump({
            "timestamp": "2026-05-14T10:00:00Z",
            "file": file_rel,
            "description": description,
            "diff": "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new\n",
            "new_content": new_content,
        }, f)


def test_handle_pending_change_reject_deletes_file():
    with tempfile.TemporaryDirectory() as tmp:
        pending_path = os.path.join(tmp, "pending_change.json")
        _write_pending_change(pending_path, "main.py", "# new\n")
        with patch("ask.PENDING_CHANGE_PATH", pending_path):
            with patch("ask.send_message") as mock_send:
                from ask import _handle_pending_change
                _handle_pending_change("reject", "123", "fake-token")
        assert not os.path.exists(pending_path)
        mock_send.assert_called_once()
        assert "rejected" in mock_send.call_args[0][2].lower()


def test_handle_pending_change_approve_writes_and_commits():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "main.py")
        with open(target, "w") as f:
            f.write("# old\n")
        pending_path = os.path.join(tmp, "pending_change.json")
        _write_pending_change(pending_path, target, "# new content\n")
        with patch("ask.PENDING_CHANGE_PATH", pending_path):
            with patch("ask.send_message") as mock_send:
                with patch("ask.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    from ask import _handle_pending_change
                    _handle_pending_change("approve", "123", "fake-token")
        with open(target) as f:
            assert f.read() == "# new content\n"
        assert not os.path.exists(pending_path)
        mock_send.assert_called_once()
        assert "applied" in mock_send.call_args[0][2].lower()
        # verify git commands were called
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("git" in c for c in calls)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_orchestrator.py::test_handle_pending_change_reject_deletes_file tests/test_orchestrator.py::test_handle_pending_change_approve_writes_and_commits -v
```
Expected: FAIL (no `_handle_pending_change` or `PENDING_CHANGE_PATH` in ask.py)

- [ ] **Step 3: Add imports to `ask.py`**

Add to the top import block (after `import sys`):

```python
import subprocess
```

Add after the existing `from lib.telegram import send_message` line:

```python
from processors.query_tools import PENDING_CHANGE_PATH
```

- [ ] **Step 4: Add `_handle_pending_change` to `ask.py`** (before `_main_inner`):

```python
def _handle_pending_change(action: str, chat_id: str, bot_token: str) -> None:
    try:
        with open(PENDING_CHANGE_PATH) as f:
            pending = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        if bot_token:
            send_message(bot_token, chat_id, f"Could not read pending change: {e}")
        return

    file_path = pending.get("file", "")
    description = pending.get("description", "")

    if action == "reject":
        os.remove(PENDING_CHANGE_PATH)
        if bot_token:
            send_message(bot_token, chat_id, f"Change to {file_path} rejected and discarded.")
        return

    new_content = pending.get("new_content", "")
    try:
        with open(file_path, "w") as f:
            f.write(new_content)
    except OSError as e:
        if bot_token:
            send_message(bot_token, chat_id, f"Could not write {file_path}: {e}")
        return

    commit_msg = f"bot: {description} [telegram-approved]"
    try:
        subprocess.run(["git", "add", file_path], check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
    except subprocess.CalledProcessError as e:
        if bot_token:
            send_message(bot_token, chat_id, f"Git error after applying change: {e}")
        return

    os.remove(PENDING_CHANGE_PATH)
    if bot_token:
        send_message(bot_token, chat_id, f"Change to {file_path} applied and pushed. Commit: \"{commit_msg}\"")
```

- [ ] **Step 5: Add approve/reject routing in `_main_inner`**

At the very top of `_main_inner` (before the nudge reply check), add:

```python
    # Approve/reject pending code change — exact match only
    query_normalized = query.strip().lower()
    if query_normalized in ("approve", "reject") and os.path.exists(PENDING_CHANGE_PATH):
        _handle_pending_change(query_normalized, chat_id, bot_token)
        return
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
pytest tests/test_orchestrator.py::test_handle_pending_change_reject_deletes_file tests/test_orchestrator.py::test_handle_pending_change_approve_writes_and_commits -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add ask.py tests/test_orchestrator.py
git commit -m "feat: approve/reject routing for pending code changes in ask.py"
```

---

### Task 7: Data persistence, ask.yml, gitignore

**Files:**
- Modify: `.github/workflows/ask.yml`
- Modify: `.gitignore`

- [ ] **Step 1: Add `data/pending_change.json` to `.gitignore`**

Open `.gitignore` and add:

```
data/pending_change.json
```

Wait — see the note at the top of this plan. `pending_change.json` must survive between GitHub Actions runs. **Remove `data/pending_change.json` from `.gitignore`** (do not add it). Instead, it will be committed as part of the data commit step below.

- [ ] **Step 2: Add `permissions` to `ask.yml`**

In `.github/workflows/ask.yml`, add a `permissions` block to the `answer` job (after `runs-on: ubuntu-latest`):

```yaml
    permissions:
      contents: write
```

- [ ] **Step 3: Add git config step to `ask.yml`** (before "Answer query"):

```yaml
      - name: Configure git
        run: |
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git config user.name "github-actions[bot]"
```

- [ ] **Step 4: Add data commit/push step to `ask.yml`** (after "Answer query"):

```yaml
      - name: Commit data files
        run: |
          git add data/notion_updates_queue.json data/brief_prefs.md data/pending_change.json data/people/ data/projects.md 2>/dev/null || true
          git diff --staged --quiet || git commit -m "chore: sync bot data [skip ci]"
          git push origin main || true
```

The `|| true` on `git add` handles missing files. `git diff --staged --quiet || git commit` skips commit when nothing changed. `git push || true` handles the case where the code-change approve already pushed (avoids double-push failure).

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v --ignore=tests/test_memory_retriever_integration.py --ignore=tests/test_vector_ingest_integration.py
```
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add .gitignore .github/workflows/ask.yml
git commit -m "chore: add data persistence and git config to ask.yml"
```

---

## Self-Review

**Spec coverage:**
- Section 1 (write confirmation): Task 1 ✓
- Section 2 (Notion queue, all 4 actions, delete safety rule): Task 2 ✓ — delete safety (Cowork-side conflict detection) is Cowork's responsibility, not this code's; the `reason` requirement is enforced ✓
- Section 3 (brief customization, clearing via correction): Task 3 + Task 4 ✓ — clearing via appended correction entry is supported by the freeform design ✓
- Section 4 (propose tool, syntax check, whitelist, single pending, approve/reject exact match, commit message, push to main): Task 5 + Task 6 ✓
- Data files table: `notion_updates_queue.json` initialized ✓, `brief_prefs.md` written by tool ✓, `pending_change.json` committed (not gitignored) ✓ — with explanation of why the spec's gitignore assumption was revised

**Type consistency:**
- `_tool_queue_notion_update` returns `str` ✓; dispatched with `input_["person"]`, `input_["action"]` ✓
- `_tool_set_brief_preference` takes `preference: str, config: dict` ✓; dispatched with `input_["preference"], config` ✓
- `_tool_propose_code_change` takes `file: str, description: str, new_content: str` (no config — reads env directly) ✓; dispatched with `input_["file"]`, `input_["description"]`, `input_["new_content"]` ✓
- `load_brief_prefs(config: dict)` ✓; called as `load_brief_prefs(config)` in pipeline.py ✓
- `PENDING_CHANGE_PATH` is `str` constant imported into `ask.py` ✓
- `CHANGE_WHITELIST` is `frozenset` ✓; `file not in CHANGE_WHITELIST` ✓
- `brief_prefs_context: str = ""` added to `_build_prompt`, `generate_brief`, and `ProcessedContext` — all consistent ✓

**Placeholder scan:** No TBDs, TODOs, or "similar to Task N" references found.
