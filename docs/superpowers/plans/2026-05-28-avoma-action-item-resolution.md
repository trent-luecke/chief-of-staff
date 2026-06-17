# Avoma Action Item Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After an Avoma call, action items are stored in a resolution store; the next pre-meeting prep for that person filters out resolved items so stale actions don't resurface; replies of "closed 1,2" or "closed all" to the post-call Telegram message mark items as resolved; the Notion update prompt includes action items for manual entry.

**Architecture:** A new `lib/resolved_actions.py` module owns the `data/state/resolved_actions.json` store. `avoma_per_call.py` saves a pending entry keyed by Telegram `message_id` and enriches the Notion update prompt with action items. `ask.py` handles "closed" replies against that pending store. `meeting_prep.py` loads resolved items for the matched contact and appends them to the external context so Claude knows not to re-surface them in the "Open:" bullet.

**Tech Stack:** Python 3.12+, pytest, `lib/storage.py` (LocalStorage), existing `ask.py` reply-dispatch pattern.

---

## File Map

| File | Change |
|------|--------|
| `lib/resolved_actions.py` | **Create** — load/save/query resolved actions store |
| `tests/test_resolved_actions.py` | **Create** — unit tests for the above |
| `scripts/avoma_per_call.py` | **Modify** — save pending actions, enrich Notion prompt, add action items section |
| `processors/meeting_prep.py` | **Modify** — `_load_resolved_for_tokens` helper + use in `build_external_context` + system prompt tweak |
| `ask.py` | **Modify** — "closed" reply handler after existing pending tasks block |

---

## Task 1: `lib/resolved_actions.py` — core store

**Files:**
- Create: `lib/resolved_actions.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_resolved_actions.py`:

```python
import json
import pytest
from datetime import date
from lib.storage import LocalStorage


def _storage(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_mark_resolved_writes_entry(tmp_path):
    from lib.resolved_actions import mark_resolved, load_all_resolved
    s = _storage(tmp_path)
    mark_resolved(s, "john-smith", "John Smith", ["Send pricing deck"], "Demo: John Smith")
    store = load_all_resolved(s)
    assert "john-smith" in store
    assert store["john-smith"]["resolved"][0]["text"] == "Send pricing deck"
    assert store["john-smith"]["resolved"][0]["resolved_date"] == date.today().isoformat()


def test_mark_resolved_deduplicates(tmp_path):
    from lib.resolved_actions import mark_resolved, load_all_resolved
    s = _storage(tmp_path)
    mark_resolved(s, "john-smith", "John Smith", ["Send pricing deck"], "Demo")
    mark_resolved(s, "john-smith", "John Smith", ["Send pricing deck"], "Follow-up")
    store = load_all_resolved(s)
    assert len(store["john-smith"]["resolved"]) == 1


def test_mark_resolved_multiple_items(tmp_path):
    from lib.resolved_actions import mark_resolved, load_all_resolved
    s = _storage(tmp_path)
    mark_resolved(s, "ryan-pace", "Ryan Pace", ["Item A", "Item B"], "Demo")
    store = load_all_resolved(s)
    texts = [r["text"] for r in store["ryan-pace"]["resolved"]]
    assert "Item A" in texts
    assert "Item B" in texts


def test_get_resolved_for_tokens_matches_slug(tmp_path):
    from lib.resolved_actions import mark_resolved, get_resolved_for_tokens
    s = _storage(tmp_path)
    mark_resolved(s, "ryan-pace", "Ryan Pace", ["Send contract"], "Demo")
    results = get_resolved_for_tokens(s, ["ryan", "pace"])
    assert len(results) == 1
    assert results[0]["text"] == "Send contract"


def test_get_resolved_for_tokens_no_match(tmp_path):
    from lib.resolved_actions import mark_resolved, get_resolved_for_tokens
    s = _storage(tmp_path)
    mark_resolved(s, "ryan-pace", "Ryan Pace", ["Send contract"], "Demo")
    results = get_resolved_for_tokens(s, ["john", "smith"])
    assert results == []


def test_get_resolved_for_tokens_empty_store(tmp_path):
    from lib.resolved_actions import get_resolved_for_tokens
    s = _storage(tmp_path)
    assert get_resolved_for_tokens(s, ["anyone"]) == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_resolved_actions.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError` or similar — `lib/resolved_actions` does not exist yet.

- [ ] **Step 3: Implement `lib/resolved_actions.py`**

```python
"""Resolved action items store — tracks which call action items Trent has marked done."""

from datetime import date

_STORE_KEY = "state/resolved_actions.json"


def load_all_resolved(storage) -> dict:
    """Returns full store: {person_slug: {name, resolved: [{text, resolved_date, call_title}]}}"""
    return storage.read_json(_STORE_KEY, default={})


def mark_resolved(
    storage,
    person_id: str,
    person_name: str,
    items: list[str],
    call_title: str,
) -> None:
    """Add items to the resolved list for person_id. Deduplicates by text."""
    store = load_all_resolved(storage)
    today = date.today().isoformat()
    entry = store.setdefault(person_id, {"name": person_name, "resolved": []})
    existing_texts = {r["text"] for r in entry["resolved"]}
    for item in items:
        if item not in existing_texts:
            entry["resolved"].append({
                "text": item,
                "resolved_date": today,
                "call_title": call_title,
            })
            existing_texts.add(item)
    storage.write_json(_STORE_KEY, store)


def get_resolved_for_tokens(storage, tokens: list[str]) -> list[dict]:
    """Return all resolved items for any person whose registry slug contains any token."""
    store = load_all_resolved(storage)
    results = []
    for slug, entry in store.items():
        if any(t in slug for t in tokens):
            results.extend(entry.get("resolved", []))
    return results
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_resolved_actions.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/resolved_actions.py tests/test_resolved_actions.py
git commit -m "feat: add resolved_actions store for tracking closed call action items"
```

---

## Task 2: `processors/meeting_prep.py` — filter resolved items from context

**Files:**
- Modify: `processors/meeting_prep.py`
- Test: `tests/test_meeting_prep.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_meeting_prep.py`:

```python
import json
from pathlib import Path


def _write_resolved(tmp_path, data: dict):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "resolved_actions.json").write_text(json.dumps(data))


def test_load_resolved_for_tokens_matches(tmp_path):
    from processors.meeting_prep import _load_resolved_for_tokens
    _write_resolved(tmp_path, {
        "ryan-pace": {"name": "Ryan Pace", "resolved": [{"text": "Send deck", "resolved_date": "2026-05-28", "call_title": "Demo"}]}
    })
    resolved_path = tmp_path / "state" / "resolved_actions.json"
    results = _load_resolved_for_tokens(resolved_path, ["ryan", "pace"])
    assert len(results) == 1
    assert results[0]["text"] == "Send deck"


def test_load_resolved_for_tokens_missing_file(tmp_path):
    from processors.meeting_prep import _load_resolved_for_tokens
    results = _load_resolved_for_tokens(tmp_path / "state" / "resolved_actions.json", ["anyone"])
    assert results == []


def test_load_resolved_for_tokens_no_match(tmp_path):
    from processors.meeting_prep import _load_resolved_for_tokens
    _write_resolved(tmp_path, {
        "ryan-pace": {"name": "Ryan Pace", "resolved": [{"text": "Send deck", "resolved_date": "2026-05-28", "call_title": "Demo"}]}
    })
    resolved_path = tmp_path / "state" / "resolved_actions.json"
    results = _load_resolved_for_tokens(resolved_path, ["john", "smith"])
    assert results == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_meeting_prep.py::test_load_resolved_for_tokens_matches tests/test_meeting_prep.py::test_load_resolved_for_tokens_missing_file tests/test_meeting_prep.py::test_load_resolved_for_tokens_no_match -v 2>&1 | tail -15
```

Expected: `ImportError` — `_load_resolved_for_tokens` not defined yet.

- [ ] **Step 3: Add `_load_resolved_for_tokens` helper to `processors/meeting_prep.py`**

Add this function after `_find_observations` (around line 123):

```python
def _load_resolved_for_tokens(resolved_path, tokens: list[str]) -> list[dict]:
    try:
        import json as _json
        from pathlib import Path as _Path
        store = _json.loads(_Path(resolved_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return []
    results = []
    for slug, entry in store.items():
        if any(t in slug for t in tokens):
            results.extend(entry.get("resolved", []))
    return results
```

- [ ] **Step 4: Use it in `build_external_context`**

In `build_external_context`, after the observations block (around line 161), add:

```python
    resolved_path = config.get("resolved_actions_path", "data/state/resolved_actions.json")
    resolved = _load_resolved_for_tokens(resolved_path, tokens)
    if resolved:
        lines = [f"• {r['text']} (resolved {r['resolved_date']})" for r in resolved]
        parts.append("## Resolved Action Items (do not surface as open)\n" + "\n".join(lines))
```

- [ ] **Step 5: Update the external meeting system prompt to be explicit**

In `_SYSTEM_PROMPTS["external"]`, change the Open bullet line from:

```python
"• Open: [any unresolved item or thing they mentioned previously]\n"
```

to:

```python
"• Open: [any unresolved item — skip anything listed under Resolved Action Items]\n"
```

- [ ] **Step 6: Run tests**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_meeting_prep.py -v 2>&1 | tail -20
```

Expected: all tests pass, including the 3 new ones.

- [ ] **Step 7: Commit**

```bash
git add processors/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat: filter resolved action items from external meeting prep context"
```

---

## Task 3: `scripts/avoma_per_call.py` — pending actions store + enriched Notion prompt + message section

**Files:**
- Modify: `scripts/avoma_per_call.py`

No new tests for this task — the functions are thin wrappers around storage and string building. Test coverage comes from integration.

- [ ] **Step 1: Add `_PENDING_ACTIONS_KEY` constant and `_save_pending_actions` function**

Add after the `_PENDING_TASKS_KEY` constant (around line 22):

```python
_PENDING_ACTIONS_KEY = "state/pending_avoma_actions.json"
```

Add after the `_save_pending_tasks` function (around line 408):

```python
def _save_pending_actions(storage, message_id: int, t, resolved_people: list) -> None:
    """Store all action items keyed by message_id so the reply handler can resolve them."""
    if not message_id or not t.action_items:
        return
    from datetime import date as _date
    pending = storage.read_json(_PENDING_ACTIONS_KEY, default={})
    # Purge entries older than 14 days
    today = _date.today().isoformat()
    cutoff = _date.fromisoformat(today).toordinal() - 14
    pending = {
        k: v for k, v in pending.items()
        if _date.fromisoformat(v.get("created", today)).toordinal() >= cutoff
    }
    external = [r for r in resolved_people if not r["is_internal"] and r["person_id"]]
    pending[str(message_id)] = {
        "call_title": t.title,
        "call_date": t.start_at[:10] if t.start_at else today,
        "participants": [{"person_id": r["person_id"], "name": r["name"]} for r in external],
        "action_items": t.action_items[:8],
        "created": today,
    }
    storage.write_json(_PENDING_ACTIONS_KEY, pending)
```

- [ ] **Step 2: Enrich `_build_notion_prompt` with action items**

In `_build_notion_prompt`, in the `else` branch (pipeline update), change the return to include action items. Replace the final return statement in the `else` block:

```python
        action_items_str = "; ".join(t.action_items[:6]) if t.action_items else "none"
        return (
            "📤 Notion Pipeline Update — paste into Claude Desktop\n"
            f"Update the pipeline record for {lead_name}. "
            f"Call date: {call_date}. Type: {call_label}. Owner: {owner}. "
            f"Inferred status: {status}. "
            f"Summary: {t.summary} "
            f"Buying signals: {signals}. "
            f"Objections: {objections}. "
            f"Action items: {action_items_str}."
        )
```

Also update the onboarding branch return to include action items:

```python
        action_items_str = "; ".join(t.action_items[:6]) if t.action_items else "none"
        return (
            "📤 Notion Onboarding Update — paste into Claude Desktop\n"
            f"Update the onboarding tracker for {lead_name}. "
            f"Call date: {call_date}. "
            f"Summary: {t.summary} "
            f"Completed: {completed}. "
            f"Next steps: {next_steps}. "
            f"Action items: {action_items_str}."
        )
```

- [ ] **Step 3: Add "All Action Items" section to `_build_message`**

In `_build_message`, after the `proposed_tasks` block (around line 319) and before the `new_stubs` block, add:

```python
    if t.action_items:
        lines += ["", "✅ All Action Items — reply 'closed 1,2' or 'closed all' once done"]
        for i, item in enumerate(t.action_items[:8], 1):
            lines.append(f"  {i}. {item}")
```

- [ ] **Step 4: Wire `_save_pending_actions` into `process_transcript`**

In `process_transcript`, after the existing `_save_pending_tasks` block (around line 452), add:

```python
    if message_id and t.action_items:
        try:
            _save_pending_actions(storage, message_id, t, resolved_people)
        except Exception as e:
            print(f"  WARNING: pending actions write failed: {e}", file=sys.stderr)
```

- [ ] **Step 5: Commit**

```bash
git add scripts/avoma_per_call.py
git commit -m "feat: save pending actions per call and enrich Notion update prompt with action items"
```

---

## Task 4: `ask.py` — "closed" reply handler

**Files:**
- Modify: `ask.py`

- [ ] **Step 1: Add the handler block**

In `_main_inner`, after the existing pending tasks block (after line 181, before the people-resolution block), add:

```python
    # Handle "closed N,M" or "closed all" replies for Avoma action item resolution
    if reply_to_id:
        pending_actions = storage.read_json("state/pending_avoma_actions.json", default={})
        if str(reply_to_id) in pending_actions:
            query_lower = query.strip().lower()
            if query_lower.startswith("closed"):
                from lib.resolved_actions import mark_resolved
                entry = pending_actions[str(reply_to_id)]
                action_items = entry.get("action_items", [])
                arg = query_lower[len("closed"):].strip()
                if not arg or arg == "all":
                    to_resolve = action_items
                elif re.match(r"^[\d,\s]+$", arg):
                    indices = [
                        int(n.strip()) - 1
                        for n in re.split(r"[,\s]+", arg)
                        if n.strip().isdigit()
                    ]
                    to_resolve = [action_items[i] for i in indices if 0 <= i < len(action_items)]
                else:
                    to_resolve = action_items

                for participant in entry.get("participants", []):
                    person_id = participant.get("person_id")
                    person_name = participant.get("name", "")
                    if person_id:
                        try:
                            mark_resolved(storage, person_id, person_name, to_resolve, entry["call_title"])
                        except Exception as e:
                            print(f"  WARNING: mark_resolved failed for {person_id}: {e}", file=sys.stderr)

                if to_resolve:
                    items_str = "\n".join(f"  ✓ {item}" for item in to_resolve)
                    reply_msg = f"Marked resolved ({len(to_resolve)}):\n{items_str}"
                else:
                    reply_msg = "No matching items found."

                if bot_token:
                    send_message(bot_token, chat_id, reply_msg)
                print(f"  Action items closed: {len(to_resolve)}")
                return
```

- [ ] **Step 2: Smoke-test the dispatch logic manually**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -c "
import re
cases = ['closed all', 'closed 1,2', 'closed 1 3', 'closed', 'closed 2']
for q in cases:
    q_lower = q.strip().lower()
    arg = q_lower[len('closed'):].strip()
    items = ['A', 'B', 'C', 'D']
    if not arg or arg == 'all':
        result = items
    elif re.match(r'^[\d,\s]+$', arg):
        indices = [int(n.strip())-1 for n in re.split(r'[,\s]+', arg) if n.strip().isdigit()]
        result = [items[i] for i in indices if 0 <= i < len(items)]
    else:
        result = items
    print(f'{q!r:20} -> {result}')
"
```

Expected output:
```
'closed all'         -> ['A', 'B', 'C', 'D']
'closed 1,2'         -> ['A', 'B']
'closed 1 3'         -> ['A', 'C']
'closed'             -> ['A', 'B', 'C', 'D']
'closed 2'           -> ['B']
```

- [ ] **Step 3: Run full test suite to check for regressions**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/ -v --ignore=tests/test_memory_retriever_integration.py --ignore=tests/test_vector_ingest_integration.py -q 2>&1 | tail -20
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add ask.py
git commit -m "feat: handle 'closed N,M' replies to Avoma post-call messages for action item resolution"
```

---

## Self-Review

**Spec coverage:**
- [x] Action items written to pending store per call (`_save_pending_actions`)
- [x] Notion update prompt enriched with action items (`_build_notion_prompt` both branches)
- [x] "All Action Items" section in post-call Telegram message (`_build_message`)
- [x] "closed" reply handler marks items resolved (`ask.py`)
- [x] Meeting prep filters resolved items from context (`build_external_context`)
- [x] System prompt updated to skip resolved items ("Open:" bullet)
- [x] 14-day TTL on pending actions store (auto-purge in `_save_pending_actions`)

**Known UX note:** The Telegram message now has two numbered lists — "Proposed Action Items" (task ledger) and "All Action Items" (resolution tracking) with independent numbering. This is intentionally left for a UX review pass — the user confirmed they want to review the reply interface after the infrastructure is in place.

**Placeholder scan:** None found.

**Type consistency:** `mark_resolved` signature in `lib/resolved_actions.py` matches usage in `ask.py`. `get_resolved_for_tokens` takes `storage` in the lib but `_load_resolved_for_tokens` in `meeting_prep.py` takes a `Path` directly — this is intentional since `meeting_prep.py` does not have a storage object.
