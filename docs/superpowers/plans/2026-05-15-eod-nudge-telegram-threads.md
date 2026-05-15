# EOD Nudge + Global Telegram Thread Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scheduled EOD Telegram nudge with the open task list, backed by a general-purpose thread store that gives all multi-turn Telegram conversations persistent context across messages.

**Architecture:** A new `lib/telegram_threads.py` module owns thread state in `data/telegram_threads.json` — every bot response is recorded so any reply can continue with full history. `ask.py` resolves incoming replies against the thread store and enriches the Claude query with prior turns. `eod_nudge.py` sends the scheduled nudge and seeds a typed EOD thread with the tasks snapshot.

**Tech Stack:** Python 3.11, `lib/storage.py` (R2/local abstraction), `lib/telegram.py` (`send_message` already returns `message_id`), GitHub Actions cron, `pytest`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `lib/telegram_threads.py` | **Create** | Thread store: read, write, resolve, append, prune, build enriched query |
| `tests/test_telegram_threads.py` | **Create** | Full test coverage for the thread store module |
| `ask.py` | **Modify** | Integrate thread resolution and creation into `_main_inner` |
| `tests/test_ask_threads.py` | **Create** | Tests for the ask.py thread integration |
| `eod_nudge.py` | **Create** | EOD nudge script: reads tasks, sends message, seeds EOD thread |
| `tests/test_eod_nudge.py` | **Create** | Tests for the nudge formatter and run function |
| `.github/workflows/eod.yml` | **Create** | Cron workflow: Mon–Thu 4PM CDT, Fri 2PM CDT |
| `.github/workflows/ask.yml` | **Modify** | Add `data/telegram_threads.json` to the git commit step |
| `.gitignore` | **Modify** | Add `!data/telegram_threads.json` exception |

---

## Task 1: `lib/telegram_threads.py` — Thread Store

**Files:**
- Create: `lib/telegram_threads.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_telegram_threads.py`:

```python
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from lib.storage import LocalStorage
from lib.telegram_threads import (
    resolve_thread_reply,
    append_thread_turn,
    create_eod_thread,
    build_enriched_query,
)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(str(tmp_path))


def _thread_data(root_id: int, thread_type: str = "general", age_hours: float = 0.0, extra_ids: list = None) -> dict:
    created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {
        "threads": {
            str(root_id): {
                "thread_type": thread_type,
                "created_at": created.isoformat(),
                "context": {},
                "turns": [],
                "all_message_ids": [root_id] + (extra_ids or []),
            }
        }
    }


def test_resolve_finds_root_message_id(storage):
    storage.write_json("telegram_threads.json", _thread_data(100))
    result = resolve_thread_reply("100", storage)
    assert result is not None
    root_id, thread = result
    assert root_id == "100"
    assert thread["thread_type"] == "general"


def test_resolve_finds_subsequent_bot_message_id(storage):
    storage.write_json("telegram_threads.json", _thread_data(100, extra_ids=[101, 102]))
    result = resolve_thread_reply("102", storage)
    assert result is not None
    root_id, _ = result
    assert root_id == "100"


def test_resolve_returns_none_for_unknown_id(storage):
    storage.write_json("telegram_threads.json", _thread_data(100))
    assert resolve_thread_reply("999", storage) is None


def test_resolve_ignores_thread_older_than_24h(storage):
    storage.write_json("telegram_threads.json", _thread_data(100, age_hours=25))
    assert resolve_thread_reply("100", storage) is None


def test_resolve_prunes_threads_older_than_48h(storage):
    data = {
        "threads": {
            "100": {
                "thread_type": "general",
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat(),
                "context": {},
                "turns": [],
                "all_message_ids": [100],
            }
        }
    }
    storage.write_json("telegram_threads.json", data)
    resolve_thread_reply("100", storage)
    stored = storage.read_json("telegram_threads.json")
    assert "100" not in stored["threads"]


def test_append_extends_existing_thread(storage):
    storage.write_json("telegram_threads.json", _thread_data(100))
    append_thread_turn("100", "hello", "world", 101, storage)
    stored = storage.read_json("telegram_threads.json")
    thread = stored["threads"]["100"]
    assert 101 in thread["all_message_ids"]
    assert thread["turns"][0] == {"user": "hello", "bot": "world", "bot_message_id": 101}


def test_append_creates_general_thread_when_no_root(storage):
    root_id = append_thread_turn(None, "hello", "world", 200, storage)
    assert root_id == "200"
    stored = storage.read_json("telegram_threads.json")
    assert "200" in stored["threads"]
    thread = stored["threads"]["200"]
    assert thread["thread_type"] == "general"
    assert thread["all_message_ids"] == [200]
    assert thread["turns"][0]["user"] == "hello"


def test_create_eod_thread_stores_correct_structure(storage):
    tasks = [{"id": "t-1", "title": "Finish proposal"}, {"id": "t-2", "title": "Follow up Acme"}]
    create_eod_thread(500, tasks, storage)
    stored = storage.read_json("telegram_threads.json")
    assert "500" in stored["threads"]
    thread = stored["threads"]["500"]
    assert thread["thread_type"] == "eod"
    assert thread["all_message_ids"] == [500]
    assert thread["turns"] == []
    snapshot = thread["context"]["open_tasks_snapshot"]
    assert snapshot == [{"id": "t-1", "title": "Finish proposal"}, {"id": "t-2", "title": "Follow up Acme"}]


def test_build_enriched_query_eod_no_prior_turns():
    thread = {
        "thread_type": "eod",
        "context": {"open_tasks_snapshot": [{"id": "t-1", "title": "Finish proposal"}]},
        "turns": [],
    }
    result = build_enriched_query(thread, "I finished it", "2026-05-15")
    assert "[EOD CHECK-IN SESSION — 2026-05-15]" in result
    assert "Finish proposal" in result
    assert "Prior conversation:" not in result
    assert "I finished it" in result


def test_build_enriched_query_eod_with_prior_turns():
    thread = {
        "thread_type": "eod",
        "context": {"open_tasks_snapshot": [{"id": "t-1", "title": "Finish proposal"}]},
        "turns": [{"user": "first msg", "bot": "first reply", "bot_message_id": 501}],
    }
    result = build_enriched_query(thread, "second msg", "2026-05-15")
    assert "Prior conversation:" in result
    assert "User: first msg" in result
    assert "You: first reply" in result
    assert "second msg" in result


def test_build_enriched_query_general_with_prior_turns():
    thread = {
        "thread_type": "general",
        "context": {},
        "turns": [{"user": "ask 1", "bot": "ans 1", "bot_message_id": 201}],
    }
    result = build_enriched_query(thread, "ask 2", "2026-05-15")
    assert "[CONTINUING CONVERSATION]" in result
    assert "User: ask 1" in result
    assert "You: ans 1" in result
    assert "ask 2" in result
```

- [ ] **Step 1.2: Run tests — confirm they all fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
.venv/bin/pytest tests/test_telegram_threads.py -v 2>&1 | head -30
```

Expected: `ImportError` or `ModuleNotFoundError` for `lib.telegram_threads`

- [ ] **Step 1.3: Create `lib/telegram_threads.py`**

```python
"""Persistent thread store for multi-turn Telegram conversations."""

from datetime import datetime, timezone, timedelta
from typing import Optional

_THREADS_KEY = "telegram_threads.json"
_ACTIVE_TTL_HOURS = 24
_PRUNE_TTL_HOURS = 48


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load(storage) -> dict:
    return storage.read_json(_THREADS_KEY, default={"threads": {}})


def _save(storage, data: dict) -> None:
    storage.write_json(_THREADS_KEY, data)


def _is_expired(thread: dict, ttl_hours: int) -> bool:
    created = thread.get("created_at", "")
    if not created:
        return True
    try:
        dt = datetime.fromisoformat(created)
        return _now_utc() - dt > timedelta(hours=ttl_hours)
    except ValueError:
        return True


def _parse_message_id(value: str) -> Optional[int]:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def resolve_thread_reply(reply_to_id: str, storage) -> Optional[tuple[str, dict]]:
    """Find the thread containing reply_to_id. Prunes stale threads (>48h) as a side effect.
    Returns (root_id, thread_dict) or None if not found or expired."""
    reply_id_int = _parse_message_id(reply_to_id)
    if reply_id_int is None:
        return None

    data = _load(storage)
    surviving = {}
    pruned = False
    result = None

    for root_id, thread in data["threads"].items():
        if _is_expired(thread, _PRUNE_TTL_HOURS):
            pruned = True
            continue
        surviving[root_id] = thread
        if result is None and reply_id_int in thread.get("all_message_ids", []):
            if not _is_expired(thread, _ACTIVE_TTL_HOURS):
                result = (root_id, thread)

    if pruned:
        data["threads"] = surviving
        _save(storage, data)

    return result


def append_thread_turn(
    root_id: Optional[str],
    user_text: str,
    bot_text: str,
    bot_message_id: int,
    storage,
) -> str:
    """Append a turn to an existing thread, or create a new general thread rooted at bot_message_id.
    Returns the root_id used."""
    data = _load(storage)

    if root_id and root_id in data["threads"]:
        thread = data["threads"][root_id]
        thread["turns"].append({
            "user": user_text,
            "bot": bot_text,
            "bot_message_id": bot_message_id,
        })
        thread["all_message_ids"].append(bot_message_id)
    else:
        root_id = str(bot_message_id)
        data["threads"][root_id] = {
            "thread_type": "general",
            "created_at": _now_utc().isoformat(),
            "context": {},
            "turns": [{"user": user_text, "bot": bot_text, "bot_message_id": bot_message_id}],
            "all_message_ids": [bot_message_id],
        }

    _save(storage, data)
    return root_id


def create_eod_thread(root_message_id: int, open_tasks: list[dict], storage) -> None:
    """Create an EOD thread entry when the nudge fires. Overwrites any prior entry for this ID."""
    data = _load(storage)
    data["threads"][str(root_message_id)] = {
        "thread_type": "eod",
        "created_at": _now_utc().isoformat(),
        "context": {
            "open_tasks_snapshot": [
                {"id": t["id"], "title": t["title"]} for t in open_tasks
            ]
        },
        "turns": [],
        "all_message_ids": [root_message_id],
    }
    _save(storage, data)


def build_enriched_query(thread: dict, user_text: str, session_date: str = "") -> str:
    """Build the context-enriched query string for Claude based on thread type and history."""
    thread_type = thread.get("thread_type", "general")
    turns = thread.get("turns", [])

    if thread_type == "eod":
        tasks = thread.get("context", {}).get("open_tasks_snapshot", [])
        task_lines = "\n".join(f"- {t['title']}" for t in tasks) if tasks else "- (none)"
        date_str = session_date or _now_utc().strftime("%Y-%m-%d")
        prior = ""
        if turns:
            prior_lines = []
            for t in turns:
                prior_lines.append(f"User: {t['user']}")
                prior_lines.append(f"You: {t['bot']}")
            prior = "Prior conversation:\n" + "\n".join(prior_lines) + "\n\n"
        return (
            f"[EOD CHECK-IN SESSION — {date_str}]\n"
            f"Open tasks at session start:\n{task_lines}\n\n"
            f"{prior}"
            f"Current message: {user_text}\n\n"
            f"Process this EOD update. Use tools to: complete tasks (syncs canvas automatically), "
            f"add people notes for any contacts mentioned, update project next-actions as needed. "
            f"Continue the conversation naturally. When the user indicates they're done, confirm "
            f"everything captured and wrap up."
        )

    # general thread
    if not turns:
        return user_text
    prior_lines = []
    for t in turns:
        prior_lines.append(f"User: {t['user']}")
        prior_lines.append(f"You: {t['bot']}")
    prior = "\n".join(prior_lines)
    return (
        f"[CONTINUING CONVERSATION]\n"
        f"Prior exchange:\n{prior}\n\n"
        f"Current message: {user_text}"
    )
```

- [ ] **Step 1.4: Run tests — confirm they all pass**

```bash
.venv/bin/pytest tests/test_telegram_threads.py -v
```

Expected: all 11 tests PASS

- [ ] **Step 1.5: Commit**

```bash
git add lib/telegram_threads.py tests/test_telegram_threads.py
git commit -m "feat: add telegram thread store for multi-turn conversation tracking"
```

---

## Task 2: `ask.py` — Thread Integration

**Files:**
- Modify: `ask.py:83-205`
- Create: `tests/test_ask_threads.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_ask_threads.py`:

```python
import json
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone, timedelta

import pytest

from lib.storage import LocalStorage


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(str(tmp_path))


@pytest.fixture
def config():
    return {"ai_model": "claude-sonnet-4-6", "slack_canvas": {}}


def _write_active_eod_thread(storage, root_id: int, extra_ids: list = None):
    data = {
        "threads": {
            str(root_id): {
                "thread_type": "eod",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "context": {"open_tasks_snapshot": [{"id": "t-1", "title": "Finish proposal"}]},
                "turns": [],
                "all_message_ids": [root_id] + (extra_ids or []),
            }
        }
    }
    storage.write_json("telegram_threads.json", data)


def test_thread_reply_enriches_query_and_appends_turn(storage, config):
    _write_active_eod_thread(storage, 100)

    with patch("ask.answer_query_with_tools", return_value="Bot reply") as mock_query, \
         patch("ask.send_message", return_value=101) as mock_send, \
         patch("ask.handle_score_command", return_value=None), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key",
                                   "TELEGRAM_BOT_TOKEN": "tok",
                                   "TELEGRAM_ALLOWED_CHAT_ID": "chat1"}):
        from ask import _main_inner
        _main_inner("I finished the proposal", "chat1", "tok", config, storage, reply_to_id="100")

    enriched = mock_query.call_args[1]["query"]
    assert "[EOD CHECK-IN SESSION" in enriched
    assert "Finish proposal" in enriched
    assert "I finished the proposal" in enriched

    threads = storage.read_json("telegram_threads.json")
    thread = threads["threads"]["100"]
    assert len(thread["turns"]) == 1
    assert thread["turns"][0]["user"] == "I finished the proposal"
    assert thread["turns"][0]["bot"] == "Bot reply"
    assert thread["turns"][0]["bot_message_id"] == 101
    assert 101 in thread["all_message_ids"]


def test_non_reply_creates_general_thread(storage, config):
    with patch("ask.answer_query_with_tools", return_value="Answer") as mock_query, \
         patch("ask.send_message", return_value=200), \
         patch("ask.handle_score_command", return_value=None), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key",
                                   "TELEGRAM_BOT_TOKEN": "tok",
                                   "TELEGRAM_ALLOWED_CHAT_ID": "chat1"}):
        from ask import _main_inner
        _main_inner("what's on my calendar?", "chat1", "tok", config, storage)

    threads = storage.read_json("telegram_threads.json")
    assert "200" in threads["threads"]
    thread = threads["threads"]["200"]
    assert thread["thread_type"] == "general"
    assert thread["turns"][0]["user"] == "what's on my calendar?"


def test_meeting_nudge_reply_takes_priority_over_thread(storage, config):
    _write_active_eod_thread(storage, 100)
    nudge_record = {
        "event_id": "evt1",
        "meeting_name": "Standup",
        "session_date": "2026-05-15",
        "attendees": [],
        "telegram_message_id": 100,
    }
    storage.write_json("pending_nudges.json", [nudge_record])

    with patch("ask.answer_query_with_tools", return_value="processed") as mock_q, \
         patch("ask.send_message", return_value=101), \
         patch("ask.append_session_notes"), \
         patch("ask.handle_score_command", return_value=None), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key",
                                   "TELEGRAM_BOT_TOKEN": "tok",
                                   "TELEGRAM_ALLOWED_CHAT_ID": "chat1"}):
        from ask import _main_inner
        _main_inner("meeting notes here", "chat1", "tok", config, storage, reply_to_id="100")

    enriched = mock_q.call_args[1]["query"]
    assert "[MEETING NUDGE REPLY]" in enriched
    assert "[EOD CHECK-IN SESSION" not in enriched


def test_unknown_reply_to_id_falls_through_to_normal_query(storage, config):
    with patch("ask.answer_query_with_tools", return_value="Answer"), \
         patch("ask.send_message", return_value=300), \
         patch("ask.handle_score_command", return_value=None), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key",
                                   "TELEGRAM_BOT_TOKEN": "tok",
                                   "TELEGRAM_ALLOWED_CHAT_ID": "chat1"}):
        from ask import _main_inner
        _main_inner("plain query", "chat1", "tok", config, storage, reply_to_id="999")

    threads = storage.read_json("telegram_threads.json")
    assert "300" in threads["threads"]
    assert threads["threads"]["300"]["thread_type"] == "general"
```

- [ ] **Step 2.2: Run tests — confirm they fail**

```bash
.venv/bin/pytest tests/test_ask_threads.py -v 2>&1 | head -40
```

Expected: failures because `ask.py` does not yet import or call thread functions.

- [ ] **Step 2.3: Modify `ask.py` — add imports and update `_main_inner`**

At the top of `ask.py`, the existing imports stay unchanged. The thread functions are imported inline inside `_main_inner` (consistent with the existing pattern in the file).

Replace the entire `_main_inner` function (lines 83–205) with:

```python
def _main_inner(query: str, chat_id: str, bot_token: str, config: dict, storage, reply_to_id: str = "") -> None:
    # Approve/reject pending code change — exact match only
    query_normalized = query.strip().lower()
    if query_normalized in ("approve", "reject") and os.path.exists(PENDING_CHANGE_PATH):
        _handle_pending_change(query_normalized, chat_id, bot_token)
        return

    # If this is a Telegram reply to a meeting nudge, route directly to meeting notes
    if reply_to_id:
        nudge = _resolve_nudge_reply(reply_to_id, storage)
        if nudge:
            memory_key = nudge.get("memory_file", "").removeprefix("data/") or None
            if not memory_key:
                safe = nudge["meeting_name"].lower().replace(" ", "_")[:40]
                memory_key = f"meeting_memory/{safe}.md"
            append_session_notes(storage, memory_key, nudge["session_date"], query)

            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                attendees = nudge.get("attendees", [])
                attendee_str = ", ".join(attendees) if attendees else "none listed"
                enriched_query = (
                    f"[MEETING NUDGE REPLY]\n"
                    f"Meeting: {nudge['meeting_name']}\n"
                    f"Date: {nudge['session_date']}\n"
                    f"Attendees (emails): {attendee_str}\n"
                    f"Meeting notes already saved to: {memory_key}\n\n"
                    f"Process these meeting notes. For each attendee, add a note to their people "
                    f"file (match by email in the people profiles). If an attendee has no existing "
                    f"profile, create one using the email prefix as their name. Extract any action "
                    f"items, todos, ideas, or next steps as captures.\n\n"
                    f"Notes:\n{query}"
                )
                try:
                    answer = answer_query_with_tools(
                        api_key=api_key,
                        model=config["ai_model"],
                        query=enriched_query,
                        config=config,
                        storage=storage,
                    )
                except Exception as e:
                    print(f"  WARNING: Claude call failed for nudge reply: {e}", file=sys.stderr)
                    answer = (
                        f"Notes saved for *{nudge['meeting_name']}*.\n"
                        f"📝 Meeting memory: `{memory_key}`\n"
                        f"⚠️ People file updates skipped — API error."
                    )
            else:
                answer = (
                    f"Notes saved for *{nudge['meeting_name']}*.\n"
                    f"📝 Meeting memory: `{memory_key}`"
                )

            if bot_token:
                send_message(bot_token, chat_id, answer)
            print(f"  Notes captured via reply for: {nudge['meeting_name']}")
            return

    # /brief score commands are handled locally — no Claude call, no API cost
    score_response = handle_score_command(query, storage=storage)
    if score_response is not None:
        if bot_token:
            send_message(bot_token, chat_id, score_response)
        return

    # /todo <text> — direct dispatch, no Claude call needed
    if query_normalized.startswith("/todo "):
        text = query[6:].strip()
        if not text:
            if bot_token:
                send_message(bot_token, chat_id, "Usage: /todo <task description>")
            return
        from processors.query_tools import _tool_add_capture
        _tool_add_capture("todo", text, storage, config)
        if bot_token:
            send_message(bot_token, chat_id, f"Done.\n  → task ledger: {text}\n  → Slack canvas: synced")
        return

    # /done <text> — direct dispatch, no Claude call needed
    if query_normalized.startswith("/done "):
        text = query[6:].strip()
        if not text:
            if bot_token:
                send_message(bot_token, chat_id, "Usage: /done <task description>")
            return
        from processors.query_tools import _tool_complete_task
        result = _tool_complete_task(text, storage, config)
        if bot_token:
            send_message(bot_token, chat_id, f"Done.\n  → {result}\n  → Slack canvas: synced")
        return

    # /reminder <text with time> — still uses Claude for time parsing, but forces set_reminder intent
    if query_normalized.startswith("/reminder "):
        text = query[10:].strip()
        if not text:
            if bot_token:
                send_message(bot_token, chat_id, "Usage: /reminder <message and time>")
            return
        query = f"[SLASH COMMAND: set_reminder — you MUST call the set_reminder tool] {text}"

    # Multi-turn thread continuation: if this is a reply to a tracked bot message, enrich with history
    user_text = query  # preserve original before possible enrichment
    thread_root_id = None
    if reply_to_id:
        from lib.telegram_threads import resolve_thread_reply, build_enriched_query
        thread_result = resolve_thread_reply(reply_to_id, storage)
        if thread_result:
            thread_root_id, active_thread = thread_result
            session_date = active_thread.get("created_at", "")[:10]
            query = build_enriched_query(active_thread, user_text, session_date)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        if bot_token:
            send_message(bot_token, chat_id, "Something went wrong — check Actions logs.")
        sys.exit(1)

    try:
        answer = answer_query_with_tools(
            api_key=api_key,
            model=config["ai_model"],
            query=query,
            config=config,
            storage=storage,
        )
    except Exception as e:
        print(f"Query error: {e}", file=sys.stderr)
        if bot_token:
            send_message(bot_token, chat_id, "Something went wrong — check Actions logs.")
        sys.exit(1)

    bot_message_id = send_message(bot_token, chat_id, answer) if bot_token else None
    if bot_message_id:
        from lib.telegram_threads import append_thread_turn
        append_thread_turn(thread_root_id, user_text, answer, bot_message_id, storage)
```

- [ ] **Step 2.4: Run all thread tests**

```bash
.venv/bin/pytest tests/test_ask_threads.py tests/test_telegram_threads.py -v
```

Expected: all tests PASS

- [ ] **Step 2.5: Run existing ask and query tests to confirm no regressions**

```bash
.venv/bin/pytest tests/test_query.py tests/test_query_tools.py tests/test_telegram.py -v
```

Expected: all PASS

- [ ] **Step 2.6: Commit**

```bash
git add ask.py tests/test_ask_threads.py
git commit -m "feat: integrate telegram thread tracking into ask.py"
```

---

## Task 3: `eod_nudge.py` — EOD Nudge Script

**Files:**
- Create: `eod_nudge.py`
- Create: `tests/test_eod_nudge.py`

- [ ] **Step 3.1: Write the failing tests**

Create `tests/test_eod_nudge.py`:

```python
from unittest.mock import patch, MagicMock

import pytest

from lib.storage import LocalStorage
from eod_nudge import _format_nudge_message, run


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(str(tmp_path))


def test_format_message_with_tasks():
    tasks = [
        {"id": "t-1", "title": "Finish proposal"},
        {"id": "t-2", "title": "Follow up Acme"},
    ]
    msg = _format_nudge_message(tasks)
    assert "EOD check-in" in msg
    assert "• Finish proposal" in msg
    assert "• Follow up Acme" in msg
    assert "Reply to this message to start" in msg


def test_format_message_no_tasks():
    msg = _format_nudge_message([])
    assert "No open tasks on the board" in msg
    assert "Reply to this message to start" in msg


def test_run_sends_message_and_creates_thread(storage):
    tasks = [{"id": "t-1", "title": "Finish proposal", "status": "open",
              "created_at": "2026-05-15", "due_date": None, "source": "telegram", "completed_at": None}]
    storage.write_json("tasks.json", {"tasks": tasks})

    with patch("eod_nudge.send_message", return_value=500) as mock_send, \
         patch("eod_nudge.build_storage", return_value=storage), \
         patch("eod_nudge.load_config", return_value={"data_dir": str(storage.base_dir)}), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_ALLOWED_CHAT_ID": "chat1"}):
        run()

    mock_send.assert_called_once()
    sent_text = mock_send.call_args[0][2]
    assert "Finish proposal" in sent_text

    threads = storage.read_json("telegram_threads.json")
    assert "500" in threads["threads"]
    thread = threads["threads"]["500"]
    assert thread["thread_type"] == "eod"
    snapshot = thread["context"]["open_tasks_snapshot"]
    assert snapshot[0]["title"] == "Finish proposal"


def test_run_skips_gracefully_when_no_token(storage, capsys):
    with patch("eod_nudge.build_storage", return_value=storage), \
         patch("eod_nudge.load_config", return_value={"data_dir": str(storage.base_dir)}), \
         patch.dict("os.environ", {}, clear=True):
        run()

    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert storage.read_json("telegram_threads.json") is None
```

- [ ] **Step 3.2: Run tests — confirm they fail**

```bash
.venv/bin/pytest tests/test_eod_nudge.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'eod_nudge'`

- [ ] **Step 3.3: Create `eod_nudge.py`**

```python
#!/usr/bin/env python3
"""EOD check-in nudge: sends a scheduled Telegram prompt with the open task list."""

import json
import os

from dotenv import load_dotenv

load_dotenv()

from lib.storage import build_storage
from lib.tasks import get_open_tasks
from lib.telegram import send_message
from lib.telegram_threads import create_eod_thread


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _format_nudge_message(open_tasks: list[dict]) -> str:
    if not open_tasks:
        return (
            "EOD check-in. No open tasks on the board — what did you get done today? "
            "Any pipeline moves or people updates?\nReply to this message to start."
        )
    task_lines = "\n".join(f"• {t['title']}" for t in open_tasks)
    return (
        f"EOD check-in. Here's what's still open:\n{task_lines}\n\n"
        f"What did you get done today? Any pipeline moves or people updates?\n"
        f"Reply to this message to start."
    )


def run() -> None:
    config = load_config()
    storage = build_storage(config)
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

    if not bot_token or not chat_id:
        print("WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_CHAT_ID not set — skipping EOD nudge.")
        return

    open_tasks = get_open_tasks(storage)
    message = _format_nudge_message(open_tasks)
    message_id = send_message(bot_token, chat_id, message)

    if message_id:
        create_eod_thread(message_id, open_tasks, storage)
        print(f"  EOD nudge sent (message_id={message_id}), thread created.")
    else:
        print("  WARNING: EOD nudge sent but no message_id returned — thread not created.")

    print("✅ EOD nudge run complete.")


if __name__ == "__main__":
    run()
```

- [ ] **Step 3.4: Run tests — confirm they pass**

```bash
.venv/bin/pytest tests/test_eod_nudge.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 3.5: Commit**

```bash
git add eod_nudge.py tests/test_eod_nudge.py
git commit -m "feat: add eod_nudge.py script"
```

---

## Task 4: GitHub Actions Workflow + `.gitignore`

**Files:**
- Create: `.github/workflows/eod.yml`
- Modify: `.gitignore`
- Modify: `.github/workflows/ask.yml`

- [ ] **Step 4.1: Add `telegram_threads.json` to `.gitignore` exceptions**

In `.gitignore`, find the block:
```
!data/tasks.json
```
Add immediately after:
```
!data/telegram_threads.json
```

The full block should now read:
```
# Runtime state — persisted to R2, not tracked in git
data/*
!data/people/
!data/people/**
!data/projects.md
!data/recurring.json
!data/meeting_index.json
!data/notion_updates_queue.json
!data/brief_prefs.md
!data/pending_change.json
!data/tasks.json
!data/telegram_threads.json
!data/memory/
data/memory/*
!data/memory/decisions.md
```

- [ ] **Step 4.2: Update `ask.yml` commit step**

In `.github/workflows/ask.yml`, find the line:
```
git add data/notion_updates_queue.json data/brief_prefs.md data/pending_change.json data/people/ data/projects.md data/tasks.json 2>/dev/null || true
```

Replace it with:
```
git add data/notion_updates_queue.json data/brief_prefs.md data/pending_change.json data/people/ data/projects.md data/tasks.json data/telegram_threads.json 2>/dev/null || true
```

- [ ] **Step 4.3: Create `.github/workflows/eod.yml`**

```yaml
name: EOD Nudge

on:
  schedule:
    # Mon–Thu 4PM CDT (UTC-5). Change to "0 22 * * 1-4" in November for CST (UTC-6).
    - cron: "0 21 * * 1-4"
    # Friday 2PM CDT (UTC-5). Change to "0 20 * * 5" in November for CST.
    - cron: "0 19 * * 5"
  workflow_dispatch:

jobs:
  eod-nudge:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    env:
      TZ: America/Chicago

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Configure git
        run: |
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git config user.name "github-actions[bot]"

      - name: Send EOD nudge
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ALLOWED_CHAT_ID: ${{ secrets.TELEGRAM_ALLOWED_CHAT_ID }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
        run: python eod_nudge.py

      - name: Commit thread state
        run: |
          git add data/telegram_threads.json 2>/dev/null || true
          git diff --staged --quiet || git commit -m "chore: eod nudge thread init [skip ci]"
          git push origin main || true
```

- [ ] **Step 4.4: Run the full test suite to confirm nothing is broken**

```bash
.venv/bin/pytest tests/ -v --ignore=tests/test_memory_retriever_integration.py --ignore=tests/test_vector_ingest_integration.py -q
```

Expected: all non-integration tests PASS

- [ ] **Step 4.5: Commit**

```bash
git add .github/workflows/eod.yml .github/workflows/ask.yml .gitignore
git commit -m "feat: add eod.yml workflow and wire telegram_threads.json into git tracking"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `data/telegram_threads.json` schema with `thread_type`, `created_at`, `context`, `turns`, `all_message_ids` — Task 1
- ✅ `resolve_thread_reply` with 24h active TTL and 48h prune TTL — Task 1
- ✅ `append_thread_turn` extends existing or creates general thread — Task 1
- ✅ `create_eod_thread` seeds EOD thread with tasks snapshot — Task 1
- ✅ `build_enriched_query` for EOD (with tasks, prior turns, routing instructions) and general — Task 1
- ✅ `ask.py` meeting nudge check runs before thread resolution — Task 2
- ✅ Thread resolution mutates query before `answer_query_with_tools` — Task 2
- ✅ `send_message` return value captured, `append_thread_turn` called after every main-path response — Task 2
- ✅ `eod_nudge.py` reads tasks, formats message, sends, creates thread — Task 3
- ✅ Empty task list fallback message — Task 3
- ✅ `eod.yml` cron Mon–Thu 21:00 UTC, Fri 19:00 UTC with CDT/CST notes — Task 4
- ✅ `data/telegram_threads.json` gitignore exception — Task 4
- ✅ `ask.yml` commit step updated — Task 4
- ✅ All required secrets already in repo (per spec) — no action needed

**Placeholder scan:** None found.

**Type consistency:**
- `resolve_thread_reply` returns `tuple[str, dict] | None` — used as `thread_root_id, active_thread = thread_result` in Task 2 ✅
- `append_thread_turn(root_id, user_text, bot_text, bot_message_id, storage)` — signature consistent across Task 1 definition, Task 2 call site, and Task 3 indirect usage ✅
- `create_eod_thread(message_id: int, open_tasks: list[dict], storage)` — consistent in Task 1 and Task 3 ✅
- `build_enriched_query(thread: dict, user_text: str, session_date: str)` — consistent in Task 1 and Task 2 ✅
- `_format_nudge_message(open_tasks: list[dict]) -> str` — consistent in Task 3 definition and test ✅
