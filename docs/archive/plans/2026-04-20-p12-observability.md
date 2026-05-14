# P12 Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument every Claude API call to log per-call token usage and estimated cost to a local JSONL file, surfaced as a weekly cost line in the synthesis prompt.

**Architecture:** A module-level accumulator (`lib/llm_logger.py`) collects call data in-process. Each entry point wraps its main logic in `try/finally` to flush accumulated calls to `data/logs/run_log.jsonl` — even on failure. The weekly synthesizer reads the last 7 days of log entries and prepends a cost summary to the synthesis prompt.

**Tech Stack:** Python standard library (`json`, `os`, `datetime`); existing Anthropic SDK `response.usage` object; pytest + `tmp_path` for tests.

---

### Task 1: `lib/llm_logger.py` + `tests/test_llm_logger.py`

**Files:**
- Create: `lib/llm_logger.py`
- Create: `tests/test_llm_logger.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_logger.py`:

```python
import json
import sys
from datetime import date

import pytest


def setup_function():
    from lib import llm_logger
    llm_logger.reset()


def teardown_function():
    from lib import llm_logger
    llm_logger.reset()


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def test_log_usage_accumulates_calls():
    from lib import llm_logger
    llm_logger.log_usage("brief", FakeUsage(), "claude-sonnet-4-6")
    llm_logger.log_usage("people", FakeUsage(), "claude-sonnet-4-6")
    assert len(llm_logger._calls) == 2


def test_log_usage_calculates_cost_correctly():
    from lib import llm_logger
    # Sonnet: $3.00/M input, $15.00/M output
    # 1000 input + 200 output = 1000*3/1_000_000 + 200*15/1_000_000 = 0.003 + 0.003 = 0.006
    llm_logger.log_usage("brief", FakeUsage(input_tokens=1000, output_tokens=200), "claude-sonnet-4-6")
    assert len(llm_logger._calls) == 1
    assert abs(llm_logger._calls[0]["estimated_cost_usd"] - 0.006) < 1e-9


def test_log_usage_unknown_model_zero_cost():
    from lib import llm_logger
    llm_logger.log_usage("brief", FakeUsage(), "claude-unknown-99")
    assert llm_logger._calls[0]["estimated_cost_usd"] == 0.0


def test_flush_writes_jsonl(tmp_path):
    from lib import llm_logger
    log_file = str(tmp_path / "run_log.jsonl")
    llm_logger.log_usage("brief", FakeUsage(input_tokens=500, output_tokens=100), "claude-sonnet-4-6")
    llm_logger.flush("daily_brief", log_file)
    with open(log_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) == 1
    entry = lines[0]
    assert entry["run_type"] == "daily_brief"
    assert entry["caller"] == "brief"
    assert entry["model"] == "claude-sonnet-4-6"
    assert entry["input_tokens"] == 500
    assert entry["output_tokens"] == 100
    assert "timestamp" in entry
    assert "estimated_cost_usd" in entry


def test_flush_clears_accumulator(tmp_path):
    from lib import llm_logger
    log_file = str(tmp_path / "run_log.jsonl")
    llm_logger.log_usage("brief", FakeUsage(), "claude-sonnet-4-6")
    llm_logger.flush("daily_brief", log_file)
    assert llm_logger._calls == []


def test_flush_non_fatal_on_bad_path():
    from lib import llm_logger
    llm_logger.log_usage("brief", FakeUsage(), "claude-sonnet-4-6")
    # Should not raise even though the directory doesn't exist and can't be created
    llm_logger.flush("daily_brief", "/nonexistent/dir/run_log.jsonl")


def test_reset_clears_calls():
    from lib import llm_logger
    llm_logger.log_usage("brief", FakeUsage(), "claude-sonnet-4-6")
    assert len(llm_logger._calls) == 1
    llm_logger.reset()
    assert llm_logger._calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest tests/test_llm_logger.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'lib.llm_logger'`

- [ ] **Step 3: Implement `lib/llm_logger.py`**

```python
import json
import os
import sys
from datetime import datetime, timezone

MODEL_PRICING = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
}

_calls: list[dict] = []


def log_usage(caller: str, usage, model: str) -> None:
    try:
        pricing = MODEL_PRICING.get(model)
        if pricing is None:
            print(f"WARNING: unknown model '{model}' — cost logged as 0.0", file=sys.stderr)
            cost = 0.0
        else:
            cost = (
                usage.input_tokens * pricing["input"]
                + usage.output_tokens * pricing["output"]
            ) / 1_000_000
        _calls.append({
            "caller": caller,
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "estimated_cost_usd": round(cost, 6),
        })
    except Exception:
        pass


def flush(run_type: str, log_file: str) -> None:
    global _calls
    snapshot = list(_calls)
    _calls = []
    if not snapshot:
        return
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log_file, "a", encoding="utf-8") as f:
            for call in snapshot:
                entry = {"timestamp": timestamp, "run_type": run_type, **call}
                f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"WARNING: llm_logger flush failed: {e}", file=sys.stderr)


def reset() -> None:
    global _calls
    _calls = []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_llm_logger.py -v
```

Expected: 7 tests pass, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add lib/llm_logger.py tests/test_llm_logger.py
git commit -m "feat(p12): add llm_logger module with accumulator and flush"
```

---

### Task 2: `_load_week_costs` + weekly synthesizer integration

**Files:**
- Modify: `processors/weekly_synthesizer.py` — add `_load_week_costs`, update `_build_prompt`, update `synthesize_week`
- Modify: `tests/test_weekly_synthesizer.py` — add 3 tests

- [ ] **Step 1: Write the 3 failing tests**

Append to `tests/test_weekly_synthesizer.py`:

```python
def test_load_week_costs_sums_7_days(tmp_path):
    import json
    from datetime import date
    from processors.weekly_synthesizer import _load_week_costs

    log_file = tmp_path / "run_log.jsonl"
    run_date = date(2026, 4, 20)
    entries = [
        {"timestamp": "2026-04-12T07:00:00Z", "estimated_cost_usd": 0.01},  # day 8 — excluded
        {"timestamp": "2026-04-13T07:00:00Z", "estimated_cost_usd": 0.02},  # day 7 — included
        {"timestamp": "2026-04-18T07:00:00Z", "estimated_cost_usd": 0.03},  # included
        {"timestamp": "2026-04-20T07:00:00Z", "estimated_cost_usd": 0.04},  # run_date — included
    ]
    with open(log_file, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    result = _load_week_costs(str(log_file), run_date)
    assert result["call_count"] == 3
    assert abs(result["total_cost_usd"] - 0.09) < 1e-6


def test_load_week_costs_missing_file(tmp_path):
    from datetime import date
    from processors.weekly_synthesizer import _load_week_costs

    result = _load_week_costs(str(tmp_path / "nonexistent.jsonl"), date(2026, 4, 20))
    assert result == {"call_count": 0, "total_cost_usd": 0.0}


def test_load_week_costs_corrupt_lines(tmp_path):
    import json
    from datetime import date
    from processors.weekly_synthesizer import _load_week_costs

    log_file = tmp_path / "run_log.jsonl"
    with open(log_file, "w") as f:
        f.write("not json at all\n")
        f.write(json.dumps({"timestamp": "2026-04-20T07:00:00Z", "estimated_cost_usd": 0.05}) + "\n")
        f.write("{corrupt\n")

    result = _load_week_costs(str(log_file), date(2026, 4, 20))
    assert result["call_count"] == 1
    assert abs(result["total_cost_usd"] - 0.05) < 1e-6
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python -m pytest tests/test_weekly_synthesizer.py::test_load_week_costs_sums_7_days tests/test_weekly_synthesizer.py::test_load_week_costs_missing_file tests/test_weekly_synthesizer.py::test_load_week_costs_corrupt_lines -v
```

Expected: `ImportError` or `AttributeError` — `_load_week_costs` doesn't exist yet.

- [ ] **Step 3: Add `_load_week_costs` to `processors/weekly_synthesizer.py`**

Add after `_load_week_state_delta` (after line 52):

```python
def _load_week_costs(log_file: str, run_date: date) -> dict:
    cutoff = run_date - timedelta(days=7)
    call_count = 0
    total_cost = 0.0
    try:
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_date = date.fromisoformat(entry.get("timestamp", "")[:10])
                    if cutoff <= entry_date <= run_date:
                        call_count += 1
                        total_cost += entry.get("estimated_cost_usd", 0.0)
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    return {"call_count": call_count, "total_cost_usd": round(total_cost, 6)}
```

- [ ] **Step 4: Run new tests to verify they pass**

```bash
python -m pytest tests/test_weekly_synthesizer.py::test_load_week_costs_sums_7_days tests/test_weekly_synthesizer.py::test_load_week_costs_missing_file tests/test_weekly_synthesizer.py::test_load_week_costs_corrupt_lines -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Update `_build_prompt` to accept `costs` parameter**

Change the `_build_prompt` signature and add the cost line at the top. Replace the current `_build_prompt` function signature:

```python
def _build_prompt(
    observations: list[dict],
    resolved_count: int,
    still_open_count: int,
    open_issue_titles: list[str],
    captures_text: str,
    run_date: date,
    costs: dict | None = None,
) -> str:
```

In `_build_prompt`, replace the `lines = [...]` initialization block:

```python
    lines = []

    if costs and costs.get("call_count", 0) > 0:
        lines += [
            f"**This week:** {costs['call_count']} Claude calls, ~${costs['total_cost_usd']:.2f}",
            "",
        ]

    lines += [
        f"## Week of {week_start} → {week_end}",
        "",
        f"**Email threads resolved: {resolved_count}**",
        f"**Email threads still open: {still_open_count}**",
        "",
    ]
```

- [ ] **Step 6: Update `synthesize_week` signature and call site**

Add `log_file: str | None = None` parameter to `synthesize_week`:

```python
def synthesize_week(
    api_key: str,
    model: str,
    obs_file: str,
    state_dir: str,
    issues_file: str,
    captures_file: str,
    run_date: date | None = None,
    log_file: str | None = None,
) -> WeeklySynthesis:
```

Add cost loading before `_build_prompt`, and pass `costs` to it. After the existing `captures_text = load_recent_captures(...)` line, add:

```python
    costs = _load_week_costs(log_file, run_date) if log_file else None
```

Update the `_build_prompt` call to pass `costs`:

```python
    prompt = _build_prompt(
        observations=observations,
        resolved_count=resolved_count,
        still_open_count=still_open_count,
        open_issue_titles=open_issue_titles,
        captures_text=captures_text,
        run_date=run_date,
        costs=costs,
    )
```

- [ ] **Step 7: Run all weekly synthesizer tests**

```bash
python -m pytest tests/test_weekly_synthesizer.py -v
```

Expected: all tests pass (including the 3 new ones and all pre-existing tests).

- [ ] **Step 8: Commit**

```bash
git add processors/weekly_synthesizer.py tests/test_weekly_synthesizer.py
git commit -m "feat(p12): add _load_week_costs and inject cost summary into weekly synthesis prompt"
```

---

### Task 3: Instrument the 8 processor call sites

**Files:**
- Modify: `processors/brief.py`
- Modify: `processors/weekly_synthesizer.py`
- Modify: `processors/people.py`
- Modify: `processors/drafts.py`
- Modify: `processors/memory_synthesizer.py`
- Modify: `processors/query.py` (2 call sites)
- Modify: `processors/feedback.py`

One-liner pattern: immediately after each `client.messages.create()` (or `response = ...`), add:

```python
from lib.llm_logger import log_usage
log_usage("caller_name", response.usage, model)
```

- [ ] **Step 1: Instrument `processors/brief.py`**

In `generate_brief`, after `response = client.messages.create(...)` (line ~194), add:

```python
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    from lib.llm_logger import log_usage
    log_usage("brief", response.usage, model)
    raw = response.content[0].text.strip()
```

- [ ] **Step 2: Instrument `processors/weekly_synthesizer.py`**

In `synthesize_week`, after `response = client.messages.create(...)` (line ~149), add:

```python
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    from lib.llm_logger import log_usage
    log_usage("weekly_synthesizer", response.usage, model)
    raw = response.content[0].text.strip()
```

- [ ] **Step 3: Instrument `processors/people.py`**

In `enrich_people` (inside the `try:` block), after `response = client.messages.create(...)` (line ~169):

```python
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        from lib.llm_logger import log_usage
        log_usage("people", response.usage, model)
        raw = response.content[0].text.strip()
```

- [ ] **Step 4: Instrument `processors/drafts.py`**

In `_call_claude`, after `response = client.messages.create(...)` (line ~23):

```python
def _call_claude(api_key: str, model: str, prompt: str, max_tokens: int = 500) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    from lib.llm_logger import log_usage
    log_usage("drafts", response.usage, model)
    return response.content[0].text.strip()
```

- [ ] **Step 5: Instrument `processors/memory_synthesizer.py`**

In `synthesize`, after `response = client.messages.create(...)` (line ~118):

```python
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    from lib.llm_logger import log_usage
    log_usage("memory_synthesizer", response.usage, model)
    raw = response.content[0].text.strip()
```

- [ ] **Step 6: Instrument `processors/query.py` — classify call**

In the classify section (line ~117), after `message = client.messages.create(...)`:

```python
        message = client.messages.create(
            model=model,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": f"Query: {query}"}],
        )
        from lib.llm_logger import log_usage
        log_usage("query_classify", message.usage, model)
        raw = message.content[0].text.strip()
```

- [ ] **Step 7: Instrument `processors/query.py` — answer call**

In the answer section (line ~213), after `message = client.messages.create(...)`:

```python
        message = client.messages.create(
            model=model,
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": query}],
        )
        from lib.llm_logger import log_usage
        log_usage("query_answer", message.usage, model)
        raw = message.content[0].text.strip()
```

- [ ] **Step 8: Instrument `processors/feedback.py`**

In `classify_feedback` (line ~42), after `message = client.messages.create(...)`:

```python
        message = client.messages.create(
            model=model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": f"Brief subject: {brief_subject}\n\nReply: {reply_body}"}],
        )
        from lib.llm_logger import log_usage
        log_usage("feedback", message.usage, model)
        raw = message.content[0].text.strip()
```

- [ ] **Step 9: Verify existing test suites still pass**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pre-existing tests pass. No new tests needed for the one-liner additions.

- [ ] **Step 10: Commit**

```bash
git add processors/brief.py processors/weekly_synthesizer.py processors/people.py processors/drafts.py processors/memory_synthesizer.py processors/query.py processors/feedback.py
git commit -m "feat(p12): instrument all 8 Claude call sites with log_usage"
```

---

### Task 4: Wire entry points, config, and data/logs/

**Files:**
- Modify: `main.py` — try/finally flush in `run()`
- Modify: `weekly_synthesis.py` — try/finally flush + pass `log_file` to `synthesize_week`
- Modify: `ask.py` — try/finally flush
- Modify: `check_replies.py` — try/finally flush
- Modify: `config.json` — add `logs_file` key
- Create: `data/logs/.gitkeep`

- [ ] **Step 1: Add `logs_file` to `config.json` and create `data/logs/.gitkeep`**

In `config.json`, add the key before the closing brace:

```json
{
  ...existing keys...,
  "logs_file": "data/logs/run_log.jsonl"
}
```

Create the gitkeep:

```bash
mkdir -p /Users/trentluecke/dev/Claude-Projects/chief-of-staff/data/logs
touch /Users/trentluecke/dev/Claude-Projects/chief-of-staff/data/logs/.gitkeep
```

- [ ] **Step 2: Wire `main.py` — wrap `run()` body in try/finally**

At the top of `run()` (line ~97), add the import and try block. Wrap the entire body of `run()` in `try/finally`:

```python
def run(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    from lib.llm_logger import flush
    try:
        print("🗓  Fetching calendar...")
        # ... all existing code unchanged ...
    finally:
        flush("daily_brief", config.get("logs_file", "data/logs/run_log.jsonl"))
```

The final `print("\n✅ Brief complete.")` block and everything before it stays inside the `try:`. Only the `finally:` block is new.

- [ ] **Step 3: Wire `weekly_synthesis.py` — try/finally + pass `log_file`**

Wrap the body of `main()` after `api_key` validation in try/finally, and pass `log_file` to `synthesize_week`:

```python
def main() -> None:
    config = load_config()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    from lib.llm_logger import flush
    run_date = date.today()
    memory_cfg = config.get("memory", {})

    try:
        print("Generating weekly synthesis...")
        try:
            synthesis = synthesize_week(
                api_key=api_key,
                model=config["ai_model"],
                obs_file=memory_cfg.get("observations_file", "data/memory/observations.jsonl"),
                state_dir=config["state_dir"],
                issues_file=config["issues_file"],
                captures_file=config.get("captures_file", "data/captures.md"),
                run_date=run_date,
                log_file=config.get("logs_file"),
            )
        except Exception as e:
            print(f"ERROR: synthesis failed: {e}", file=sys.stderr)
            sys.exit(1)

        _save_synthesis(synthesis, "data/weekly", run_date)

        gmail = build_gmail_service(config["email"])
        subject = f"📊 Weekly Synthesis — week ending {run_date.isoformat()}"
        html = _render_html(synthesis, run_date.isoformat())

        try:
            msg_id, _ = send_brief_email(
                gmail_service=gmail,
                to_email=config["email"],
                subject=subject,
                html_body=html,
                plain_text="Weekly synthesis — view in an HTML-capable email client.",
            )
            print(f"Sent: {msg_id}")
        except Exception as e:
            print(f"WARNING: could not send email: {e}", file=sys.stderr)

        print(f"\nSummary: {synthesis.executive_summary}")
        if synthesis.carry_forwards:
            print("\nCarry-Forwards:")
            for item in synthesis.carry_forwards:
                print(f"  → {item}")
    finally:
        flush("weekly_synthesis", config.get("logs_file", "data/logs/run_log.jsonl"))
```

- [ ] **Step 4: Wire `ask.py` — try/finally around logic after config load**

```python
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

    from lib.llm_logger import flush
    try:
        try:
            result = answer_query(api_key=api_key, model=config["ai_model"], query=query, config=config)
        except Exception as e:
            print(f"Query error: {e}", file=sys.stderr)
            if bot_token:
                send_message(bot_token, chat_id, "Something went wrong — check Actions logs.")
            sys.exit(1)

        if bot_token:
            send_message(bot_token, chat_id, result.answer)

        captures_file = config.get("captures_file", "data/captures.md")
        projects_file = config.get("projects_file", "data/projects.md")
        for capture in result.captures:
            if capture.type == "complete":
                hit_capture = complete_capture(captures_file, capture.content)
                hit_project = complete_project_next(projects_file, capture.content)
                print(f"Completed: {capture.content} (captures={hit_capture}, projects={hit_project})")
            else:
                append_capture(captures_file, capture.type, capture.target, capture.content)
                print(f"Captured [{capture.type}]: {capture.content}")
    finally:
        flush("telegram_query", config.get("logs_file", "data/logs/run_log.jsonl"))
```

- [ ] **Step 5: Wire `check_replies.py` — try/finally around the reply-processing body**

In `check_replies.py:main()`, the function early-returns for "no state" and "stale date" cases — those happen before any Claude calls, so no flush needed there. The `classify_feedback` call happens inside the `for reply in replies:` loop. Wrap from after the `if not replies: ... return` block to the end of `main()`:

```python
def main() -> None:
    config = load_config()
    # ... existing setup code (load state, build gmail, fetch thread, find replies) ...

    if not replies:
        print("No new replies found.")
        if processed_ids != set(state.get("processed_reply_ids", [])):
            state["processed_reply_ids"] = list(processed_ids)
            save_brief_state(config["state_dir"], state)
        return

    brief_subject = state.get("subject", "Morning Brief")
    captures_file = config.get("captures_file", "data/captures.md")
    feedback_file = config.get("brief_feedback_file", "data/brief_feedback.md")

    from lib.llm_logger import flush
    try:
        for reply in replies:
            snippet = reply.get("snippet", "")
            reply_body = _get_message_body(gmail, reply["id"], snippet)
            print(f"Processing reply: {reply_body[:80]}...")

            result = classify_feedback(
                api_key=api_key,
                model=config["ai_model"],
                reply_body=reply_body,
                brief_subject=brief_subject,
            )

            # ... rest of existing reply processing loop (ack, save state) unchanged ...
    finally:
        flush("email_reply", config.get("logs_file", "data/logs/run_log.jsonl"))
```

- [ ] **Step 6: Verify all tests still pass**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add main.py weekly_synthesis.py ask.py check_replies.py config.json data/logs/.gitkeep
git commit -m "feat(p12): wire try/finally flush to all 4 entry points and add logs_file to config"
```

---

### Task 5: Mark P12 complete in BACKLOG.md

**Files:**
- Modify: `BACKLOG.md`

- [ ] **Step 1: Update the P12 section**

Replace the current P12 entry with:

```markdown
## ✅ P12 — Observability (complete)

**Shipped 2026-04-20.** Per-call Claude API usage logged to `data/logs/run_log.jsonl` as JSONL. Each entry captures timestamp, run_type, caller, model, input_tokens, output_tokens, and estimated_cost_usd. All 8 Claude call sites instrumented via `lib/llm_logger.log_usage()`. All 4 entry points flush via try/finally. Weekly synthesis reads the 7-day window and prepends a cost summary line to the synthesis prompt. Langfuse skipped — local log is sufficient.
```

- [ ] **Step 2: Commit**

```bash
git add BACKLOG.md
git commit -m "docs: mark P12 observability complete in backlog"
```

---

## Self-Review

**Spec coverage:**
- `lib/llm_logger.py` with `log_usage`, `flush`, `reset` → Task 1 ✅
- Pricing constants for 3 models → Task 1 ✅
- Unknown model → 0.0 cost + warning → Task 1 ✅
- 10 tests (7 in `test_llm_logger.py`, 3 in `test_weekly_synthesizer.py`) → Tasks 1+2 ✅
- 8 call sites instrumented → Task 3 ✅
- 4 entry points with try/finally flush → Task 4 ✅
- `config.json` `logs_file` key → Task 4 ✅
- `data/logs/.gitkeep` → Task 4 ✅
- `_load_week_costs` in weekly synthesizer → Task 2 ✅
- `log_file` param on `synthesize_week` → Task 2 ✅
- `costs` param on `_build_prompt`, cost line prepended → Task 2 ✅
- `weekly_synthesis.py` passes `config["logs_file"]` → Task 4 ✅

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:** `_load_week_costs` returns `dict` matching the `costs: dict | None = None` parameter in `_build_prompt`. `flush` clears `_calls` (snapshot pattern avoids race between clear and write error). `log_file: str | None = None` in `synthesize_week` matches the `if log_file:` guard.
