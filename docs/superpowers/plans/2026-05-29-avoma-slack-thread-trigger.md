# Avoma Slack Thread Trigger (Two-Phase) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 30-minute cron Avoma trigger with a Slack Events API push trigger — Trent replies in the Avoma recording thread → Phase 1 runs once (writes observation, posts action items + Notion paste block to thread) → further replies in that thread are Phase 2 conversation (Q&A or gate-confirmed corrections).

**Architecture:** A new Cloudflare Worker (`avoma-slack-bridge.js`) receives Slack Events API posts, verifies Slack signatures, drops bot/system events and non-thread messages, then dispatches to a new GitHub Actions workflow via `workflow_dispatch`. The workflow runs `scripts/avoma_slack_processor.py`, which reads `state/avoma_thread_state.json` (R2 storage) to route Phase 1 vs Phase 2. Phase 1: find Avoma transcript by UUID (extracted from root Slack post) or title-match fallback → write observation → post output to thread → mark processed. Phase 2: Claude conversation handler with tools for Q&A and correction proposals; confirmed corrections write to observations.jsonl (append-only, correction type) or mutate people files in place.

**Tech Stack:** Python 3.11+, pytest, `slack_sdk` (WebClient), `anthropic`, `lib/storage.py` (R2 + Local), Cloudflare Workers (JS + Web Crypto API), GitHub Actions `workflow_dispatch`.

---

## File Map

| File | Change |
|------|--------|
| `lib/slack_post.py` | **Create** — `post_to_thread` + `get_thread_root_text` |
| `processors/avoma_thread_state.py` | **Create** — once-per-thread guard, phase state, pending correction |
| `collectors/avoma.py` | **Modify** — add `extract_avoma_uuid_from_text`, `fetch_meeting_by_uuid` |
| `processors/avoma_phase1.py` | **Create** — find transcript, write obs, post output, set state |
| `processors/avoma_phase2.py` | **Create** — Claude Q&A + correction proposal/application |
| `scripts/avoma_slack_processor.py` | **Create** — thin env dispatcher (Phase 1 or Phase 2) |
| `cloudflare/avoma-slack-bridge.js` | **Create** — Slack Events API Worker |
| `cloudflare/avoma-wrangler.toml` | **Create** — Wrangler config for new Worker |
| `.github/workflows/avoma_slack_trigger.yml` | **Create** — GH Actions workflow |
| `config.json` | **Modify** — add `avoma.slack_channel_id` |
| `.github/workflows/avoma_per_call.yml` | **Modify** — remove `schedule` trigger, keep `workflow_dispatch` only |
| `tests/test_slack_post.py` | **Create** |
| `tests/test_avoma_thread_state.py` | **Create** |
| `tests/test_avoma_collector_additions.py` | **Create** |
| `tests/test_avoma_phase1.py` | **Create** |
| `tests/test_avoma_phase2.py` | **Create** |

---

## Task 1: `lib/slack_post.py` — Slack thread utilities

**Files:**
- Create: `lib/slack_post.py`
- Create: `tests/test_slack_post.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_slack_post.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from slack_sdk.errors import SlackApiError


def _make_post_client(ts="1234.5678"):
    client = MagicMock()
    resp = MagicMock()
    resp.data = {"ok": True, "ts": ts}
    client.chat_postMessage.return_value = resp
    return client


def _make_replies_client(text="Root message text"):
    client = MagicMock()
    resp = MagicMock()
    resp.data = {"messages": [{"text": text}]}
    client.conversations_replies.return_value = resp
    return client


def test_post_to_thread_returns_ts():
    from lib.slack_post import post_to_thread
    with patch("lib.slack_post.WebClient", return_value=_make_post_client("ts.999")):
        result = post_to_thread("tok", "C123", "t.123", "hello")
    assert result == "ts.999"


def test_post_to_thread_returns_none_on_slack_error():
    from lib.slack_post import post_to_thread
    client = MagicMock()
    client.chat_postMessage.side_effect = SlackApiError("fail", {"error": "not_in_channel"})
    with patch("lib.slack_post.WebClient", return_value=client):
        result = post_to_thread("tok", "C123", "t.123", "hello")
    assert result is None


def test_get_thread_root_text_returns_first_message():
    from lib.slack_post import get_thread_root_text
    with patch("lib.slack_post.WebClient", return_value=_make_replies_client("Avoma meeting text")):
        text = get_thread_root_text("tok", "C123", "t.123")
    assert text == "Avoma meeting text"


def test_get_thread_root_text_returns_empty_on_error():
    from lib.slack_post import get_thread_root_text
    client = MagicMock()
    client.conversations_replies.side_effect = SlackApiError("fail", {"error": "channel_not_found"})
    with patch("lib.slack_post.WebClient", return_value=client):
        text = get_thread_root_text("tok", "C123", "t.123")
    assert text == ""


def test_get_thread_root_text_returns_empty_on_no_messages():
    from lib.slack_post import get_thread_root_text
    client = MagicMock()
    resp = MagicMock()
    resp.data = {"messages": []}
    client.conversations_replies.return_value = resp
    with patch("lib.slack_post.WebClient", return_value=client):
        assert get_thread_root_text("tok", "C123", "t.123") == ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_slack_post.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'lib.slack_post'`

- [ ] **Step 3: Implement `lib/slack_post.py`**

```python
"""Slack thread utilities — post messages and fetch thread roots."""

from __future__ import annotations
import sys
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def post_to_thread(bot_token: str, channel_id: str, thread_ts: str, text: str) -> str | None:
    """Post a message to a Slack thread. Returns the message ts, or None on failure."""
    client = WebClient(token=bot_token)
    try:
        resp = client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)
        return resp.data.get("ts")
    except SlackApiError as e:
        print(f"WARNING: Slack post failed: {e.response['error']}", file=sys.stderr)
        return None


def get_thread_root_text(bot_token: str, channel_id: str, thread_ts: str) -> str:
    """Return the text of the root message of a Slack thread, or '' on failure."""
    client = WebClient(token=bot_token)
    try:
        resp = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=1)
        messages = resp.data.get("messages", [])
        return messages[0].get("text", "") if messages else ""
    except SlackApiError:
        return ""
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_slack_post.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/slack_post.py tests/test_slack_post.py
git commit -m "feat: add slack_post utility for thread posting and root message fetch"
```

---

## Task 2: `processors/avoma_thread_state.py` — once-per-thread guard and Phase 2 state

**Files:**
- Create: `processors/avoma_thread_state.py`
- Create: `tests/test_avoma_thread_state.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_avoma_thread_state.py`:

```python
import pytest
from lib.storage import LocalStorage


def _s(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return s


def test_is_processed_false_for_new_thread(tmp_path):
    from processors.avoma_thread_state import is_processed
    assert is_processed(_s(tmp_path), "1234.5678") is False


def test_set_phase1_complete_marks_processed(tmp_path):
    from processors.avoma_thread_state import is_processed, set_phase1_complete
    s = _s(tmp_path)
    set_phase1_complete(s, "1234.5678", "uuid-abc", "1234.9999", "output text", {"uuid": "uuid-abc"})
    assert is_processed(s, "1234.5678") is True


def test_get_thread_record_returns_correct_fields(tmp_path):
    from processors.avoma_thread_state import set_phase1_complete, get_thread_record
    s = _s(tmp_path)
    set_phase1_complete(s, "1234.5678", "uuid-abc", "1234.9999", "output text", {"uuid": "uuid-abc"})
    rec = get_thread_record(s, "1234.5678")
    assert rec["phase"] == 2
    assert rec["avoma_uuid"] == "uuid-abc"
    assert rec["output_ts"] == "1234.9999"
    assert rec["phase1_output"] == "output text"
    assert rec["pending_correction"] is None
    assert "processed_at" in rec


def test_get_thread_record_returns_none_for_unknown(tmp_path):
    from processors.avoma_thread_state import get_thread_record
    assert get_thread_record(_s(tmp_path), "no-such-thread") is None


def test_set_pending_correction_stores_data(tmp_path):
    from processors.avoma_thread_state import set_phase1_complete, set_pending_correction, get_thread_record
    s = _s(tmp_path)
    set_phase1_complete(s, "1234.5678", None, None, "", {})
    correction = {"description": "fix name", "writes": [], "confirmation_prompt": "Reply yes", "notion_payload": None}
    set_pending_correction(s, "1234.5678", correction)
    rec = get_thread_record(s, "1234.5678")
    assert rec["pending_correction"]["description"] == "fix name"


def test_clear_pending_correction_sets_none(tmp_path):
    from processors.avoma_thread_state import set_phase1_complete, set_pending_correction, clear_pending_correction, get_thread_record
    s = _s(tmp_path)
    set_phase1_complete(s, "1234.5678", None, None, "", {})
    set_pending_correction(s, "1234.5678", {"description": "x", "writes": [], "confirmation_prompt": "y", "notion_payload": None})
    clear_pending_correction(s, "1234.5678")
    assert get_thread_record(s, "1234.5678")["pending_correction"] is None


def test_set_pending_correction_noop_for_unknown_thread(tmp_path):
    from processors.avoma_thread_state import set_pending_correction
    # must not raise
    set_pending_correction(_s(tmp_path), "no-such", {"description": "x", "writes": [], "confirmation_prompt": "y", "notion_payload": None})


def test_multiple_threads_tracked_independently(tmp_path):
    from processors.avoma_thread_state import set_phase1_complete, is_processed
    s = _s(tmp_path)
    set_phase1_complete(s, "thread-A", "uuid-1", None, "", {})
    assert is_processed(s, "thread-A") is True
    assert is_processed(s, "thread-B") is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_avoma_thread_state.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'processors.avoma_thread_state'`

- [ ] **Step 3: Implement `processors/avoma_thread_state.py`**

```python
"""Thread state store for Avoma Slack processing.

Tracks which Slack thread_ts values have completed Phase 1 and any
pending Phase 2 correction awaiting Trent's confirmation.

State schema per thread_ts key:
{
  "phase": 2,
  "avoma_uuid": str | null,
  "processed_at": "2026-06-02T10:00:00+00:00",
  "output_ts": str | null,
  "phase1_output": str,
  "transcript_json": dict,
  "pending_correction": null | {
    "description": str,
    "writes": [{"type": str, "target": str, "value": str}],
    "notion_payload": str | null,
    "confirmation_prompt": str,
  }
}
"""

from __future__ import annotations
from datetime import datetime, timezone

_STATE_KEY = "state/avoma_thread_state.json"


def _load(storage) -> dict:
    return storage.read_json(_STATE_KEY, default={})


def _save(storage, state: dict) -> None:
    storage.write_json(_STATE_KEY, state)


def is_processed(storage, thread_ts: str) -> bool:
    return thread_ts in _load(storage)


def get_thread_record(storage, thread_ts: str) -> dict | None:
    return _load(storage).get(thread_ts)


def set_phase1_complete(
    storage,
    thread_ts: str,
    avoma_uuid: str | None,
    output_ts: str | None,
    phase1_output: str,
    transcript_json: dict,
) -> None:
    state = _load(storage)
    state[thread_ts] = {
        "phase": 2,
        "avoma_uuid": avoma_uuid,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "output_ts": output_ts,
        "phase1_output": phase1_output,
        "transcript_json": transcript_json,
        "pending_correction": None,
    }
    _save(storage, state)


def set_pending_correction(storage, thread_ts: str, correction: dict) -> None:
    state = _load(storage)
    if thread_ts not in state:
        return
    state[thread_ts]["pending_correction"] = correction
    _save(storage, state)


def clear_pending_correction(storage, thread_ts: str) -> None:
    state = _load(storage)
    if thread_ts not in state:
        return
    state[thread_ts]["pending_correction"] = None
    _save(storage, state)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_avoma_thread_state.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/avoma_thread_state.py tests/test_avoma_thread_state.py
git commit -m "feat: add avoma_thread_state module for once-per-thread guard and Phase 2 state"
```

---

## Task 3: `collectors/avoma.py` additions — UUID extraction and single-meeting fetch

**Files:**
- Modify: `collectors/avoma.py`
- Create: `tests/test_avoma_collector_additions.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_avoma_collector_additions.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_extract_uuid_from_url():
    from collectors.avoma import extract_avoma_uuid_from_text
    text = "New recording: https://my.avoma.com/meetings/3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    result = extract_avoma_uuid_from_text(text)
    assert result == "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


def test_extract_uuid_case_insensitive():
    from collectors.avoma import extract_avoma_uuid_from_text
    text = "UUID: 3F2504E0-4F89-11D3-9A0C-0305E82C3301"
    result = extract_avoma_uuid_from_text(text)
    assert result == "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


def test_extract_uuid_returns_none_when_absent():
    from collectors.avoma import extract_avoma_uuid_from_text
    assert extract_avoma_uuid_from_text("No UUID here") is None
    assert extract_avoma_uuid_from_text("") is None


def _mock_meeting_response(uuid="test-uuid-1234", transcript_ready=True, title="TeamBuildr OS Demo - Acme"):
    return {
        "uuid": uuid,
        "subject": title,
        "start_at": "2026-06-02T14:00:00Z",
        "transcript_ready": transcript_ready,
        "attendees": [
            {"name": "John Smith", "email": "john@acme.com"},
            {"name": "Trent Luecke", "email": "trent@teambuildr.com"},
        ],
    }


def test_fetch_meeting_by_uuid_returns_transcript():
    from collectors.avoma import fetch_meeting_by_uuid

    mock_meeting = _mock_meeting_response()
    mock_analysis = {
        "os_interested": True,
        "call_type": "demo",
        "summary": "Good demo call.",
        "features_covered": ["scheduling"],
        "gaps": [],
        "objections": [],
        "buying_signals": ["asked about pricing"],
        "competitors": [],
        "onboarding_completed": [],
        "onboarding_next_steps": [],
        "action_items": ["Send pricing deck"],
    }

    with patch("collectors.avoma.requests.get") as mock_get, \
         patch("collectors.avoma._fetch_transcript", return_value=([], [{"speaker_id": "1", "transcript": "Hi there"}])), \
         patch("collectors.avoma._analyze_with_claude", return_value=mock_analysis):

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_meeting
        mock_get.return_value = mock_resp

        transcript = fetch_meeting_by_uuid("avoma-key", "anthropic-key", "claude-sonnet-4-6", "test-uuid-1234")

    assert transcript is not None
    assert transcript.uuid == "test-uuid-1234"
    assert transcript.title == "TeamBuildr OS Demo - Acme"
    assert transcript.os_interested is True
    assert transcript.action_items == ["Send pricing deck"]
    assert "John Smith" in transcript.participants


def test_fetch_meeting_by_uuid_returns_none_when_not_ready():
    from collectors.avoma import fetch_meeting_by_uuid

    with patch("collectors.avoma.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _mock_meeting_response(transcript_ready=False)
        mock_get.return_value = mock_resp

        result = fetch_meeting_by_uuid("avoma-key", "anthropic-key", "claude-sonnet-4-6", "test-uuid")

    assert result is None


def test_fetch_meeting_by_uuid_returns_none_on_api_error():
    from collectors.avoma import fetch_meeting_by_uuid
    import requests

    with patch("collectors.avoma.requests.get") as mock_get:
        mock_get.side_effect = requests.RequestException("network error")
        result = fetch_meeting_by_uuid("avoma-key", "anthropic-key", "claude-sonnet-4-6", "test-uuid")

    assert result is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_avoma_collector_additions.py -v 2>&1 | tail -15
```

Expected: `ImportError` — `extract_avoma_uuid_from_text` and `fetch_meeting_by_uuid` not defined.

- [ ] **Step 3: Add `extract_avoma_uuid_from_text` to `collectors/avoma.py`**

Add after the `_UUID_RE` pattern near the top of the file (after existing imports, before `_BASE_URL`):

```python
import re as _re

_UUID_RE = _re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    _re.IGNORECASE,
)


def extract_avoma_uuid_from_text(text: str) -> str | None:
    """Return the first UUID found in text (lowercase), or None."""
    m = _UUID_RE.search(text or "")
    return m.group(0).lower() if m else None
```

- [ ] **Step 4: Add a `context_note` parameter to `_analyze_with_claude` in `collectors/avoma.py`**

Modify the existing `_analyze_with_claude` function signature and user message construction:

```python
def _analyze_with_claude(
    anthropic_api_key: str,
    model: str,
    title: str,
    formatted_transcript: str,
    context_note: str = "",
) -> dict | None:
```

Inside that function, change the user message to:

```python
        messages=[{
            "role": "user",
            "content": (
                f"Meeting title: {title}\n\nTranscript:\n{formatted_transcript}"
                + (f"\n\nNote from rep: {context_note}" if context_note else "")
            ),
        }],
```

- [ ] **Step 5: Add `fetch_meeting_by_uuid` to `collectors/avoma.py`**

Add at the end of `collectors/avoma.py` (after `fetch_recent_meetings`):

```python
def fetch_meeting_by_uuid(
    api_key: str,
    anthropic_api_key: str,
    model: str,
    meeting_uuid: str,
    context_note: str = "",
) -> "AvomaTranscript | None":
    """Fetch and analyze a single Avoma meeting by UUID. Returns None if not found or transcript not ready."""
    try:
        m = _get(api_key, f"/v1/meetings/{meeting_uuid}")
    except Exception:
        return None

    if not m.get("transcript_ready"):
        return None

    uuid = m.get("uuid", meeting_uuid)
    attendees = m.get("attendees", [])
    participants = [
        a.get("name") or a.get("email", "")
        for a in attendees
        if a.get("name") or a.get("email")
    ]

    speakers, utterances = _fetch_transcript(api_key, uuid)
    if not utterances:
        return None

    formatted = _format_transcript(speakers, utterances)
    title = m.get("subject") or "Untitled Meeting"

    result = _analyze_with_claude(anthropic_api_key, model, title, formatted, context_note=context_note)
    if not result:
        return None

    return AvomaTranscript(
        uuid=uuid,
        title=title,
        start_at=m.get("start_at", ""),
        participants=participants,
        call_type=result.get("call_type", "other"),
        os_interested=bool(result.get("os_interested")),
        summary=result.get("summary", ""),
        features_covered=result.get("features_covered", []),
        gaps=result.get("gaps", []),
        objections=result.get("objections", []),
        buying_signals=result.get("buying_signals", []),
        competitors=result.get("competitors", []),
        onboarding_completed=result.get("onboarding_completed", []),
        onboarding_next_steps=result.get("onboarding_next_steps", []),
        action_items=result.get("action_items", []),
    )
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_avoma_collector_additions.py -v
```

Expected: 6 tests pass.

- [ ] **Step 7: Confirm no regressions in existing Avoma tests**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/ -k "avoma" -v 2>&1 | tail -15
```

Expected: all Avoma-related tests pass.

- [ ] **Step 8: Commit**

```bash
git add collectors/avoma.py tests/test_avoma_collector_additions.py
git commit -m "feat: add extract_avoma_uuid_from_text, fetch_meeting_by_uuid, and context_note support to avoma collector"
```

---

## Task 4: `processors/avoma_phase1.py` — Phase 1 processor

**Files:**
- Create: `processors/avoma_phase1.py`
- Create: `tests/test_avoma_phase1.py`

The Phase 1 processor contains helpers copied from `scripts/avoma_per_call.py` (not imported — scripts should not be imported by processors). The key behavioral differences from avoma_per_call.py: trigger text feeds into the analysis as optional context, output goes to Slack thread (not Telegram), and state is updated via `avoma_thread_state` after posting.

- [ ] **Step 1: Write failing tests**

Create `tests/test_avoma_phase1.py`:

```python
import json
import pytest
from unittest.mock import MagicMock, patch, call
from lib.storage import LocalStorage
from collectors.avoma import AvomaTranscript


def _storage(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    for d in ["state", "memory"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return s


def _fake_transcript(uuid="uuid-abc", title="TeamBuildr OS Demo - Acme Corp", os_interested=True):
    return AvomaTranscript(
        uuid=uuid,
        title=title,
        start_at="2026-06-02T14:00:00Z",
        participants=["john@acme.com", "trent@teambuildr.com"],
        call_type="demo",
        os_interested=os_interested,
        summary="Good demo. Strong interest.",
        features_covered=["scheduling"],
        gaps=["mobile app"],
        objections=[],
        buying_signals=["asked about pricing"],
        competitors=[],
        onboarding_completed=[],
        onboarding_next_steps=[],
        action_items=["Send pricing deck", "Schedule follow-up"],
    )


def _config():
    return {
        "ai_model": "claude-sonnet-4-6",
        "avoma": {
            "lookback_hours": 96,
            "filter_internal": True,
            "sales_rep_emails": ["trent@teambuildr.com"],
        },
    }


def test_run_phase1_posts_output_to_thread(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="https://avoma.com/meetings/uuid-abc"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript()), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="1234.9999") as mock_post, \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    mock_post.assert_called_once()
    args = mock_post.call_args
    assert args[0][1] == "C-avoma"  # channel_id
    assert args[0][2] == "t.123"    # thread_ts
    assert "Acme Corp" in args[0][3] or "Action Items" in args[0][3]


def test_run_phase1_sets_processed_state(tmp_path):
    from processors.avoma_phase1 import run_phase1
    from processors.avoma_thread_state import is_processed
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="https://avoma.com/meetings/uuid-abc"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript()), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="1234.9999"), \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    assert is_processed(s, "t.123") is True


def test_run_phase1_is_idempotent(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="url"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript()), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="1234.9999") as mock_post, \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")
        run_phase1("t.123", "C-avoma", "second call", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    # post_to_thread called exactly once — second run skipped
    assert mock_post.call_count == 1


def test_run_phase1_posts_error_when_transcript_not_found(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="no uuid here"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value=None), \
         patch("processors.avoma_phase1.fetch_recent_meetings", return_value=[]), \
         patch("processors.avoma_phase1.post_to_thread", return_value=None) as mock_post:
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    mock_post.assert_called_once()
    assert "not found" in mock_post.call_args[0][3].lower() or "Could not" in mock_post.call_args[0][3]


def test_run_phase1_includes_notion_block_for_os_interested(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="url"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript(os_interested=True)), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="ts") as mock_post, \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    output = mock_post.call_args[0][3]
    assert "Notion" in output


def test_run_phase1_omits_notion_block_for_non_os(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="url"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript(os_interested=False)), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="ts") as mock_post, \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    output = mock_post.call_args[0][3]
    assert "Notion" not in output
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_avoma_phase1.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'processors.avoma_phase1'`

- [ ] **Step 3: Implement `processors/avoma_phase1.py`**

```python
"""Phase 1 Avoma processing — runs ONCE per Slack thread on first qualifying reply.

Finds the Avoma transcript from the thread's root message (UUID extraction or
title-match fallback), writes the observation, posts output to the Slack thread,
and marks the thread as processed in avoma_thread_state.
"""

from __future__ import annotations
import json
import re
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from collectors.avoma import extract_avoma_uuid_from_text, fetch_meeting_by_uuid, fetch_recent_meetings
from lib.slack_post import get_thread_root_text, post_to_thread
from processors.avoma_thread_state import is_processed, set_phase1_complete

_ROOT = Path(__file__).parent.parent
_REGISTRY_FILE = _ROOT / "data" / "people_registry.json"
_OBS_KEY = "memory/observations.jsonl"
_INTERNAL_DOMAIN = "teambuildr.com"
_FUZZY_THRESHOLD = 85
_SALES_REP_MAP = {
    "ryan@teambuildr.com": "Ryan",
    "lmartin@teambuildr.com": "Martin",
    "chris@teambuildr.com": "Chris",
    "jeff@teambuildr.com": "Jeff",
    "quinn@teambuildr.com": "Quinn",
    "trent@teambuildr.com": "Trent",
}
_NO_SHOW_KEYWORDS = ("no-show", "no show", "did not attend", "didn't attend")
_STRONG_SIGNAL_KEYWORDS = ("contract", "pricing", "timeline", "next step", "trial", "ready to start", "implement", "sign")


# ---------------------------------------------------------------------------
# Registry helpers (copied from scripts/avoma_per_call.py — processors cannot
# import from scripts)
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    if _REGISTRY_FILE.exists():
        return json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "people": []}


def _save_registry(registry: dict) -> None:
    _REGISTRY_FILE.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _build_lookup(people: list) -> tuple[dict, list]:
    email_index: dict[str, str] = {}
    alias_list: list[tuple[str, list[str], str]] = []
    for p in people:
        email = (p.get("email") or "").lower().strip()
        if email:
            email_index[email] = p["id"]
        names = [p["canonical_name"]] + [a for a in p.get("aliases", []) if "@" not in a]
        alias_list.append((p["canonical_name"], names, p["id"]))
    return email_index, alias_list


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _unique_id(base: str, existing_ids: set) -> str:
    new_id, counter = base, 2
    while new_id in existing_ids:
        new_id = f"{base}-{counter}"
        counter += 1
    return new_id


def _is_internal(s: str) -> bool:
    return s.lower().endswith(f"@{_INTERNAL_DOMAIN}")


def _resolve_participants(participants: list[str], people: list, email_index: dict, alias_list: list) -> list[dict]:
    from rapidfuzz import fuzz
    today = date.today().isoformat()
    resolved: list[dict] = []
    existing_ids = {p["id"] for p in people}

    for participant in participants:
        participant = participant.strip()
        if not participant:
            continue
        is_email = "@" in participant

        if is_email:
            pid = email_index.get(participant.lower())
            if pid:
                for p in people:
                    if p["id"] == pid:
                        p["last_seen"] = today
                        resolved.append({"name": participant, "person_id": pid, "is_new": False,
                                         "is_internal": p.get("type") == "internal", "is_stub_only": False})
                        break
                continue
            if _is_internal(participant):
                resolved.append({"name": participant, "person_id": None, "is_new": False,
                                  "is_internal": True, "is_stub_only": False})
                continue
            display = participant.split("@")[0]
            new_id = _unique_id(_slug(display), existing_ids)
            existing_ids.add(new_id)
            stub = {"id": new_id, "canonical_name": display, "aliases": [display, participant],
                    "email": participant, "type": "unknown", "pipeline_record": None, "people_file": None,
                    "created": today, "last_seen": today}
            people.append(stub)
            email_index[participant.lower()] = new_id
            alias_list.append((display, [display], new_id))
            resolved.append({"name": participant, "person_id": new_id, "is_new": True,
                              "is_internal": False, "is_stub_only": True})
            continue

        best_id, best_score = None, 0
        for _canonical, aliases, pid in alias_list:
            for alias in aliases:
                score = fuzz.token_sort_ratio(participant.lower(), alias.lower())
                if score > best_score:
                    best_score, best_id = score, pid

        if best_score >= _FUZZY_THRESHOLD and best_id:
            for p in people:
                if p["id"] == best_id:
                    p["last_seen"] = today
                    is_int = p.get("type") == "internal"
                    break
            else:
                is_int = False
            resolved.append({"name": participant, "person_id": best_id, "is_new": False,
                              "is_internal": is_int, "is_stub_only": False})
            continue

        if any(rep.lower() == participant.lower().split()[0] for rep in _SALES_REP_MAP.values()):
            resolved.append({"name": participant, "person_id": None, "is_new": False,
                              "is_internal": True, "is_stub_only": False})
            continue

        new_id = _unique_id(_slug(participant) if participant else "unknown", existing_ids)
        existing_ids.add(new_id)
        stub = {"id": new_id, "canonical_name": participant, "aliases": [participant], "email": "",
                "type": "unknown", "pipeline_record": None, "people_file": None,
                "created": today, "last_seen": today}
        people.append(stub)
        alias_list.append((participant, [participant], new_id))
        resolved.append({"name": participant, "person_id": new_id, "is_new": True,
                          "is_internal": False, "is_stub_only": True})

    return resolved


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def _write_observation(t, resolved_people: list, storage) -> None:
    from processors.memory_observer import _transcript_to_observation, _load_registry as _load_obs_registry
    _email_index, alias_list, internal_ids = _load_obs_registry()
    obs = _transcript_to_observation(t, alias_list, internal_ids)
    storage.append_line(_OBS_KEY, json.dumps(obs))


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

def _extract_lead_name(title: str) -> str:
    prefixes = (
        "TeamBuildr OS Demo - ", "TeamBuildr OS Demo | ", "TeamBuildr OS Demo: ",
        "TeamBuildr Demo - ", "TeamBuildr Demo | ", "TeamBuildr Demo: ",
        "Demo - ", "Demo | ", "Demo: ",
        "Follow Up - ", "Follow Up | ", "Follow Up: ",
        "Follow-Up - ", "Follow-Up | ", "Follow-Up: ",
        "Onboarding - ", "Onboarding | ", "Onboarding: ",
        "Onboarding Session - ", "Onboarding Call - ",
    )
    for prefix in prefixes:
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title.strip()


def _format_call_date(start_at: str) -> str:
    try:
        return datetime.fromisoformat(start_at.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return date.today().isoformat()


def _infer_pipeline_status(t) -> str:
    summary_lower = t.summary.lower()
    if any(kw in summary_lower for kw in _NO_SHOW_KEYWORDS):
        return "No-Show"
    if t.call_type == "demo":
        if t.buying_signals and any(
            any(kw in s.lower() for kw in _STRONG_SIGNAL_KEYWORDS)
            for s in t.buying_signals
        ):
            return "In-Trial / Post Demo"
        return "No Trial / Post Demo"
    if t.call_type == "follow_up":
        return "On-Hold" if t.objections else "Out of Demo / Need Update"
    return "Post Demo"


def _infer_account_owner(participants: list[str]) -> str:
    for p in participants:
        p_lower = p.lower().strip()
        for email, name in _SALES_REP_MAP.items():
            if email.lower() in p_lower:
                return name
    return "Unknown"


def _build_notion_prompt(t, lead_name: str) -> str:
    call_date = _format_call_date(t.start_at)
    call_label = t.call_type.replace("_", " ").title()
    owner = _infer_account_owner(t.participants)
    action_items_str = "; ".join(t.action_items[:6]) if t.action_items else "none"

    if t.call_type == "onboarding":
        completed = "; ".join(t.onboarding_completed) if t.onboarding_completed else "none noted"
        next_steps = "; ".join(t.onboarding_next_steps) if t.onboarding_next_steps else "none noted"
        return (
            "📤 Notion Onboarding Update — paste into Claude Desktop\n"
            f"Update the onboarding tracker for {lead_name}. "
            f"Call date: {call_date}. "
            f"Summary: {t.summary} "
            f"Completed: {completed}. "
            f"Next steps: {next_steps}. "
            f"Action items: {action_items_str}."
        )
    else:
        status = _infer_pipeline_status(t)
        signals = "; ".join(t.buying_signals[:3]) if t.buying_signals else "none"
        objections = "; ".join(t.objections[:3]) if t.objections else "none"
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


def _build_slack_message(t, lead_name: str, resolved_people: list, trigger_text: str) -> str:
    call_label = t.call_type.replace("_", " ").title() if t.call_type else "Call"
    external = [r for r in resolved_people if not r["is_internal"]]
    participants_display = ", ".join(r["name"] for r in external) or ", ".join(t.participants[:5])

    lines = [
        f"*{lead_name}* — {call_label}",
        participants_display,
        "",
        "*Summary*",
        t.summary or "(no summary)",
    ]

    if t.action_items:
        lines += ["", "*Action Items*"]
        for i, item in enumerate(t.action_items[:8], 1):
            lines.append(f"{i}. {item}")

    new_stubs = [r for r in resolved_people if r["is_new"] and not r["is_internal"]]
    if new_stubs:
        names = ", ".join(r["name"] for r in new_stubs)
        lines += ["", f"⚠️ New contact(s) — stub only, no file yet: {names}"]

    if t.os_interested and t.call_type in ("demo", "follow_up", "onboarding"):
        notion_block = _build_notion_prompt(t, lead_name)
        if notion_block:
            lines += ["", notion_block]

    msg = "\n".join(lines)
    if len(msg) > 3000:
        msg = msg[:2990] + "\n…(truncated)"
    return msg


# ---------------------------------------------------------------------------
# Transcript lookup
# ---------------------------------------------------------------------------

_READY_PHRASES = frozenset({"ready to process", "ready", "process", "go", "process this", "ready to go"})


def _find_transcript(root_text: str, avoma_api_key: str, anthropic_api_key: str, config: dict, trigger_text: str = ""):
    """Find the Avoma transcript for a thread. UUID extraction first, title-match fallback.

    trigger_text is passed as a context note to Claude if it contains rep-supplied context
    (i.e. anything other than a bare 'ready to process' variant).
    """
    context_note = "" if trigger_text.strip().lower() in _READY_PHRASES else trigger_text.strip()
    uuid = extract_avoma_uuid_from_text(root_text)
    if uuid:
        model = config.get("ai_model", "claude-sonnet-4-6")
        return fetch_meeting_by_uuid(avoma_api_key, anthropic_api_key, model, uuid, context_note=context_note)

    avoma_cfg = config.get("avoma", {})
    model = config.get("ai_model", "claude-sonnet-4-6")
    try:
        transcripts = fetch_recent_meetings(
            api_key=avoma_api_key,
            anthropic_api_key=anthropic_api_key,
            model=model,
            lookback_hours=avoma_cfg.get("lookback_hours", 96),
            sales_rep_emails=avoma_cfg.get("sales_rep_emails", []),
            filter_internal=avoma_cfg.get("filter_internal", True),
            include_non_os=True,
        )
    except Exception as e:
        print(f"WARNING: fetch_recent_meetings failed: {e}", file=sys.stderr)
        return None

    if not transcripts:
        return None

    root_lower = (root_text or "").lower()
    best, best_score = None, 0
    for t in transcripts:
        title_words = [w for w in t.title.lower().split() if len(w) > 3]
        score = sum(1 for w in title_words if w in root_lower)
        if score > best_score:
            best_score, best = score, t

    return best if best_score > 0 else transcripts[0]  # fall back to most recent


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_phase1(
    thread_ts: str,
    channel_id: str,
    trigger_text: str,
    storage,
    config: dict,
    avoma_api_key: str,
    anthropic_api_key: str,
    slack_bot_token: str,
) -> None:
    """Run Phase 1 processing for a Slack thread. Posts output; sets processed state. Idempotent."""
    if is_processed(storage, thread_ts):
        return

    root_text = get_thread_root_text(slack_bot_token, channel_id, thread_ts)
    transcript = _find_transcript(root_text, avoma_api_key, anthropic_api_key, config, trigger_text=trigger_text)

    if not transcript:
        post_to_thread(slack_bot_token, channel_id, thread_ts,
                       "Could not find an Avoma transcript for this thread. "
                       "Check that the meeting UUID is in the Avoma post, or try again after the transcript is ready.")
        return

    registry = _load_registry()
    people = registry["people"]
    email_index, alias_list = _build_lookup(people)
    resolved_people = _resolve_participants(transcript.participants, people, email_index, alias_list)

    try:
        _write_observation(transcript, resolved_people, storage)
    except Exception as e:
        print(f"WARNING: observation write failed for {transcript.uuid}: {e}", file=sys.stderr)

    lead_name = _extract_lead_name(transcript.title)
    output_text = _build_slack_message(transcript, lead_name, resolved_people, trigger_text)
    output_ts = post_to_thread(slack_bot_token, channel_id, thread_ts, output_text)

    transcript_json = {
        "uuid": transcript.uuid,
        "title": transcript.title,
        "start_at": transcript.start_at,
        "participants": transcript.participants,
        "call_type": transcript.call_type,
        "os_interested": transcript.os_interested,
        "summary": transcript.summary,
        "action_items": transcript.action_items,
        "features_covered": transcript.features_covered,
        "gaps": transcript.gaps,
        "objections": transcript.objections,
        "buying_signals": transcript.buying_signals,
        "competitors": transcript.competitors,
        "onboarding_completed": transcript.onboarding_completed,
        "onboarding_next_steps": transcript.onboarding_next_steps,
    }
    set_phase1_complete(storage, thread_ts, transcript.uuid, output_ts, output_text, transcript_json)

    registry["people"] = people
    _save_registry(registry)
    print(f"Phase 1 complete for thread {thread_ts}: {transcript.title}")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_avoma_phase1.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/avoma_phase1.py tests/test_avoma_phase1.py
git commit -m "feat: add avoma_phase1 processor — finds transcript, writes obs, posts output to Slack thread"
```

---

## Task 5: `processors/avoma_phase2.py` — conversation handler

**Files:**
- Create: `processors/avoma_phase2.py`
- Create: `tests/test_avoma_phase2.py`

Phase 2 handles messages after Phase 1 output is posted. It uses Claude with a `propose_correction` tool. Pure questions get text replies. Edit requests get a proposal posted to the thread and `pending_correction` written to state. A subsequent confirmation message triggers `_apply_correction`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_avoma_phase2.py`:

```python
import json
import pytest
from unittest.mock import MagicMock, patch
from lib.storage import LocalStorage
from processors.avoma_thread_state import set_phase1_complete


def _storage(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    for d in ["state", "memory"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return s


def _state_record(phase1_output="Action items: 1. Send pricing deck", transcript_json=None):
    return {
        "phase": 2,
        "avoma_uuid": "uuid-abc",
        "processed_at": "2026-06-02T14:00:00+00:00",
        "output_ts": "ts.999",
        "phase1_output": phase1_output,
        "transcript_json": transcript_json or {"uuid": "uuid-abc", "title": "Demo - Acme", "summary": "Good call."},
        "pending_correction": None,
    }


def _config():
    return {"ai_model": "claude-sonnet-4-6"}


def _make_text_response(text="Here is your answer."):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _make_tool_response(description="Fix the name", writes=None, notion_payload=None, prompt="Reply yes to confirm"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "propose_correction"
    block.input = {
        "description": description,
        "writes": writes or [{"type": "observation_correction", "target": "observations.jsonl", "value": "corrected name"}],
        "notion_payload": notion_payload,
        "confirmation_prompt": prompt,
    }
    resp = MagicMock()
    resp.content = [block]
    return resp


def test_phase2_question_posts_answer(tmp_path):
    from processors.avoma_phase2 import run_phase2
    s = _storage(tmp_path)
    rec = _state_record()

    with patch("processors.avoma_phase2.anthropic.Anthropic") as mock_cls, \
         patch("processors.avoma_phase2.post_to_thread", return_value="ts.post") as mock_post:
        mock_cls.return_value.messages.create.return_value = _make_text_response("They discussed pricing on the call.")
        run_phase2("t.123", "what did they say about pricing?", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    mock_post.assert_called_once()
    assert "pricing" in mock_post.call_args[0][3].lower() or "discussed" in mock_post.call_args[0][3].lower()


def test_phase2_correction_stores_pending_and_posts_proposal(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from processors.avoma_thread_state import get_thread_record
    s = _storage(tmp_path)
    set_phase1_complete(s, "t.123", "uuid-abc", "ts.999", "output", {})

    with patch("processors.avoma_phase2.anthropic.Anthropic") as mock_cls, \
         patch("processors.avoma_phase2.post_to_thread", return_value="ts.post") as mock_post:
        mock_cls.return_value.messages.create.return_value = _make_tool_response(
            description="Change rep name from Chris to Quinn"
        )
        run_phase2("t.123", "their account owner is Quinn not Chris", _state_record(), "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    rec = get_thread_record(s, "t.123")
    assert rec["pending_correction"] is not None
    assert "Quinn" in rec["pending_correction"]["description"] or "name" in rec["pending_correction"]["description"].lower()
    mock_post.assert_called_once()


def test_phase2_confirmation_applies_correction(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from processors.avoma_thread_state import set_phase1_complete, set_pending_correction, get_thread_record
    s = _storage(tmp_path)
    set_phase1_complete(s, "t.123", "uuid-abc", "ts.999", "output", {"uuid": "uuid-abc"})
    set_pending_correction(s, "t.123", {
        "description": "Fix rep name",
        "writes": [{"type": "observation_correction", "target": "observations.jsonl", "value": "corrected info"}],
        "notion_payload": None,
        "confirmation_prompt": "Reply yes to confirm",
    })

    state_rec = get_thread_record(s, "t.123")

    with patch("processors.avoma_phase2.post_to_thread", return_value="ts.ack") as mock_post:
        run_phase2("t.123", "yes", state_rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    rec = get_thread_record(s, "t.123")
    assert rec["pending_correction"] is None
    mock_post.assert_called_once()

    obs = (tmp_path / "memory" / "observations.jsonl").read_text()
    assert "correction" in obs


def test_phase2_rejection_clears_pending(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from processors.avoma_thread_state import set_phase1_complete, set_pending_correction, get_thread_record
    s = _storage(tmp_path)
    set_phase1_complete(s, "t.123", "uuid-abc", "ts.999", "output", {})
    set_pending_correction(s, "t.123", {
        "description": "Fix name", "writes": [], "notion_payload": None, "confirmation_prompt": "Reply yes"
    })

    state_rec = get_thread_record(s, "t.123")

    with patch("processors.avoma_phase2.post_to_thread"):
        run_phase2("t.123", "no", state_rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    assert get_thread_record(s, "t.123")["pending_correction"] is None


def test_phase2_notion_payload_included_in_proposal(tmp_path):
    from processors.avoma_phase2 import run_phase2
    s = _storage(tmp_path)
    set_phase1_complete(s, "t.123", "uuid-abc", "ts.999", "output", {})

    notion_payload = "📤 Notion Pipeline Update — paste into Claude Desktop\nUpdate record for Acme..."

    with patch("processors.avoma_phase2.anthropic.Anthropic") as mock_cls, \
         patch("processors.avoma_phase2.post_to_thread") as mock_post:
        mock_cls.return_value.messages.create.return_value = _make_tool_response(
            notion_payload=notion_payload
        )
        run_phase2("t.123", "drop objection 1", _state_record(), "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    post_text = mock_post.call_args[0][3]
    assert "Notion" in post_text
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_avoma_phase2.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'processors.avoma_phase2'`

- [ ] **Step 3: Implement `processors/avoma_phase2.py`**

```python
"""Phase 2 Avoma conversation handler — Q&A and gate-confirmed corrections.

After Phase 1 posts output to the thread, subsequent replies route here.
Claude gets the Phase 1 output and transcript analysis as context.

- Questions → text answer posted to thread; no writes.
- Edit requests → Claude calls propose_correction; bot posts proposal;
  pending_correction written to state. A "yes" confirmation applies writes.
- "no"/"cancel" → clears pending_correction.

Correction write routing:
  observation_correction → append new correction-type obs to observations.jsonl
  people_file → append correction block in place to data/people/<file>.md
  payload → Notion paste block re-posted (no file write; it's paste-only)
"""

from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path

import anthropic

from lib.slack_post import post_to_thread
from processors.avoma_thread_state import set_pending_correction, clear_pending_correction

_OBS_KEY = "memory/observations.jsonl"

_SYSTEM_PROMPT = (
    "You are Trent Luecke's AI Chief of Staff. A sales call was just analyzed and the output "
    "was posted to the thread. Trent has replied with a question or a correction.\n\n"
    "If it's a question about the call: answer directly and concisely from the data provided.\n"
    "If it's an edit or correction: call propose_correction with a precise description of what "
    "would change and where. Be specific: name the target (observation log, people file path, "
    "or Notion payload). If the Notion payload block would change, include a corrected version "
    "in notion_payload. confirmation_prompt should say exactly what Trent needs to reply to confirm.\n\n"
    "No preamble. Be concise."
)

_PROPOSE_TOOL = {
    "name": "propose_correction",
    "description": "Propose a write that requires Trent's confirmation before applying.",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Plain English: what changes, where, and why.",
            },
            "writes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["observation_correction", "people_file", "payload"],
                        },
                        "target": {
                            "type": "string",
                            "description": "observations.jsonl, people file path (e.g. data/people/john-smith.md), or 'notion_payload'",
                        },
                        "value": {"type": "string", "description": "The correction or new value."},
                    },
                    "required": ["type", "target", "value"],
                },
            },
            "notion_payload": {
                "type": ["string", "null"],
                "description": "Corrected Notion paste block if the payload is affected, else null.",
            },
            "confirmation_prompt": {
                "type": "string",
                "description": "Message asking Trent to confirm, e.g. 'Reply yes to apply this correction.'",
            },
        },
        "required": ["description", "writes", "notion_payload", "confirmation_prompt"],
    },
}

_CONFIRMATIONS = {"yes", "confirm", "confirmed", "ok", "apply", "do it", "yep", "yeah"}
_REJECTIONS = {"no", "cancel", "nevermind", "never mind", "skip", "nope", "don't"}


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

    _handle_fresh_message(thread_ts, trigger_text, state_record, slack_bot_token, channel_id, storage, config, anthropic_api_key)


def _handle_fresh_message(
    thread_ts: str,
    trigger_text: str,
    state_record: dict,
    slack_bot_token: str,
    channel_id: str,
    storage,
    config: dict,
    anthropic_api_key: str,
) -> None:
    phase1_output = state_record.get("phase1_output", "")
    transcript_json = state_record.get("transcript_json", {})
    model = config.get("ai_model", "claude-sonnet-4-6")

    user_content = (
        f"## Phase 1 Output\n{phase1_output}\n\n"
        f"## Call Analysis\n{json.dumps(transcript_json, indent=2)}\n\n"
        f"## Trent's message\n{trigger_text}"
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        system=_SYSTEM_PROMPT,
        tools=[_PROPOSE_TOOL],
        messages=[{"role": "user", "content": user_content}],
    )

    correction_input = None
    text_response = ""
    for block in response.content:
        if block.type == "tool_use" and block.name == "propose_correction":
            correction_input = block.input
        elif block.type == "text":
            text_response = block.text.strip()

    if correction_input:
        set_pending_correction(storage, thread_ts, {
            "description": correction_input["description"],
            "writes": correction_input["writes"],
            "notion_payload": correction_input.get("notion_payload"),
            "confirmation_prompt": correction_input["confirmation_prompt"],
        })
        msg = f"Proposed correction: {correction_input['description']}\n\n{correction_input['confirmation_prompt']}"
        if correction_input.get("notion_payload"):
            msg += f"\n\n{correction_input['notion_payload']}"
        post_to_thread(slack_bot_token, channel_id, thread_ts, msg)
    else:
        post_to_thread(slack_bot_token, channel_id, thread_ts, text_response or "(no response)")


def _apply_correction(
    pending: dict,
    state_record: dict,
    storage,
    slack_bot_token: str,
    channel_id: str,
    thread_ts: str,
) -> None:
    applied: list[str] = []

    for write in pending.get("writes", []):
        write_type = write.get("type")
        target = write.get("target", "")
        value = write.get("value", "")

        if write_type == "observation_correction":
            _append_correction_obs(storage, state_record.get("avoma_uuid"), pending["description"], value)
            applied.append("appended correction observation")

        elif write_type == "people_file":
            _apply_people_file_write(target, value)
            applied.append(f"updated {target}")

        elif write_type == "payload":
            applied.append("Notion payload noted (paste manually)")

    if pending.get("notion_payload"):
        ack = f"Correction applied ({'; '.join(applied)}).\n\nCorrected Notion payload:\n{pending['notion_payload']}"
    else:
        ack = f"Correction applied: {'; '.join(applied) or 'no writes'}."

    post_to_thread(slack_bot_token, channel_id, thread_ts, ack)


def _append_correction_obs(storage, supersedes_uuid: str | None, description: str, value: str) -> None:
    obs = {
        "date": date.today().isoformat(),
        "source": "avoma_correction",
        "type": "correction",
        "supersedes_uuid": supersedes_uuid,
        "content": f"Correction to call analysis: {description}. {value}",
        "primary_person_id": None,
    }
    storage.append_line(_OBS_KEY, json.dumps(obs))


def _apply_people_file_write(target_path: str, value: str) -> None:
    path = Path(target_path)
    if not path.exists():
        print(f"WARNING: people file not found: {target_path}", file=sys.stderr)
        return
    current = path.read_text(encoding="utf-8")
    block = f"\n\n## Correction ({date.today().isoformat()})\n{value}\n"
    path.write_text(current + block, encoding="utf-8")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/test_avoma_phase2.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/avoma_phase2.py tests/test_avoma_phase2.py
git commit -m "feat: add avoma_phase2 conversation handler — Q&A and gate-confirmed corrections"
```

---

## Task 6: `scripts/avoma_slack_processor.py` — dispatcher

**Files:**
- Create: `scripts/avoma_slack_processor.py`

This is a thin env-loading script. No separate tests (integration tested by Phase 1/2 module tests).

- [ ] **Step 1: Create `scripts/avoma_slack_processor.py`**

```python
#!/usr/bin/env python3
"""Avoma Slack thread processor — dispatched by avoma_slack_trigger.yml.

Reads env vars, routes to Phase 1 (first reply) or Phase 2 (subsequent replies).
"""

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")

    thread_ts = os.environ.get("AVOMA_THREAD_TS", "").strip()
    channel_id = os.environ.get("AVOMA_CHANNEL_ID", "").strip()
    trigger_text = os.environ.get("AVOMA_TRIGGER_TEXT", "").strip()
    avoma_key = os.environ.get("AVOMA_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    slack_bot_token = os.environ.get("SLACK_BOT_TOKEN", "")

    for name, val in [
        ("AVOMA_THREAD_TS", thread_ts),
        ("AVOMA_CHANNEL_ID", channel_id),
        ("AVOMA_API_KEY", avoma_key),
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("SLACK_BOT_TOKEN", slack_bot_token),
    ]:
        if not val:
            print(f"ERROR: {name} not set — avoma_slack_processor cannot run.", file=sys.stderr)
            sys.exit(0)  # non-fatal — never fail the Actions run

    config_path = _ROOT / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    from lib.storage import build_storage
    storage = build_storage(config)

    from processors.avoma_thread_state import is_processed, get_thread_record

    if not is_processed(storage, thread_ts):
        print(f"Phase 1: processing thread {thread_ts}")
        from processors.avoma_phase1 import run_phase1
        run_phase1(thread_ts, channel_id, trigger_text, storage, config, avoma_key, anthropic_key, slack_bot_token)
    else:
        state_record = get_thread_record(storage, thread_ts)
        print(f"Phase 2: conversation for thread {thread_ts}")
        from processors.avoma_phase2 import run_phase2
        run_phase2(thread_ts, trigger_text, state_record, slack_bot_token, channel_id, storage, config, anthropic_key)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: avoma_slack_processor failed: {exc}", file=sys.stderr)
        sys.exit(0)  # non-fatal
```

- [ ] **Step 2: Verify the script parses without errors**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -c "import ast; ast.parse(open('scripts/avoma_slack_processor.py').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/avoma_slack_processor.py
git commit -m "feat: add avoma_slack_processor dispatcher (Phase 1/2 router)"
```

---

## Task 7: GitHub Actions workflow — `avoma_slack_trigger.yml`

**Files:**
- Create: `.github/workflows/avoma_slack_trigger.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/avoma_slack_trigger.yml`:

```yaml
name: Avoma Slack Thread Trigger

on:
  workflow_dispatch:
    inputs:
      thread_ts:
        description: "Slack thread timestamp (thread root ts)"
        required: true
        type: string
      channel_id:
        description: "Slack channel ID"
        required: true
        type: string
      trigger_text:
        description: "Text of the reply that triggered this run"
        required: true
        type: string

jobs:
  process:
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

      - name: Run Avoma Slack processor
        env:
          AVOMA_THREAD_TS: ${{ inputs.thread_ts }}
          AVOMA_CHANNEL_ID: ${{ inputs.channel_id }}
          AVOMA_TRIGGER_TEXT: ${{ inputs.trigger_text }}
          AVOMA_API_KEY: ${{ secrets.AVOMA_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
        run: python scripts/avoma_slack_processor.py

      - name: Commit data changes
        run: |
          git add data/people_registry.json 2>/dev/null || true
          git diff --staged --quiet || git commit -m "chore: avoma slack processor data update [skip ci]"
          git pull --rebase origin main || true
          git push origin main || true
```

- [ ] **Step 2: Verify YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('/Users/trentluecke/dev/Claude-Projects/chief-of-staff/.github/workflows/avoma_slack_trigger.yml')); print('YAML valid')"
```

Expected: `YAML valid`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/avoma_slack_trigger.yml
git commit -m "feat: add avoma_slack_trigger GitHub Actions workflow"
```

---

## Task 8: Cloudflare Worker — `cloudflare/avoma-slack-bridge.js`

**Files:**
- Create: `cloudflare/avoma-slack-bridge.js`
- Create: `cloudflare/avoma-wrangler.toml`

The Worker:
1. Handles `url_verification` challenge (respond with `{"challenge": "..."}`)
2. Verifies Slack request signature (HMAC-SHA256 with `SLACK_SIGNING_SECRET` + 5-minute replay window)
3. Drops: non-`message` events, any `subtype` (bot_message, message_changed, etc.), events with `bot_id`, messages not from `AVOMA_CHANNEL_ID`, messages where `thread_ts === ts` (root post, not a reply)
4. Acks immediately via `ctx.waitUntil()`, dispatches to `avoma-slack-trigger.yml` via GitHub API

- [ ] **Step 1: Create `cloudflare/avoma-slack-bridge.js`**

```javascript
// cloudflare/avoma-slack-bridge.js
// Slack Events API bridge → GitHub Actions dispatch for Avoma thread processing.

async function verifySlackSignature(request, body, signingSecret) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp");
  const provided = request.headers.get("X-Slack-Signature");
  if (!timestamp || !provided) return false;

  // Replay protection: reject if > 5 minutes old
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp, 10)) > 300) return false;

  const encoder = new TextEncoder();
  const keyData = encoder.encode(signingSecret);
  const msgData = encoder.encode(`v0:${timestamp}:${body}`);

  const key = await crypto.subtle.importKey(
    "raw", keyData, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, msgData);
  const hexSig = "v0=" + Array.from(new Uint8Array(sig))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");

  // Constant-time comparison
  if (hexSig.length !== provided.length) return false;
  let diff = 0;
  for (let i = 0; i < hexSig.length; i++) {
    diff |= hexSig.charCodeAt(i) ^ provided.charCodeAt(i);
  }
  return diff === 0;
}

async function dispatchToGitHub(env, thread_ts, channel_id, trigger_text) {
  const inputs = { thread_ts, channel_id, trigger_text };
  const resp = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/avoma_slack_trigger.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "chief-of-staff-avoma-bridge",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    }
  );
  if (!resp.ok) {
    console.error(`GitHub dispatch error: ${resp.status} ${await resp.text()}`);
  }
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("OK");

    const body = await request.text();

    // Verify Slack signature before parsing body
    const valid = await verifySlackSignature(request, body, env.SLACK_SIGNING_SECRET);
    if (!valid) return new Response("Unauthorized", { status: 401 });

    let payload;
    try {
      payload = JSON.parse(body);
    } catch {
      return new Response("OK");
    }

    // Handle Slack's initial url_verification challenge
    if (payload.type === "url_verification") {
      return new Response(JSON.stringify({ challenge: payload.challenge }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    const event = payload.event;
    if (!event) return new Response("OK");

    // Drop: non-message events, any subtype (bot_message, message_changed, etc.), bot messages
    if (event.type !== "message") return new Response("OK");
    if (event.subtype) return new Response("OK");
    if (event.bot_id) return new Response("OK");

    // Only process events in the configured Avoma channel
    if (event.channel !== env.AVOMA_CHANNEL_ID) return new Response("OK");

    // Only process thread replies, not root posts
    // Root posts have thread_ts === ts (or no thread_ts)
    if (!event.thread_ts || event.thread_ts === event.ts) return new Response("OK");

    const thread_ts = event.thread_ts;
    const channel_id = event.channel;
    const trigger_text = (event.text || "").trim();

    console.log(`Avoma thread reply: thread_ts=${thread_ts}, text="${trigger_text.slice(0, 60)}"`);

    // Ack immediately; dispatch runs in background after response is sent
    ctx.waitUntil(dispatchToGitHub(env, thread_ts, channel_id, trigger_text));
    return new Response("OK");
  },
};
```

- [ ] **Step 2: Create `cloudflare/avoma-wrangler.toml`**

```toml
name = "chief-of-staff-avoma-bridge"
main = "avoma-slack-bridge.js"
compatibility_date = "2024-01-01"

[observability]
enabled = false

[observability.logs]
enabled = true
head_sampling_rate = 1
persist = true
invocation_logs = true
```

- [ ] **Step 3: Verify JS syntax**

```bash
node --input-type=module --eval "$(cat /Users/trentluecke/dev/Claude-Projects/chief-of-staff/cloudflare/avoma-slack-bridge.js)" 2>&1 | head -5 || echo "syntax check done"
```

Expected: module evaluates without syntax errors (may throw on missing `crypto` — that's a runtime env thing, not a syntax error).

- [ ] **Step 4: Commit**

```bash
git add cloudflare/avoma-slack-bridge.js cloudflare/avoma-wrangler.toml
git commit -m "feat: add Cloudflare Worker for Slack Events API → GitHub Actions dispatch (Avoma thread trigger)"
```

---

## Task 9: Config update + disable old cron trigger

**Files:**
- Modify: `config.json`
- Modify: `.github/workflows/avoma_per_call.yml`

- [ ] **Step 1: Add `slack_channel_id` to `config.json`**

In `config.json`, add `"slack_channel_id": ""` to the `avoma` block:

```json
  "avoma": {
    "enabled": true,
    "lookback_hours": 96,
    "filter_internal": true,
    "slack_channel_id": "",
    "sales_rep_emails": [
      "ryan@teambuildr.com",
      "lmartin@teambuildr.com",
      "chris@teambuildr.com",
      "jeff@teambuildr.com",
      "quinn@teambuildr.com",
      "trent@teambuildr.com"
    ]
  },
```

Note: set `slack_channel_id` to the actual Avoma-Trent channel ID after completing the Slack app setup below.

- [ ] **Step 2: Disable the cron trigger in `avoma_per_call.yml`**

In `.github/workflows/avoma_per_call.yml`, remove the `schedule` block so only `workflow_dispatch` remains:

```yaml
on:
  workflow_dispatch:
```

(The file is kept for manual fallback / backfill runs — just remove the `schedule:` key and its `cron` line.)

- [ ] **Step 3: Run full test suite to verify no regressions**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest tests/ -q --ignore=tests/test_memory_retriever_integration.py --ignore=tests/test_vector_ingest_integration.py 2>&1 | tail -15
```

Expected: all non-integration tests pass.

- [ ] **Step 4: Commit**

```bash
git add config.json .github/workflows/avoma_per_call.yml
git commit -m "feat: add avoma.slack_channel_id config; disable avoma_per_call cron (replaced by Slack trigger)"
```

---

## Task 10: One-time Slack app and Worker setup

This task is manual setup — no code changes. Complete it once after deploying the Worker.

- [ ] **Step 1: Create a Slack app (or add to existing)**

In the Slack app settings (`api.slack.com/apps`):

1. Under *Event Subscriptions* → Enable Events → set Request URL to the Worker's `https://...workers.dev` URL.
2. Subscribe to Bot Events: add `message.channels`.
3. Under *OAuth & Permissions*, add scopes: `channels:history`, `channels:read`, `chat:write`.
4. Install the app to the workspace.

- [ ] **Step 2: Invite the bot to the Avoma-Trent channel**

In Slack, open the Avoma-Trent channel and type `/invite @<bot-name>`.

- [ ] **Step 3: Get the channel ID**

In Slack, right-click the Avoma-Trent channel → *Copy link* → extract the channel ID from the URL (starts with `C`).

- [ ] **Step 4: Set Cloudflare Worker secrets**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/cloudflare
wrangler secret put SLACK_SIGNING_SECRET --config avoma-wrangler.toml
wrangler secret put AVOMA_CHANNEL_ID --config avoma-wrangler.toml
wrangler secret put GITHUB_PAT --config avoma-wrangler.toml
wrangler secret put GITHUB_REPO --config avoma-wrangler.toml
```

Enter the values when prompted: Slack app's Signing Secret, channel ID from Step 3, existing GitHub PAT (same as `telegram-bridge`), and `trentluecke/Claude-Projects` (or whatever `GITHUB_REPO` is).

- [ ] **Step 5: Deploy the Worker**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/cloudflare
wrangler deploy --config avoma-wrangler.toml
```

- [ ] **Step 6: Verify the Slack URL verification challenge passed**

After setting the Request URL in Step 1, Slack sends a `url_verification` challenge. The Worker responds with `{"challenge": "..."}`. Slack shows a green checkmark. If it fails, check Worker logs in the Cloudflare dashboard.

- [ ] **Step 7: Update `config.json` with the real channel ID**

Set `avoma.slack_channel_id` to the channel ID from Step 3 and push:

```bash
git add config.json
git commit -m "chore: set avoma.slack_channel_id [skip ci]"
git push origin main
```

---

## Self-Review

**Spec coverage:**

- [x] Slack Events API push trigger via Cloudflare Worker (not polling)
- [x] `url_verification` challenge handled (Task 8)
- [x] Signature verification with 5-minute replay protection (Task 8)
- [x] 3-second ack with async dispatch via `ctx.waitUntil()` (Task 8)
- [x] Loop guard: drop `bot_id` events and all `subtype` events (Task 8)
- [x] Drop non-thread messages (`thread_ts === ts` or absent) (Task 8)
- [x] Channel filter: only `AVOMA_CHANNEL_ID` events processed (Task 8)
- [x] Once-per-thread marker via `avoma_thread_state.json` (Task 2)
- [x] Phase 1 runs once; "ready to process" → null context, other text → context prompt (Task 4 — trigger_text passed through but not yet wired into the Claude prompt; see gap note below)
- [x] Phase 1 writes observation (non-fatal) (Task 4)
- [x] Phase 1 posts action items + Notion payload for OS-interested calls (Task 4)
- [x] Non-OS calls get action items only (Task 4)
- [x] Phase 1 state set atomically after posting (Task 4)
- [x] Phase 2 questions answered without re-running Avoma processing (Task 5)
- [x] Phase 2 corrections discussed + confirmation-gated (Task 5)
- [x] Confirmed observation correction appended as new `correction` type (Task 5)
- [x] Confirmed people file correction appended in-place (Task 5)
- [x] Notion payload re-post offered in correction proposals (Task 5)
- [x] Slack retries / duplicates do NOT cause double Phase 1 (idempotency test in Task 4)

- [x] trigger_text is fed into the Claude transcript analysis as a "Note from rep" when it contains meaningful context (anything other than bare "ready to process" variants). Flows: `run_phase1` → `_find_transcript(trigger_text=...)` → `fetch_meeting_by_uuid(context_note=...)` → `_analyze_with_claude(context_note=...)` → appended to user message. "ready to process" and similar bare-ack phrases produce `context_note=""` so they're filtered cleanly at `_READY_PHRASES`.

**Placeholder scan:** None found.

**Type consistency:** `run_phase1` and `run_phase2` signatures are consistent with how `avoma_slack_processor.py` calls them. `set_phase1_complete` / `get_thread_record` / `set_pending_correction` / `clear_pending_correction` signatures match usage across Task 4 and Task 5.
