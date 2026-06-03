# Slack Task Slash Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up a `/task <title> [due:<date>]` Slack slash command that adds tasks to `data/tasks.jsonl` via Cloudflare Worker → GitHub Actions, and makes the Registry UI auto-push to git after each task mutation.

**Architecture:** The Cloudflare Worker gains a `/slack/task` path handler that verifies Slack's HMAC signature, acknowledges immediately, then dispatches `task_add.yml` via GitHub Actions with title and response_url. A new Python script adds the task and posts a confirmation back to Slack. The Flask server wraps task mutations in a git commit+push using the existing `_git_push_projects` pattern.

**Tech Stack:** Cloudflare Workers (JS, Web Crypto API), GitHub Actions, Python 3.11, `dateparser`, Flask

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `requirements.txt` | Modify | Add `dateparser>=1.2.0` |
| `scripts/__init__.py` | Create | Empty — makes scripts/ importable as package |
| `scripts/slack_add_task.py` | Create | parse_due_date, format_confirmation, post_to_slack, main |
| `tests/test_slack_add_task.py` | Create | Tests for parse_due_date and format_confirmation |
| `.github/workflows/task_add.yml` | Create | Workflow: checkout → install → run script → git push |
| `cloudflare/telegram-bridge.js` | Rewrite | Path-based routing; new handleSlackTask function |
| `tools/server.py` | Modify | Add _git_push_tasks(); wire into update_task and complete_task |
| `.github/workflows/ask.yml` | Modify | Fix stale `data/tasks.json` → `data/tasks.jsonl` on line 60 |

---

## Task 1: Write failing tests for slack_add_task helpers

**Files:**
- Create: `tests/test_slack_add_task.py`

- [ ] **Step 1: Create the test file**

```python
# tests/test_slack_add_task.py
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.slack_add_task import format_confirmation, parse_due_date


def test_parse_due_date_empty_returns_none():
    assert parse_due_date("") is None


def test_parse_due_date_whitespace_returns_none():
    assert parse_due_date("   ") is None


def test_parse_due_date_garbage_returns_none():
    assert parse_due_date("zzzzgarbage12345") is None


def test_parse_due_date_iso_passthrough():
    assert parse_due_date("2026-12-31") == "2026-12-31"


def test_parse_due_date_natural_language_returns_iso():
    result = parse_due_date("next monday")
    assert result is not None
    assert re.match(r"\d{4}-\d{2}-\d{2}", result)


def test_format_confirmation_no_date():
    assert format_confirmation("Follow up with Acme", None) == "Task added: Follow up with Acme"


def test_format_confirmation_with_date():
    result = format_confirmation("Follow up with Acme", "2026-06-06")
    assert result == "Task added: Follow up with Acme — due 2026-06-06"
```

- [ ] **Step 2: Run — confirm ImportError (module doesn't exist yet)**

```bash
pytest tests/test_slack_add_task.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'scripts.slack_add_task'`

---

## Task 2: Add dateparser and implement slack_add_task.py

**Files:**
- Modify: `requirements.txt`
- Create: `scripts/__init__.py`
- Create: `scripts/slack_add_task.py`

- [ ] **Step 1: Add dateparser to requirements.txt**

Add after line 8 (`python-dateutil>=2.8.2`):

```
dateparser>=1.2.0
```

- [ ] **Step 2: Install updated dependencies**

```bash
pip install -r requirements.txt 2>&1 | tail -5
```

Expected: `Successfully installed dateparser-...` (or already satisfied)

- [ ] **Step 3: Create scripts/__init__.py**

Create an empty file at `scripts/__init__.py`. No content needed — just makes the directory a Python package.

- [ ] **Step 4: Create scripts/slack_add_task.py**

```python
#!/usr/bin/env python3
"""Add a task from a Slack slash command. Called by task_add.yml."""
import json
import os
import sys
import urllib.request
from pathlib import Path

import dateparser

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.storage import LocalStorage
from lib.tasks import add_task


def parse_due_date(raw: str):
    """Parse natural language date to YYYY-MM-DD. Returns None if empty or unparseable."""
    if not raw or not raw.strip():
        return None
    result = dateparser.parse(
        raw,
        settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
    )
    if result is None:
        return None
    return result.strftime("%Y-%m-%d")


def format_confirmation(title: str, due_date) -> str:
    if due_date:
        return f"Task added: {title} — due {due_date}"
    return f"Task added: {title}"


def post_to_slack(response_url: str, text: str) -> None:
    if not response_url:
        return
    payload = json.dumps({"response_type": "ephemeral", "text": text}).encode()
    req = urllib.request.Request(
        response_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Warning: failed to post to Slack response_url: {e}", file=sys.stderr)


def main():
    title = os.environ.get("TASK_TITLE", "").strip()
    response_url = os.environ.get("RESPONSE_URL", "")
    due_date_raw = os.environ.get("DUE_DATE_RAW", "")

    if not title:
        print("Error: TASK_TITLE is required", file=sys.stderr)
        sys.exit(1)

    storage = LocalStorage(base_dir=str(ROOT / "data"))
    due_date = parse_due_date(due_date_raw)
    add_task(storage, title=title, source="slack", due_date=due_date)
    post_to_slack(response_url, format_confirmation(title, due_date))
    print(f"Task added: {title}" + (f" (due {due_date})" if due_date else ""))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests — confirm all pass**

```bash
pytest tests/test_slack_add_task.py -v
```

Expected output:
```
tests/test_slack_add_task.py::test_parse_due_date_empty_returns_none PASSED
tests/test_slack_add_task.py::test_parse_due_date_whitespace_returns_none PASSED
tests/test_slack_add_task.py::test_parse_due_date_garbage_returns_none PASSED
tests/test_slack_add_task.py::test_parse_due_date_iso_passthrough PASSED
tests/test_slack_add_task.py::test_parse_due_date_natural_language_returns_iso PASSED
tests/test_slack_add_task.py::test_format_confirmation_no_date PASSED
tests/test_slack_add_task.py::test_format_confirmation_with_date PASSED
7 passed
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt scripts/__init__.py scripts/slack_add_task.py tests/test_slack_add_task.py
git commit -m "feat: add slack_add_task script with date parsing"
```

---

## Task 3: Create task_add.yml workflow

**Files:**
- Create: `.github/workflows/task_add.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
# .github/workflows/task_add.yml
name: Add Task from Slack

on:
  workflow_dispatch:
    inputs:
      title:
        description: "Task title"
        required: true
      response_url:
        description: "Slack response_url for posting confirmation"
        required: false
        default: ""
      due_date_raw:
        description: "Raw due date string (e.g. 'friday', 'next tuesday')"
        required: false
        default: ""

permissions:
  contents: write

jobs:
  add-task:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Add task
        env:
          TASK_TITLE: ${{ inputs.title }}
          RESPONSE_URL: ${{ inputs.response_url }}
          DUE_DATE_RAW: ${{ inputs.due_date_raw }}
        run: python scripts/slack_add_task.py

      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/tasks.jsonl
          git diff --staged --quiet || git commit -m "chore: add task from slack [skip ci]"
          git push origin main || true
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/task_add.yml
git commit -m "feat: add task_add GitHub Actions workflow"
```

---

## Task 4: Update Cloudflare Worker with Slack route

**Files:**
- Rewrite: `cloudflare/telegram-bridge.js`

The refactor: `dispatchToGitHub` is generalized to accept `inputs` and `workflow` directly, allowing both Telegram and Slack to reuse it. A path check routes `/slack/task` to the new handler before the existing Telegram logic.

- [ ] **Step 1: Rewrite telegram-bridge.js**

Replace the entire file with:

```javascript
// cloudflare/telegram-bridge.js

async function dispatchToGitHub(env, workflow, inputs) {
  const resp = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "chief-of-staff-bot",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    }
  );
  if (!resp.ok) {
    console.error(`GitHub API error: ${resp.status} ${await resp.text()}`);
  }
}

async function handleSlackTask(request, env, ctx) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp");
  const signature = request.headers.get("X-Slack-Signature");

  if (!timestamp || !signature) {
    return new Response("Unauthorized", { status: 401 });
  }

  // Reject requests older than 5 minutes (replay attack prevention)
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp, 10)) > 300) {
    return new Response("Unauthorized", { status: 401 });
  }

  const rawBody = await request.text();
  const sigBase = `v0:${timestamp}:${rawBody}`;
  const encoder = new TextEncoder();

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(env.SLACK_SIGNING_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, encoder.encode(sigBase));
  const expected =
    "v0=" +
    Array.from(new Uint8Array(mac))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");

  if (expected !== signature) {
    return new Response("Unauthorized", { status: 401 });
  }

  const params = new URLSearchParams(rawBody);
  const text = (params.get("text") || "").trim();
  const responseUrl = params.get("response_url") || "";

  if (!text) {
    return Response.json({
      response_type: "ephemeral",
      text: "Usage: /task <title> [due:<date>]",
    });
  }

  const dueMatch = text.match(/\bdue:(\S+)/i);
  const dueDateRaw = dueMatch ? dueMatch[1] : "";
  const title = text.replace(/\bdue:\S+/i, "").trim();

  if (!title) {
    return Response.json({
      response_type: "ephemeral",
      text: "Usage: /task <title> [due:<date>]",
    });
  }

  ctx.waitUntil(
    dispatchToGitHub(env, "task_add.yml", {
      title,
      response_url: responseUrl,
      due_date_raw: dueDateRaw,
    })
  );

  return Response.json({
    response_type: "ephemeral",
    text: "Adding task...",
  });
}

export default {
  // ctx (ExecutionContext) lets us use ctx.waitUntil() to fire GitHub dispatch
  // after returning OK, so Telegram/Slack don't retry on slow GitHub responses.
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("OK");

    const url = new URL(request.url);

    if (url.pathname === "/slack/task") {
      return handleSlackTask(request, env, ctx);
    }

    // Telegram path
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

    console.log(
      `Telegram message received: "${message.text}" from chat ${message.chat.id}`
    );

    const inputs = {
      query: message.text,
      chat_id: String(message.chat.id),
    };
    const replyToId = message.reply_to_message?.message_id;
    if (replyToId) inputs.reply_to_message_id = String(replyToId);

    ctx.waitUntil(dispatchToGitHub(env, "ask.yml", inputs));
    return new Response("OK");
  },
};
```

- [ ] **Step 2: Commit**

```bash
git add cloudflare/telegram-bridge.js
git commit -m "feat: add /slack/task route to Cloudflare Worker"
```

---

## Task 5: Add git push to Registry UI task mutations

**Files:**
- Modify: `tools/server.py:65-79` (update_task and complete_task endpoints)

- [ ] **Step 1: Add _git_push_tasks() after the existing _git_push_projects() function (after line 107)**

Insert this block after line 107 (the closing `}` of `_git_push_projects`):

```python
def _git_push_tasks(detail: str) -> dict:
    """Stage, commit, and push tasks.jsonl. Returns status dict."""
    try:
        repo = str(ROOT)
        subprocess.run(
            ["git", "add", "data/tasks.jsonl"],
            cwd=repo, check=True, capture_output=True,
        )
        commit = subprocess.run(
            ["git", "commit", "-m", f"data: {detail}"],
            cwd=repo, capture_output=True, text=True,
        )
        if commit.returncode != 0:
            out = (commit.stdout + commit.stderr).strip()
            if "nothing to commit" in out:
                return {"status": "ok", "detail": "already committed"}
            return {"status": "commit_failed", "detail": out}
        push = subprocess.run(
            ["git", "push"],
            cwd=repo, capture_output=True, text=True,
        )
        if push.returncode != 0:
            return {"status": "push_failed", "detail": push.stderr.strip()}
        return {"status": "ok", "detail": "committed and pushed"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
```

- [ ] **Step 2: Update update_task endpoint (lines 65-71) to call _git_push_tasks**

Replace the current `update_task` function body:

```python
@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id: str):
    patch = request.get_json(force=True)
    result = tasks_lib.edit_task(_storage(), task_id, patch)
    if result is None:
        return jsonify({"error": "not found"}), 404
    push = _git_push_tasks(f"update task {task_id}")
    if push["status"] != "ok":
        return jsonify({"error": f"git push failed: {push['detail']}"}), 500
    return jsonify(result)
```

- [ ] **Step 3: Update complete_task endpoint (lines 74-79) to call _git_push_tasks**

Replace the current `complete_task` function body:

```python
@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id: str):
    result = tasks_lib.complete_task_by_id(_storage(), task_id)
    if result is None:
        return jsonify({"error": "not found"}), 404
    push = _git_push_tasks(f"complete task {task_id}")
    if push["status"] != "ok":
        return jsonify({"error": f"git push failed: {push['detail']}"}), 500
    return jsonify(result)
```

- [ ] **Step 4: Smoke-test the server locally**

```bash
python tools/server.py &
sleep 2
# List tasks (should return JSON array)
curl -s http://localhost:8787/api/tasks | python3 -m json.tool | head -20
# Kill server
kill %1
```

Expected: JSON array of open tasks with no errors.

- [ ] **Step 5: Commit**

```bash
git add tools/server.py
git commit -m "feat: auto git push after task mutations in registry UI"
```

---

## Task 6: Fix stale tasks.json reference in ask.yml

**Files:**
- Modify: `.github/workflows/ask.yml:60`

- [ ] **Step 1: Update the git add line**

On line 60 of `.github/workflows/ask.yml`, replace:

```
git add data/notion_updates_queue.json data/brief_prefs.md data/pending_change.json data/people/ data/projects.md data/tasks.json 2>/dev/null || true
```

with:

```
git add data/notion_updates_queue.json data/brief_prefs.md data/pending_change.json data/people/ data/projects.md data/tasks.jsonl 2>/dev/null || true
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ask.yml
git commit -m "fix: commit tasks.jsonl (not stale tasks.json) in ask.yml"
```

---

## Task 7: Deploy Worker and configure Slack app

These steps are manual/deployment — no code changes.

- [ ] **Step 1: Add SLACK_SIGNING_SECRET to Cloudflare Worker**

Find your Slack signing secret: api.slack.com/apps → your app → Basic Information → App Credentials → Signing Secret

```bash
cd cloudflare
wrangler secret put SLACK_SIGNING_SECRET
# Paste the signing secret when prompted
```

- [ ] **Step 2: Deploy the updated Worker**

```bash
cd cloudflare
wrangler deploy
```

Expected: `Deployed chief-of-staff-bot ... https://chief-of-staff-bot.trent-4a1.workers.dev`

- [ ] **Step 3: Verify Telegram still works**

Send a test message to your Telegram bot. It should respond normally — confirms the Telegram path was not broken by the refactor.

- [ ] **Step 4: Configure the Slack slash command**

1. api.slack.com/apps → your app → **Slash Commands** → Create New Command
2. Set:
   - Command: `/task`
   - Request URL: `https://chief-of-staff-bot.trent-4a1.workers.dev/slack/task`
   - Short Description: `Add a task`
   - Usage Hint: `<title> [due:<date>]`
3. Save → **Reinstall to Workspace** (required after adding slash commands)

- [ ] **Step 5: End-to-end test**

In any Slack channel or DM:

```
/task Test task from slash command
```

Expected sequence:
1. Immediate ephemeral: `Adding task...`
2. ~45 seconds later, second ephemeral: `Task added: Test task from slash command`
3. Check `data/tasks.jsonl` in the repo — new entry with `"source": "slack"`

Then test with a due date:

```
/task Follow up with Acme due:friday
```

Expected final message: `Task added: Follow up with Acme — due 2026-06-06` (or the upcoming Friday's date)

- [ ] **Step 6: Test Registry UI git push**

```bash
python tools/server.py &
sleep 2
# Get a task ID from the task list
TASK_ID=$(curl -s http://localhost:8787/api/tasks | python3 -c "import sys,json; tasks=json.load(sys.stdin); print(tasks[0]['id'] if tasks else '')")
echo "Testing with task: $TASK_ID"
# Complete it
curl -s -X POST http://localhost:8787/api/tasks/$TASK_ID/complete | python3 -m json.tool
kill %1
```

Expected: JSON response with the completed task, and `git log --oneline -1` shows `data: complete task <id>`.
