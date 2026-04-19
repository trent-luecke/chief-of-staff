# P4 Two-Way Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Telegram query channel and an email feedback channel so Trent can ask ad hoc questions and tune the brief without touching code.

**Architecture:** A Cloudflare Worker (~20 lines) receives Telegram messages and fires a `workflow_dispatch` on `ask.yml`, which runs a two-pass Claude query handler and replies via the Telegram Bot API. Email replies to the morning brief are polled every 15 minutes by `reply-check.yml`, classified as action signals or delivery notes, and written to `data/captures.md` or `data/brief_feedback.md` — both of which feed into the next morning brief.

**Tech Stack:** Python 3.11, Anthropic SDK, Google Gmail API (existing auth), Cloudflare Workers (JS), GitHub Actions

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `lib/telegram.py` | Create | `send_message(bot_token, chat_id, text)` |
| `lib/captures.py` | Create | `append_capture`, `load_recent_captures`, `load_brief_feedback` |
| `processors/query.py` | Create | Two-pass query handler: intent → context → answer + captures |
| `processors/feedback.py` | Create | Feedback classifier: action_signal / delivery_note / unclear |
| `ask.py` | Create | Entry point for Telegram query runs |
| `check_replies.py` | Create | Entry point for email reply polling |
| `cloudflare/telegram-bridge.js` | Create | Cloudflare Worker: validate webhook → fire workflow_dispatch |
| `.github/workflows/ask.yml` | Create | workflow_dispatch workflow for queries |
| `.github/workflows/reply-check.yml` | Create | Cron workflow for email reply polling |
| `outputs/sender.py` | Modify | Return `(message_id, thread_id)`, add feedback footer, accept `thread_id` param |
| `main.py` | Modify | Save brief_message_id after send; load captures/feedback context for brief |
| `processors/brief.py` | Modify | Accept and inject `captures_context` and `brief_feedback_context` |
| `config.json` | Modify | Add `captures_file` and `brief_feedback_file` keys |
| `tests/test_telegram.py` | Create | Unit tests for `lib/telegram.py` |
| `tests/test_captures.py` | Create | Unit tests for `lib/captures.py` |
| `tests/test_query.py` | Create | Unit tests for `processors/query.py` |
| `tests/test_feedback.py` | Create | Unit tests for `processors/feedback.py` |
| `tests/test_sender.py` | Modify | Update for new `(message_id, thread_id)` return type |

---

## Task 1: `lib/telegram.py`

**Files:**
- Create: `lib/telegram.py`
- Create: `tests/test_telegram.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram.py
from unittest.mock import patch, MagicMock
from lib.telegram import send_message


def test_send_message_calls_correct_url():
    with patch("lib.telegram.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        send_message("TOKEN123", "CHAT456", "hello world")
    mock_post.assert_called_once_with(
        "https://api.telegram.org/botTOKEN123/sendMessage",
        json={"chat_id": "CHAT456", "text": "hello world"},
        timeout=10,
    )


def test_send_message_raises_on_http_error():
    with patch("lib.telegram.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 403")
        mock_post.return_value = mock_resp
        try:
            send_message("TOKEN123", "CHAT456", "hello")
            assert False, "Should have raised"
        except Exception as e:
            assert "HTTP 403" in str(e)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest tests/test_telegram.py -v
```

Expected: `ImportError: cannot import name 'send_message' from 'lib.telegram'`

- [ ] **Step 3: Create `lib/telegram.py`**

```python
import requests


def send_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    resp.raise_for_status()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_telegram.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add lib/telegram.py tests/test_telegram.py
git commit -m "feat(p4): add telegram send_message wrapper"
```

---

## Task 2: `lib/captures.py`

**Files:**
- Create: `lib/captures.py`
- Create: `tests/test_captures.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_captures.py
import os
import tempfile
from lib.captures import append_capture, load_recent_captures, load_brief_feedback


def test_append_capture_creates_line_with_type_and_content():
    with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
        path = f.name
    try:
        append_capture(path, "todo", "Marcus", "Call back re: contract")
        content = open(path).read()
        assert "[todo]" in content
        assert "Marcus" in content
        assert "Call back re: contract" in content
    finally:
        os.unlink(path)


def test_append_capture_no_target():
    with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
        path = f.name
    try:
        append_capture(path, "idea", None, "Write a blog post")
        content = open(path).read()
        assert "[idea]" in content
        assert "Write a blog post" in content
    finally:
        os.unlink(path)


def test_append_capture_multiple_entries_accumulate():
    with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
        path = f.name
    try:
        append_capture(path, "todo", None, "First capture")
        append_capture(path, "flag", "Apex", "Second capture")
        lines = [l for l in open(path).read().splitlines() if l.strip()]
        assert len(lines) == 2
    finally:
        os.unlink(path)


def test_load_recent_captures_returns_empty_when_file_missing():
    result = load_recent_captures("/tmp/nonexistent_captures_xyz.md")
    assert result == ""


def test_load_brief_feedback_returns_empty_when_file_missing():
    result = load_brief_feedback("/tmp/nonexistent_feedback_xyz.md")
    assert result == ""


def test_load_brief_feedback_truncates_to_token_budget():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        path = f.name
        f.write("x" * 10000)
    try:
        result = load_brief_feedback(path, token_budget=100)
        assert len(result) <= 400 + 50  # 100 tokens * 4 chars + small buffer
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_captures.py -v
```

Expected: `ImportError: cannot import name 'append_capture'`

- [ ] **Step 3: Create `lib/captures.py`**

```python
from datetime import datetime
from typing import Optional
import os


def append_capture(captures_file: str, type_: str, target: Optional[str], content: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    target_str = f" {target} —" if target else ""
    line = f"## {timestamp} — [{type_}]{target_str} {content}\n"
    dir_ = os.path.dirname(captures_file)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    with open(captures_file, "a") as f:
        f.write(line)


def load_recent_captures(captures_file: str, max_chars: int = 2000) -> str:
    if not os.path.exists(captures_file):
        return ""
    try:
        with open(captures_file) as f:
            content = f.read()
        return content[-max_chars:] if len(content) > max_chars else content
    except OSError:
        return ""


def load_brief_feedback(feedback_file: str, token_budget: int = 800) -> str:
    if not os.path.exists(feedback_file):
        return ""
    try:
        with open(feedback_file) as f:
            content = f.read()
        max_chars = token_budget * 4
        return content[-max_chars:] if len(content) > max_chars else content
    except OSError:
        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_captures.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add lib/captures.py tests/test_captures.py
git commit -m "feat(p4): add captures utility (append, load_recent, load_feedback)"
```

---

## Task 3: `processors/query.py`

**Files:**
- Create: `processors/query.py`
- Create: `tests/test_query.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_query.py
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

from processors.query import _load_local_context, answer_query, QueryResult, Capture


def _make_config(tmp_dir: str) -> dict:
    pipeline_cache = os.path.join(tmp_dir, "pipeline_cache.json")
    people_dir = os.path.join(tmp_dir, "people")
    issues_file = os.path.join(tmp_dir, "issues.json")
    captures_file = os.path.join(tmp_dir, "captures.md")
    os.makedirs(people_dir)

    with open(pipeline_cache, "w") as f:
        json.dump({"leads": [{"name": "Apex Fitness", "status": "trial", "contact": "john@apex.com"}]}, f)
    with open(issues_file, "w") as f:
        json.dump([{"title": "Follow up with Marcus", "age_days": 2, "source": "email", "channel": "inbox", "status": "open"}], f)
    with open(os.path.join(people_dir, "marcus.md"), "w") as f:
        f.write("# Marcus\n## Activity\n- Called 2026-04-18\n")

    return {
        "email": "trent@teambuildr.com",
        "pipeline": {"enabled": True, "cache_path": pipeline_cache},
        "people_dir": people_dir,
        "issues_file": issues_file,
        "captures_file": captures_file,
        "calendar_ids": ["primary"],
        "memory": {"enabled": False},
    }


def test_load_local_context_includes_pipeline():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        context = _load_local_context(config)
        assert "Apex Fitness" in context


def test_load_local_context_includes_people():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        context = _load_local_context(config)
        assert "Marcus" in context


def test_load_local_context_includes_issues():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        context = _load_local_context(config)
        assert "Follow up with Marcus" in context


def test_answer_query_returns_query_result():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        intent_resp = MagicMock()
        intent_resp.content = [MagicMock(text='{"needs_live_gmail": false, "needs_live_calendar": false, "gmail_search_query": null, "calendar_date_range": null}')]
        answer_resp = MagicMock()
        answer_resp.content = [MagicMock(text='{"answer": "Apex Fitness is in trial.", "captures": []}')]

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [intent_resp, answer_resp]
            mock_cls.return_value = mock_client
            result = answer_query("fake-key", "claude-sonnet-4-6", "What's the status of Apex?", config)

        assert isinstance(result, QueryResult)
        assert "Apex" in result.answer
        assert result.captures == []


def test_answer_query_extracts_captures():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        intent_resp = MagicMock()
        intent_resp.content = [MagicMock(text='{"needs_live_gmail": false, "needs_live_calendar": false, "gmail_search_query": null, "calendar_date_range": null}')]
        answer_resp = MagicMock()
        answer_resp.content = [MagicMock(text='{"answer": "Done.", "captures": [{"type": "todo", "target": "Marcus", "content": "Call back re: contract"}]}')]

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [intent_resp, answer_resp]
            mock_cls.return_value = mock_client
            result = answer_query("fake-key", "claude-sonnet-4-6", "Remind me to call Marcus about his contract", config)

        assert len(result.captures) == 1
        assert result.captures[0].type == "todo"
        assert result.captures[0].target == "Marcus"
        assert result.captures[0].content == "Call back re: contract"


def test_answer_query_handles_malformed_json_gracefully():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        intent_resp = MagicMock()
        intent_resp.content = [MagicMock(text="not json")]
        answer_resp = MagicMock()
        answer_resp.content = [MagicMock(text="also not json")]

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [intent_resp, answer_resp]
            mock_cls.return_value = mock_client
            result = answer_query("fake-key", "claude-sonnet-4-6", "anything", config)

        assert isinstance(result, QueryResult)
        assert len(result.answer) > 0
        assert result.captures == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_query.py -v
```

Expected: `ImportError: cannot import name '_load_local_context'`

- [ ] **Step 3: Create `processors/query.py`**

```python
from dataclasses import dataclass
from typing import Optional
import json
import os
import anthropic

from processors.memory_retriever import retrieve_memories


@dataclass
class Capture:
    type: str
    target: Optional[str]
    content: str


@dataclass
class QueryResult:
    answer: str
    captures: list[Capture]


def _load_local_context(config: dict) -> str:
    parts = []

    # Pipeline cache
    try:
        with open(config["pipeline"]["cache_path"]) as f:
            cache = json.load(f)
        leads = cache.get("leads", [])
        if leads:
            parts.append("## Pipeline\n" + json.dumps(leads[:20], indent=2))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # People store
    people_dir = config.get("people_dir", "data/people")
    if os.path.isdir(people_dir):
        people_parts = []
        for fname in sorted(os.listdir(people_dir))[:30]:
            if fname.endswith(".md"):
                try:
                    with open(os.path.join(people_dir, fname)) as f:
                        people_parts.append(f.read()[:600])
                except OSError:
                    pass
        if people_parts:
            parts.append("## People\n" + "\n---\n".join(people_parts))

    # Memory (reuse existing retriever)
    memory_cfg = config.get("memory", {})
    if memory_cfg.get("enabled"):
        memory_context = retrieve_memories(
            memory_dir=memory_cfg["dir"],
            token_budget=memory_cfg.get("retrieval_token_budget", 1500),
        )
        if memory_context:
            parts.append(f"## Memory\n{memory_context}")

    # Open issues
    try:
        with open(config["issues_file"]) as f:
            issues = json.load(f)
        if issues:
            parts.append("## Open Issues\n" + json.dumps(issues, indent=2))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Recent captures (last ~2000 chars)
    captures_file = config.get("captures_file", "data/captures.md")
    if os.path.exists(captures_file):
        try:
            content = open(captures_file).read()
            parts.append("## Recent Captures\n" + (content[-2000:] if len(content) > 2000 else content))
        except OSError:
            pass

    return "\n\n".join(parts)


def _classify_intent(client: anthropic.Anthropic, model: str, query: str) -> dict:
    system = """You are a query router for a chief-of-staff AI system.
Given a natural language query, decide whether live Gmail or Calendar data is needed.
Respond with JSON only, no other text.

Available local data (always loaded, no API call needed):
- Pipeline cache (leads, trial status, stale opps)
- People store (contact files with activity history)
- Memory (synthesized patterns and decisions from past briefs)
- Open issues
- Recent action captures

Live data (extra ~15s — fetch only when local data is insufficient):
- Gmail: arbitrary thread search (from:, to:, subject:, date ranges)
- Calendar: dates beyond tomorrow

Return exactly this JSON schema:
{
  "needs_live_gmail": boolean,
  "needs_live_calendar": boolean,
  "gmail_search_query": "gmail search string or null",
  "calendar_date_range": "description like 'next 7 days' or null"
}"""

    try:
        message = client.messages.create(
            model=model,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": f"Query: {query}"}],
        )
        return json.loads(message.content[0].text)
    except (json.JSONDecodeError, IndexError, AttributeError, Exception):
        return {"needs_live_gmail": False, "needs_live_calendar": False,
                "gmail_search_query": None, "calendar_date_range": None}


def _fetch_live_gmail(config: dict, gmail_query: str) -> str:
    from collectors.gmail import fetch_threads_needing_attention
    try:
        threads = fetch_threads_needing_attention(
            user_email=config["email"],
            max_results=10,
            query=gmail_query,
        )
    except Exception:
        return ""
    if not threads:
        return ""
    lines = [f"- [{t.last_sender}] {t.subject} — {t.snippet[:120]}" for t in threads]
    return "## Live Gmail Results\n" + "\n".join(lines)


def _fetch_live_calendar(config: dict, date_range: str) -> str:
    from collectors.calendar import fetch_today_events
    from datetime import date, timedelta

    days = 7
    if date_range:
        for n in ["14", "7", "3"]:
            if n in date_range:
                days = int(n)
                break

    events_text = []
    for i in range(1, days + 1):
        target = date.today() + timedelta(days=i)
        for cal_id in config.get("calendar_ids", ["primary"]):
            try:
                events = fetch_today_events(cal_id, target_date=target, user_email=config["email"])
                for e in events:
                    events_text.append(f"- {target.isoformat()} {e.start.strftime('%H:%M')} {e.summary}")
            except Exception:
                pass

    if not events_text:
        return ""
    return "## Live Calendar Results\n" + "\n".join(events_text)


def answer_query(api_key: str, model: str, query: str, config: dict) -> QueryResult:
    local_context = _load_local_context(config)
    client = anthropic.Anthropic(api_key=api_key)

    intent = _classify_intent(client, model, query)

    context_parts = [local_context]
    if intent.get("needs_live_gmail") and intent.get("gmail_search_query"):
        live_gmail = _fetch_live_gmail(config, intent["gmail_search_query"])
        if live_gmail:
            context_parts.append(live_gmail)
    if intent.get("needs_live_calendar") and intent.get("calendar_date_range"):
        live_cal = _fetch_live_calendar(config, intent["calendar_date_range"])
        if live_cal:
            context_parts.append(live_cal)

    full_context = "\n\n".join(context_parts)

    system = f"""You are Trent's AI Chief of Staff. Answer concisely and directly.
If the query requests an action or capture, include it in the captures list.
Capture types: todo (action item), idea (thought to explore), note (info to remember), flag (priority signal).
Respond with JSON only, no other text.

Schema:
{{
  "answer": "concise reply for Telegram, plain text, 500 chars max",
  "captures": [
    {{"type": "todo|idea|note|flag", "target": "person/company name or null", "content": "what to capture"}}
  ]
}}

Context:
{full_context}"""

    try:
        message = client.messages.create(
            model=model,
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": query}],
        )
        data = json.loads(message.content[0].text)
        captures = [
            Capture(type=c.get("type", "note"), target=c.get("target"), content=c.get("content", ""))
            for c in data.get("captures", [])
        ]
        return QueryResult(answer=data.get("answer", "No answer generated."), captures=captures)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return QueryResult(answer="Sorry, I couldn't parse a response. Try rephrasing.", captures=[])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_query.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add processors/query.py tests/test_query.py
git commit -m "feat(p4): add two-pass query processor"
```

---

## Task 4: `ask.py`

**Files:**
- Create: `ask.py`

No unit test for the entry point itself — the components it calls are already tested. Integration verified manually in Task 8.

- [ ] **Step 1: Create `ask.py`**

```python
#!/usr/bin/env python3
"""Entry point for Telegram query runs. Called by ask.yml workflow."""

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from processors.query import answer_query
from lib.telegram import send_message
from lib.captures import append_capture


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def main() -> None:
    query = os.environ.get("QUERY_TEXT", "").strip()
    chat_id = os.environ.get("QUERY_CHAT_ID", "").strip()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    allowed_chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

    if not query or not chat_id:
        print("ERROR: QUERY_TEXT and QUERY_CHAT_ID must be set.", file=sys.stderr)
        sys.exit(1)

    if allowed_chat_id and chat_id != allowed_chat_id:
        print(f"Rejected: unknown chat_id {chat_id}", file=sys.stderr)
        sys.exit(0)

    config = load_config()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        if bot_token:
            send_message(bot_token, chat_id, "Something went wrong — check Actions logs.")
        sys.exit(1)

    try:
        result = answer_query(api_key=api_key, model=config["ai_model"], query=query, config=config)
    except Exception as e:
        print(f"Query error: {e}", file=sys.stderr)
        if bot_token:
            send_message(bot_token, chat_id, "Something went wrong — check Actions logs.")
        sys.exit(1)

    send_message(bot_token, chat_id, result.answer)

    captures_file = config.get("captures_file", "data/captures.md")
    for capture in result.captures:
        append_capture(captures_file, capture.type, capture.target, capture.content)
        print(f"Captured [{capture.type}]: {capture.content}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
python -c "import ask; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ask.py
git commit -m "feat(p4): add ask.py query entry point"
```

---

## Task 5: `config.json` — add new keys

**Files:**
- Modify: `config.json`

- [ ] **Step 1: Add `captures_file` and `brief_feedback_file` to config.json**

Open `config.json` and add these two keys at the top level (after `"drafts_dir"`):

```json
"captures_file": "data/captures.md",
"brief_feedback_file": "data/brief_feedback.md",
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python -c "import json; json.load(open('config.json')); print('valid')"
```

Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add config.json
git commit -m "feat(p4): add captures_file and brief_feedback_file to config"
```

---

## Task 6: `.github/workflows/ask.yml`

**Files:**
- Create: `.github/workflows/ask.yml`

- [ ] **Step 1: Create `.github/workflows/ask.yml`**

```yaml
name: Ask

on:
  workflow_dispatch:
    inputs:
      query:
        description: "Natural language query"
        required: true
        type: string
      chat_id:
        description: "Telegram chat ID"
        required: true
        type: string

jobs:
  answer:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    env:
      TZ: America/Chicago

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Answer query
        env:
          GOOGLE_OAUTH_JSON: ${{ secrets.GOOGLE_OAUTH_JSON }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ALLOWED_CHAT_ID: ${{ secrets.TELEGRAM_ALLOWED_CHAT_ID }}
          QUERY_TEXT: ${{ inputs.query }}
          QUERY_CHAT_ID: ${{ inputs.chat_id }}
        run: python ask.py

      - name: Persist captures
        run: |
          git config user.name "chief-of-staff[bot]"
          git config user.email "noreply@github.com"
          git add data/
          git diff --cached --quiet || git commit -m "chore: captures $(date +%Y-%m-%d-%H%M)"
          git push
```

- [ ] **Step 2: Verify YAML parses**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ask.yml')); print('valid')" 2>/dev/null || python -c "print('yaml not installed — visually verify indentation is correct')"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ask.yml
git commit -m "feat(p4): add ask.yml workflow_dispatch workflow"
```

---

## Task 7: `cloudflare/telegram-bridge.js`

**Files:**
- Create: `cloudflare/telegram-bridge.js`

- [ ] **Step 1: Create `cloudflare/` directory, `wrangler.toml`, and the worker**

```bash
mkdir -p cloudflare
```

Create `cloudflare/wrangler.toml`:

```toml
name = "chief-of-staff-bot"
main = "telegram-bridge.js"
compatibility_date = "2024-01-01"
```

Create `cloudflare/telegram-bridge.js`:

```javascript
// cloudflare/telegram-bridge.js
export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("OK");

    const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (secret !== env.TELEGRAM_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("OK");
    }

    const message = body?.message;
    if (!message?.text || !message?.chat?.id) return new Response("OK");

    const resp = await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/ask.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_PAT}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "User-Agent": "chief-of-staff-bot",
        },
        body: JSON.stringify({
          ref: "main",
          inputs: {
            query: message.text,
            chat_id: String(message.chat.id),
          },
        }),
      }
    );

    if (!resp.ok) {
      console.error(`GitHub API error: ${resp.status} ${await resp.text()}`);
    }

    return new Response("OK");
  },
};
```

- [ ] **Step 2: Commit**

```bash
git add cloudflare/
git commit -m "feat(p4): add Cloudflare Worker telegram bridge"
```

---

## Task 8: Telegram channel end-to-end setup

This task wires up the live infrastructure. Do it once; everything after is automated.

- [ ] **Step 1: Create a Telegram bot via BotFather**

Open Telegram, search `@BotFather`, send `/newbot`, follow prompts. Copy the bot token.

- [ ] **Step 2: Get your Telegram chat ID**

Message your new bot anything. Then open in a browser:
```
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```
Find `"chat": {"id": 123456789}` — that number is your chat ID.

- [ ] **Step 3: Create a GitHub PAT with actions:write scope**

Go to GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens.
- Repository: `trent-luecke/chief-of-staff`
- Permissions: `Actions: Read and write`

Copy the token.

- [ ] **Step 4: Add GitHub Actions secrets**

Go to the repo → Settings → Secrets and variables → Actions → New repository secret:
- `TELEGRAM_BOT_TOKEN` → your bot token
- `TELEGRAM_ALLOWED_CHAT_ID` → your chat ID (as a string)

- [ ] **Step 5: Deploy the Cloudflare Worker**

```bash
# Install Wrangler if not installed
npm install -g wrangler

# Login
wrangler login

# Deploy from cloudflare/ directory (wrangler.toml is already there)
cd cloudflare
wrangler deploy
```

Note the worker URL from the output (e.g., `https://chief-of-staff-bot.<your-subdomain>.workers.dev`).

- [ ] **Step 6: Set Cloudflare Worker secrets**

```bash
# Still in cloudflare/ directory
wrangler secret put TELEGRAM_SECRET
# Enter a random secret string (e.g., openssl rand -hex 20)

wrangler secret put GITHUB_PAT
# Enter the PAT from Step 3

wrangler secret put GITHUB_REPO
# Enter: trent-luecke/chief-of-staff
```

- [ ] **Step 7: Register the Telegram webhook**

Replace `<BOT_TOKEN>`, `<WORKER_URL>`, and `<TELEGRAM_SECRET>` (same value you set in Step 6):

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "<WORKER_URL>",
    "secret_token": "<TELEGRAM_SECRET>"
  }'
```

Expected response: `{"ok": true, "result": true, "description": "Webhook was set"}`

- [ ] **Step 8: Smoke test the full flow**

Send a message to your bot: `What's in my pipeline right now?`

Go to the repo → Actions tab → watch the `Ask` workflow trigger and complete. You should receive a reply in Telegram within ~60 seconds.

---

## Task 9: `processors/feedback.py`

**Files:**
- Create: `processors/feedback.py`
- Create: `tests/test_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_feedback.py
import os
import tempfile
from unittest.mock import patch, MagicMock

from processors.feedback import classify_feedback, append_brief_feedback, FeedbackResult


def test_classify_feedback_action_signal():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"classification": "action_signal", "capture_type": "flag", "capture_target": "Apex", "capture_content": "elevate in tomorrow brief", "delivery_note": null, "clarification_question": null}')]

    with patch("processors.feedback.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_cls.return_value = mock_client
        result = classify_feedback("fake-key", "claude-sonnet-4-6", "Elevate Apex", "Morning Brief — Monday")

    assert result.classification == "action_signal"
    assert result.capture_type == "flag"
    assert result.capture_target == "Apex"
    assert result.capture_content == "elevate in tomorrow brief"


def test_classify_feedback_delivery_note():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"classification": "delivery_note", "capture_type": null, "capture_target": null, "capture_content": null, "delivery_note": "Cut gym scout section unless 3+ leads", "clarification_question": null}')]

    with patch("processors.feedback.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_cls.return_value = mock_client
        result = classify_feedback("fake-key", "claude-sonnet-4-6", "Too much gym stuff", "Morning Brief")

    assert result.classification == "delivery_note"
    assert result.delivery_note == "Cut gym scout section unless 3+ leads"
    assert result.capture_content is None


def test_classify_feedback_unclear():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"classification": "unclear", "capture_type": null, "capture_target": null, "capture_content": null, "delivery_note": null, "clarification_question": "What would you like me to do?"}')]

    with patch("processors.feedback.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_cls.return_value = mock_client
        result = classify_feedback("fake-key", "claude-sonnet-4-6", "hmm", "Morning Brief")

    assert result.classification == "unclear"
    assert result.clarification_question is not None


def test_classify_feedback_handles_malformed_json():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="not json")]

    with patch("processors.feedback.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_cls.return_value = mock_client
        result = classify_feedback("fake-key", "claude-sonnet-4-6", "anything", "Brief")

    assert result.classification == "unclear"
    assert result.clarification_question is not None


def test_append_brief_feedback_writes_timestamped_line():
    with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
        path = f.name
    try:
        append_brief_feedback(path, "Cut gym scout section unless 3+ leads")
        content = open(path).read()
        assert "Cut gym scout section" in content
        assert "##" in content
    finally:
        os.unlink(path)


def test_append_brief_feedback_accumulates():
    with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
        path = f.name
    try:
        append_brief_feedback(path, "First note")
        append_brief_feedback(path, "Second note")
        lines = [l for l in open(path).read().splitlines() if l.strip()]
        assert len(lines) == 2
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_feedback.py -v
```

Expected: `ImportError: cannot import name 'classify_feedback'`

- [ ] **Step 3: Create `processors/feedback.py`**

```python
from dataclasses import dataclass
from typing import Literal, Optional
import json
import os
from datetime import datetime
import anthropic


@dataclass
class FeedbackResult:
    classification: Literal["action_signal", "delivery_note", "unclear"]
    capture_type: Optional[str]
    capture_target: Optional[str]
    capture_content: Optional[str]
    delivery_note: Optional[str]
    clarification_question: Optional[str]


def classify_feedback(api_key: str, model: str, reply_body: str, brief_subject: str) -> FeedbackResult:
    client = anthropic.Anthropic(api_key=api_key)
    system = """You classify email replies to a morning brief as feedback.

Three categories:
- action_signal: reactive instruction about something in the brief ("ignore that email", "elevate Apex", "flag Marcus as urgent")
- delivery_note: instruction about how future briefs should be formatted or prioritized ("executive summary too long", "cut gym scout section")
- unclear: can't determine intent

Respond with JSON only, no other text.

Schema:
{
  "classification": "action_signal|delivery_note|unclear",
  "capture_type": "flag|todo|note|idea or null",
  "capture_target": "person/company name or null",
  "capture_content": "what the action is or null",
  "delivery_note": "the tuning instruction in clear imperative form or null",
  "clarification_question": "what to ask the user if unclear, or null"
}"""

    try:
        message = client.messages.create(
            model=model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": f"Brief subject: {brief_subject}\n\nReply: {reply_body}"}],
        )
        data = json.loads(message.content[0].text)
        return FeedbackResult(
            classification=data.get("classification", "unclear"),
            capture_type=data.get("capture_type"),
            capture_target=data.get("capture_target"),
            capture_content=data.get("capture_content"),
            delivery_note=data.get("delivery_note"),
            clarification_question=data.get("clarification_question"),
        )
    except (json.JSONDecodeError, IndexError, AttributeError, Exception):
        return FeedbackResult(
            classification="unclear",
            capture_type=None,
            capture_target=None,
            capture_content=None,
            delivery_note=None,
            clarification_question="Sorry, I couldn't parse your feedback. Could you rephrase?",
        )


def append_brief_feedback(feedback_file: str, note: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d")
    line = f"## {timestamp} — {note}\n"
    dir_ = os.path.dirname(feedback_file)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    with open(feedback_file, "a") as f:
        f.write(line)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_feedback.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add processors/feedback.py tests/test_feedback.py
git commit -m "feat(p4): add feedback classifier and brief_feedback writer"
```

---

## Task 10: `outputs/sender.py` — return thread_id, add footer, support thread reply

**Files:**
- Modify: `outputs/sender.py`
- Modify: `tests/test_sender.py`

- [ ] **Step 1: Update `tests/test_sender.py` to reflect new return type**

In `tests/test_sender.py`, change the existing `test_send_brief_email_calls_gmail_api` test:

Old mock and assertion:
```python
mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "msg_001"}
...
assert result == "msg_001"
```

New mock and assertion:
```python
mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "msg_001", "threadId": "thread_001"}
...
msg_id, thread_id = result
assert msg_id == "msg_001"
assert thread_id == "thread_001"
```

Also update `test_send_brief_email_encodes_html` — it doesn't assert on the return value, so no change needed there. But the call to `send_brief_email` needs no change since we're not using the return value in that test.

Add a new test after the existing ones:

```python
def test_send_brief_email_uses_thread_id_when_provided(mock_gmail_service):
    mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "msg_003", "threadId": "thread_003"}
    send_brief_email(
        gmail_service=mock_gmail_service,
        to_email="trent@teambuildr.com",
        subject="Re: Morning Brief",
        html_body="<p>Got it.</p>",
        thread_id="thread_003",
    )
    call_args = mock_gmail_service.users().messages().send.call_args
    body = call_args.kwargs.get("body") or (call_args.args[0] if call_args.args else call_args.kwargs["body"])
    assert body.get("threadId") == "thread_003"


def test_build_html_email_contains_feedback_footer():
    html = build_html_email(
        brief=make_brief(),
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        template_dir="templates",
    )
    assert "Reply to this email" in html
```

- [ ] **Step 2: Run updated tests to confirm they now fail**

```bash
python -m pytest tests/test_sender.py -v
```

Expected: `test_send_brief_email_calls_gmail_api` FAILS (return type mismatch), `test_send_brief_email_uses_thread_id_when_provided` FAILS, `test_build_html_email_contains_feedback_footer` FAILS

- [ ] **Step 3: Update `outputs/sender.py`**

Replace the `build_html_email` function — add footer to the rendered HTML:

```python
def build_html_email(
    brief: BriefContent,
    today_events: list[CalendarEvent],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    template_dir: str = "templates",
) -> str:
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("morning_brief.html")
    now = datetime.now()
    html = template.render(
        brief=brief,
        today_events=today_events,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        date_str=now.strftime("%A, %B ") + str(now.day),
        generated_at=now.strftime("%I:%M %p").lstrip("0"),
    )
    footer = (
        '<hr style="margin-top: 40px; border: none; border-top: 1px solid #eee;">'
        '<p style="font-size: 12px; color: #999; margin-top: 16px;">'
        "Reply to this email to give feedback on this brief."
        "</p>"
    )
    return html + footer
```

Replace the `send_brief_email` function — return `(message_id, thread_id)` and accept optional `thread_id`:

```python
def send_brief_email(
    gmail_service,
    to_email: str,
    subject: str,
    html_body: str,
    plain_text: str = "Morning brief — view in an HTML-capable email client.",
    thread_id: str = None,
) -> tuple[str, str]:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = to_email
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body: dict = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    result = gmail_service.users().messages().send(userId="me", body=body).execute()
    return result.get("id", ""), result.get("threadId", "")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_sender.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add outputs/sender.py tests/test_sender.py
git commit -m "feat(p4): sender returns thread_id, add feedback footer, support thread reply"
```

---

## Task 11: `main.py` — save brief_message_id and inject captures/feedback context

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add `_save_brief_message_id` helper and import**

After the `load_config` function in `main.py` (around line 38), add:

```python
def _save_brief_message_id(config: dict, message_id: str, thread_id: str, subject: str) -> None:
    state_path = os.path.join(config["state_dir"], "brief_message_id.json")
    os.makedirs(config["state_dir"], exist_ok=True)
    with open(state_path, "w") as f:
        json.dump({
            "message_id": message_id,
            "thread_id": thread_id,
            "subject": subject,
            "date": date.today().isoformat(),
            "processed_reply_ids": [],
        }, f)
```

- [ ] **Step 2: Update the send block in `run()` to unpack the new return value**

Find this block in `run()` (around line 260):

```python
        print("📤  Sending brief email...")
        gmail = build_gmail_service(config["email"])
        subject = f"☀️ Morning Brief — {datetime.now().strftime('%A, %B %-d')}"
        html = build_html_email(brief, today_events, projects, due_tasks, loop_summary)
        msg_id = send_brief_email(gmail, config["email"], subject, html)
        print(f"   Sent: {msg_id}")
```

Replace with:

```python
        print("📤  Sending brief email...")
        gmail = build_gmail_service(config["email"])
        subject = f"☀️ Morning Brief — {datetime.now().strftime('%A, %B %-d')}"
        html = build_html_email(brief, today_events, projects, due_tasks, loop_summary)
        msg_id, thread_id = send_brief_email(gmail, config["email"], subject, html)
        print(f"   Sent: {msg_id}")
        _save_brief_message_id(config, msg_id, thread_id, subject)
```

- [ ] **Step 3: Add imports for `load_recent_captures` and `load_brief_feedback` at the top of `main.py`**

After the existing imports, add:

```python
from lib.captures import load_recent_captures, load_brief_feedback
```

- [ ] **Step 4: Load captures and feedback context in `run()` before the brief generation call**

Find the `print("🤖  Generating brief with Claude...")` line (around line 211). Just before it, add:

```python
    captures_context = load_recent_captures(config.get("captures_file", "data/captures.md"))
    brief_feedback_context = load_brief_feedback(config.get("brief_feedback_file", "data/brief_feedback.md"))
```

- [ ] **Step 5: Pass the new params to `generate_brief()`**

In the `generate_brief(...)` call, add two new keyword arguments at the end (before the closing `)`) :

```python
            captures_context=captures_context,
            brief_feedback_context=brief_feedback_context,
```

- [ ] **Step 6: Verify the app still runs locally**

```bash
python main.py --dry-run --no-email 2>&1 | head -30
```

Expected: runs without error, prints section headers, exits cleanly.

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat(p4): save brief_message_id after send; inject captures/feedback into brief"
```

---

## Task 12: `processors/brief.py` — inject captures and brief_feedback context

**Files:**
- Modify: `processors/brief.py`

- [ ] **Step 1: Add `captures_context` and `brief_feedback_context` params to `_build_prompt`**

In `_build_prompt`, add two parameters after `memory_context: str = ""`:

```python
    captures_context: str = "",
    brief_feedback_context: str = "",
```

Then in the `sections` list, add these blocks. Brief feedback goes at the very top (before memory — it's a delivery instruction). Captures go after the inbox section (they're captured action items).

After the `sections = []` line, before the `if memory_context:` block, add:

```python
    if brief_feedback_context:
        sections += [
            "## Delivery Instructions (from your feedback — follow these when writing the brief)",
            brief_feedback_context,
            "",
        ]
```

After the `"## Quick Capture Inbox..."` section in the `sections` list, add:

```python
        "",
        "## Action Captures (logged via Telegram query channel — surface relevant items)",
        captures_context if captures_context else "  (none)",
```

- [ ] **Step 2: Add `captures_context` and `brief_feedback_context` params to `generate_brief`**

In the `generate_brief` function signature, add after `memory_context: str = ""`:

```python
    captures_context: str = "",
    brief_feedback_context: str = "",
```

In the `_build_prompt(...)` call inside `generate_brief`, add at the end:

```python
        captures_context=captures_context,
        brief_feedback_context=brief_feedback_context,
```

- [ ] **Step 3: Run existing brief tests to verify nothing broke**

```bash
python -m pytest tests/test_brief.py tests/test_brief_extended.py -v
```

Expected: all existing tests pass

- [ ] **Step 4: Commit**

```bash
git add processors/brief.py
git commit -m "feat(p4): inject captures and brief_feedback context into brief prompt"
```

---

## Task 13: `check_replies.py`

**Files:**
- Create: `check_replies.py`

- [ ] **Step 1: Create `check_replies.py`**

```python
#!/usr/bin/env python3
"""Entry point for email reply polling. Called by reply-check.yml workflow."""

import json
import os
import sys
from datetime import date

from dotenv import load_dotenv
load_dotenv()

from lib.google_auth import build_gmail_service
from processors.feedback import classify_feedback, append_brief_feedback
from lib.captures import append_capture
from outputs.sender import send_brief_email


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_brief_state(state_dir: str) -> dict | None:
    path = os.path.join(state_dir, "brief_message_id.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_brief_state(state_dir: str, state: dict) -> None:
    path = os.path.join(state_dir, "brief_message_id.json")
    with open(path, "w") as f:
        json.dump(state, f)


def main() -> None:
    config = load_config()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    user_email = config["email"]

    state = load_brief_state(config["state_dir"])
    if not state:
        print("No brief state found — skipping reply check.")
        return

    if state.get("date") != date.today().isoformat():
        print(f"Brief state is from {state.get('date')} — skipping.")
        return

    thread_id = state.get("thread_id")
    if not thread_id:
        print("No thread_id in brief state — skipping.")
        return

    gmail = build_gmail_service(user_email)

    try:
        thread_data = gmail.users().threads().get(
            userId="me", id=thread_id, format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()
    except Exception as e:
        print(f"WARNING: Could not fetch brief thread: {e}", file=sys.stderr)
        return

    messages = thread_data.get("messages", [])
    brief_msg_id = state.get("message_id")
    processed_ids = set(state.get("processed_reply_ids", []))

    # Find replies: messages after the original brief, from user_email, not yet processed
    replies = []
    found_original = False
    for msg in messages:
        if msg["id"] == brief_msg_id:
            found_original = True
            continue
        if found_original and msg["id"] not in processed_ids:
            headers = msg.get("payload", {}).get("headers", [])
            from_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
            if user_email.lower() in from_header.lower():
                replies.append(msg)

    if not replies:
        print("No new replies found.")
        return

    brief_subject = state.get("subject", "Morning Brief")
    captures_file = config.get("captures_file", "data/captures.md")
    feedback_file = config.get("brief_feedback_file", "data/brief_feedback.md")

    for reply in replies:
        snippet = reply.get("snippet", "")
        print(f"Processing reply: {snippet[:80]}...")

        result = classify_feedback(
            api_key=api_key,
            model=config["ai_model"],
            reply_body=snippet,
            brief_subject=brief_subject,
        )

        if result.classification == "action_signal" and result.capture_content:
            append_capture(captures_file, result.capture_type or "flag",
                           result.capture_target, result.capture_content)
            ack = f"Got it — logged as [{result.capture_type or 'flag'}]: {result.capture_content}"
        elif result.classification == "delivery_note" and result.delivery_note:
            append_brief_feedback(feedback_file, result.delivery_note)
            ack = f"Got it — noted for future briefs: {result.delivery_note}"
        else:
            ack = result.clarification_question or "Received — could you clarify what you'd like me to do?"

        try:
            _, _ = send_brief_email(
                gmail_service=gmail,
                to_email=user_email,
                subject=f"Re: {brief_subject}",
                html_body=f"<p>{ack}</p>",
                thread_id=thread_id,
            )
            print(f"Acknowledged: {ack}")
        except Exception as e:
            print(f"WARNING: Could not send acknowledgment: {e}", file=sys.stderr)

        processed_ids.add(reply["id"])

    state["processed_reply_ids"] = list(processed_ids)
    save_brief_state(config["state_dir"], state)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
python -c "import check_replies; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add check_replies.py
git commit -m "feat(p4): add check_replies.py email reply poller"
```

---

## Task 14: `.github/workflows/reply-check.yml`

**Files:**
- Create: `.github/workflows/reply-check.yml`

- [ ] **Step 1: Create `.github/workflows/reply-check.yml`**

```yaml
name: Check Email Replies

on:
  schedule:
    # Every 15 minutes, Mon-Fri, 8am-5pm CDT (UTC-5).
    # Change to "*/15 14-23 * * 1-5" in November for CST (UTC-6).
    - cron: "*/15 13-22 * * 1-5"
  workflow_dispatch:

jobs:
  check-replies:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    env:
      TZ: America/Chicago

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Check for email replies
        env:
          GOOGLE_OAUTH_JSON: ${{ secrets.GOOGLE_OAUTH_JSON }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python check_replies.py

      - name: Persist data
        run: |
          git config user.name "chief-of-staff[bot]"
          git config user.email "noreply@github.com"
          git add data/
          git diff --cached --quiet || git commit -m "chore: feedback $(date +%Y-%m-%d-%H%M)"
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/reply-check.yml
git commit -m "feat(p4): add reply-check.yml cron workflow"
```

---

## Task 15: Full test suite and final verification

- [ ] **Step 1: Run the full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_watcher.py 2>&1 | tail -30
```

(Ignore `test_watcher.py` — it has a known stale API issue documented in the backlog.)

Expected: all other tests pass

- [ ] **Step 2: Dry-run `main.py` end-to-end**

```bash
python main.py --dry-run --no-email
```

Expected: completes without error, prints `✅ Brief complete.`

- [ ] **Step 3: Dry-run `check_replies.py`**

```bash
python check_replies.py
```

Expected: either `No brief state found — skipping reply check.` or `Brief state is from <date> — skipping.` — no errors.

- [ ] **Step 4: Final commit**

```bash
git add -A
git diff --cached --quiet || git commit -m "feat(p4): complete two-way interface implementation"
```

---

## Secrets Reference

| Location | Secret | Value |
|---|---|---|
| GitHub Actions | `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| GitHub Actions | `TELEGRAM_ALLOWED_CHAT_ID` | Your Telegram chat ID (string) |
| Cloudflare Worker | `TELEGRAM_SECRET` | Random hex string (set at webhook registration) |
| Cloudflare Worker | `GITHUB_PAT` | Fine-grained PAT with `Actions: Read and write` on this repo |
| Cloudflare Worker | `GITHUB_REPO` | `trent-luecke/chief-of-staff` |
