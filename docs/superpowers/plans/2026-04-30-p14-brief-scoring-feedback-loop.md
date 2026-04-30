# P14 — Brief scoring and retrieval feedback loop

**Date:** 2026-04-30  
**Status:** Draft  
**Parent:** `docs/superpowers/specs/2026-04-30-p14-retrieval-logging-spec.md`

---

## Problem

The retrieval logging spec captures what the system did. But without feedback on whether the output was actually useful, the logs are just data — there's no signal to learn from. And if auditing requires you to remember to open JSONL files and cross-reference them manually, it won't happen. The system needs to push insights to you, not wait for you to pull them.

Two pieces:

1. A `/brief score` Telegram command that takes five seconds after reading the morning brief
2. A weekly retrieval digest that lands in Telegram (or email) every Sunday alongside the weekly synthesis, summarizing score trends and surfacing recurring problems

---

## Part 1: `/brief score` command

### User interface

From Telegram, after reading the morning brief:

```
/brief score 4
```

With an optional note:

```
/brief score 2 missed the Apex contract deadline completely
```

Response from the bot:

```
Logged: 4/5 for today's brief.
```

or with note:

```
Logged: 2/5 for today's brief.
Note: missed the Apex contract deadline completely
```

Invalid input:

```
/brief score 7
```

Response:

```
Score must be 1-5. Usage: /brief score 3 [optional note]
```

### Data format

Append one line to `data/state/brief_scores.jsonl`:

```json
{
  "date": "2026-05-01",
  "score": 2,
  "note": "missed the Apex contract deadline completely",
  "timestamp": "2026-05-01T12:45:00Z"
}
```

If scored multiple times in one day, each score is appended (not overwritten). The analysis layer uses the last score for that date. This avoids needing upsert logic while still letting you change your mind.

### Implementation

**The routing happens in `ask.py`, not the Cloudflare worker.** Every Telegram message already flows through `ask.py` via the GitHub Actions workflow. Add a command parser at the top of `_main_inner` that intercepts `/brief score` before it reaches the Claude query path.

New file: `processors/brief_scorer.py`

```python
"""Handle /brief score commands and manage brief_scores.jsonl."""

import json
import os
import re
from datetime import date, datetime, timezone
from typing import Optional


SCORE_PATTERN = re.compile(
    r"^/brief\s+score\s+(\d+)(?:\s+(.+))?$", re.IGNORECASE
)

SCORES_FILE = "data/state/brief_scores.jsonl"


def parse_score_command(text: str) -> Optional[tuple[int, Optional[str]]]:
    """Parse a /brief score command. Returns (score, note) or None if not a score command."""
    match = SCORE_PATTERN.match(text.strip())
    if not match:
        return None
    score = int(match.group(1))
    note = match.group(2).strip() if match.group(2) else None
    return score, note


def save_score(
    score: int,
    note: Optional[str] = None,
    scores_file: str = SCORES_FILE,
    score_date: Optional[str] = None,
) -> None:
    """Append a score entry to the JSONL file."""
    entry = {
        "date": score_date or date.today().isoformat(),
        "score": score,
        "note": note,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(scores_file) or ".", exist_ok=True)
    with open(scores_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def handle_score_command(text: str, scores_file: str = SCORES_FILE) -> Optional[str]:
    """Process a /brief score command. Returns response text, or None if not a score command."""
    parsed = parse_score_command(text)
    if parsed is None:
        return None

    score, note = parsed

    if score < 1 or score > 5:
        return "Score must be 1-5. Usage: /brief score 3 [optional note]"

    save_score(score, note, scores_file)

    response = f"Logged: {score}/5 for today's brief."
    if note:
        response += f"\nNote: {note}"
    return response
```

**Modification to `ask.py`:** in `_main_inner`, before the Claude query call:

```python
from processors.brief_scorer import handle_score_command

def _main_inner(query: str, chat_id: str, bot_token: str, config: dict) -> None:
    # Check for /brief score command first
    score_response = handle_score_command(query)
    if score_response is not None:
        if bot_token:
            send_message(bot_token, chat_id, score_response)
        return

    # ... existing query logic continues unchanged
```

This means `/brief score` never hits Claude, never costs an API call, and responds in under a second (just a file append and a Telegram message).

### Config

Add to `config.json`:

```json
"brief_scores_file": "data/state/brief_scores.jsonl"
```

Pass this through to `handle_score_command` and the analysis functions instead of hardcoding the path.

### Tests

```python
# tests/test_brief_scorer.py

from processors.brief_scorer import parse_score_command, handle_score_command, save_score
import json
import os


def test_parse_valid_score():
    assert parse_score_command("/brief score 4") == (4, None)


def test_parse_score_with_note():
    score, note = parse_score_command("/brief score 2 missed Apex deadline")
    assert score == 2
    assert note == "missed Apex deadline"


def test_parse_not_a_score_command():
    assert parse_score_command("what's on my calendar?") is None
    assert parse_score_command("/brief") is None
    assert parse_score_command("/brief something else") is None


def test_parse_case_insensitive():
    assert parse_score_command("/Brief Score 3") == (3, None)


def test_handle_valid_score(tmp_path):
    scores_file = str(tmp_path / "scores.jsonl")
    response = handle_score_command("/brief score 4", scores_file=scores_file)
    assert "4/5" in response
    with open(scores_file) as f:
        entry = json.loads(f.readline())
    assert entry["score"] == 4
    assert entry["note"] is None


def test_handle_score_with_note(tmp_path):
    scores_file = str(tmp_path / "scores.jsonl")
    response = handle_score_command("/brief score 2 missed Apex", scores_file=scores_file)
    assert "2/5" in response
    assert "missed Apex" in response
    with open(scores_file) as f:
        entry = json.loads(f.readline())
    assert entry["note"] == "missed Apex"


def test_handle_out_of_range(tmp_path):
    scores_file = str(tmp_path / "scores.jsonl")
    response = handle_score_command("/brief score 7", scores_file=scores_file)
    assert "must be 1-5" in response
    assert not os.path.exists(scores_file)


def test_handle_not_a_command():
    assert handle_score_command("what's on my calendar?") is None
```

---

## Part 2: Weekly retrieval digest

### What it is

A Sunday message (Telegram, alongside the weekly synthesis) that reads the past week's brief scores and retrieval logs, runs a Claude analysis call, and sends you a short summary. You don't have to open any files or remember to audit anything. It arrives, you read it, done.

### What it contains

The digest has four sections:

**Score summary.** Running average for the week, trend vs. prior week (improving / stable / declining), and a sparkline-style representation of the 7 daily scores.

Example:
```
Brief scores this week: 3 4 4 2 5 4 3
Average: 3.6 (last week: 3.1, ↑ improving)
```

**Low-score diagnosis.** For any day that scored 2 or below, Claude reads the retrieval log for that day and the score note, then writes one sentence explaining what likely went wrong. This is the actionable part — it connects your gut reaction ("missed Apex") to a specific retrieval failure mode.

Example:
```
Wednesday (2/5): "missed Apex deadline" — retrieval log shows no Apex-related 
vectors in top-20 results. Calendar had no Apex events that day, so the query 
string had no Apex signals to match against. Likely fix: add deal names from 
pipeline cache to query construction even when no calendar event exists.
```

**Recurring patterns.** If the same note keyword or failure mode appears across multiple low-scoring days (across weeks, not just this one), call it out. "Apex" showing up in 3 of the last 10 low-score notes means the system consistently misses that deal.

Example:
```
Recurring: "pipeline" or deal names appear in 4 of your last 8 low-score notes. 
The query construction may be under-weighting pipeline signals relative to 
calendar and email.
```

**Suggested tuning.** Based on the score patterns and retrieval logs, Claude proposes one concrete config change. Not a list of five recommendations — one. The most impactful thing to try next week.

Example:
```
Suggested change: increase observation_budget_pct from 0.4 to 0.5. 
Three of four low-score days had relevant observations that were excluded 
due to budget exhaustion while memory results with lower scores were included.
```

### Implementation

New file: `processors/retrieval_digest.py`

This function reads both JSONL files, builds a prompt with the raw data, calls Claude, and returns a structured digest.

```python
"""Weekly retrieval digest: analyze brief scores + retrieval logs."""

import json
import os
from datetime import date, timedelta
from typing import Optional

import anthropic


def load_scores(scores_file: str, since: date) -> list[dict]:
    """Load scores from since date onward. Uses last score per day."""
    daily = {}
    try:
        with open(scores_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                entry_date = date.fromisoformat(entry["date"])
                if entry_date >= since:
                    daily[entry["date"]] = entry  # last write wins
    except FileNotFoundError:
        pass
    return sorted(daily.values(), key=lambda e: e["date"])


def load_retrieval_logs(log_file: str, since: date) -> list[dict]:
    """Load retrieval log entries from since date onward, brief trigger only."""
    entries = []
    try:
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                entry_date = date.fromisoformat(entry["date"])
                if entry_date >= since and entry.get("trigger") == "brief":
                    entries.append(entry)
    except FileNotFoundError:
        pass
    return entries


def load_all_scores(scores_file: str) -> list[dict]:
    """Load all historical scores for recurring pattern detection."""
    scores = []
    try:
        with open(scores_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                scores.append(json.loads(line))
    except FileNotFoundError:
        pass
    return scores


def build_digest_prompt(
    this_week_scores: list[dict],
    this_week_logs: list[dict],
    all_scores: list[dict],
    config_snapshot: dict,
) -> str:
    """Build the Claude prompt for digest analysis."""
    prompt_parts = [
        "You are analyzing the performance of a morning brief retrieval system.",
        "The system uses vector search (Pinecone + Voyage AI) to find relevant context",
        "for a daily email brief. The user scores each brief 1-5 after reading it.",
        "",
        "Your job: analyze the scores and retrieval logs for this week, identify",
        "what went wrong on low-scoring days, find recurring patterns across all",
        "historical scores, and suggest ONE concrete config change.",
        "",
        "Be direct and specific. No preamble. No hedging.",
        "",
        "## This week's scores",
        json.dumps(this_week_scores, indent=2),
        "",
        "## This week's retrieval logs",
        json.dumps(this_week_logs, indent=2),
        "",
        "## All historical scores (for pattern detection)",
        json.dumps(all_scores, indent=2),
        "",
        "## Current retrieval config",
        json.dumps(config_snapshot, indent=2),
        "",
        "Respond with exactly four sections, using these headers:",
        "",
        "SCORE SUMMARY",
        "Show the daily scores, this week's average, last week's average, trend.",
        "",
        "LOW-SCORE DIAGNOSIS",
        "For each day scoring 2 or below: one sentence connecting the user's note",
        "to a specific finding in the retrieval log (what was missing, what was",
        "noise, what was excluded and why). If there are no low scores, say so.",
        "",
        "RECURRING PATTERNS",
        "Look at ALL historical scores. Are the same keywords, entities, or failure",
        "modes showing up repeatedly? Call them out. If the history is too short",
        "to detect patterns, say so.",
        "",
        "SUGGESTED CHANGE",
        "Propose exactly ONE config change for next week. Reference the specific",
        "evidence from the logs. Include the current value and proposed new value.",
        "If no change is warranted, say 'Hold steady — not enough data yet' and",
        "explain why.",
    ]
    return "\n".join(prompt_parts)


def generate_digest(
    api_key: str,
    model: str,
    scores_file: str,
    retrieval_log_file: str,
    config_snapshot: dict,
    run_date: Optional[date] = None,
) -> str:
    """Generate the weekly retrieval digest via Claude. Returns formatted text."""
    run_date = run_date or date.today()
    week_start = run_date - timedelta(days=6)

    this_week_scores = load_scores(scores_file, since=week_start)
    this_week_logs = load_retrieval_logs(retrieval_log_file, since=week_start)
    all_scores = load_all_scores(scores_file)

    if not this_week_scores:
        return (
            "No brief scores recorded this week. "
            "Score your briefs with: /brief score [1-5] [optional note]"
        )

    prompt = build_digest_prompt(
        this_week_scores, this_week_logs, all_scores, config_snapshot
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text
```

### Delivery

**Option A: Add to the weekly synthesis workflow.**

The weekly synthesis already runs Sunday at noon CDT. Add the retrieval digest as a second step in `weekly_synthesis.py` (or a separate function called from the same entry point). Send it as a Telegram message so it's separate from the email synthesis.

In `weekly_synthesis.py`, after the synthesis email is sent:

```python
# Retrieval digest — sent via Telegram
from processors.retrieval_digest import generate_digest

vector_cfg = config.get("vector", {})
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

if bot_token and chat_id:
    try:
        digest = generate_digest(
            api_key=api_key,
            model=config["ai_model"],
            scores_file=config.get("brief_scores_file", "data/state/brief_scores.jsonl"),
            retrieval_log_file=vector_cfg.get("retrieval_log_file", "data/state/retrieval_log.jsonl"),
            config_snapshot={
                "retrieval_mode": vector_cfg.get("retrieval_mode", "auto"),
                "top_k": vector_cfg.get("top_k", 20),
                "memory_budget_pct": vector_cfg.get("memory_budget_pct", 0.6),
                "observation_budget_pct": vector_cfg.get("observation_budget_pct", 0.4),
                "score_threshold": vector_cfg.get("score_threshold"),
            },
        )
        header = f"📊 Retrieval Digest — week ending {run_date.isoformat()}\n\n"
        send_message(bot_token, chat_id, header + digest)
        print("Retrieval digest sent via Telegram.")
    except Exception as e:
        print(f"WARNING: retrieval digest failed: {e}", file=sys.stderr)
```

This requires adding `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_ID` to the `weekly.yml` workflow env.

**Option B: Separate workflow on its own schedule.**

If you'd rather decouple it from the weekly synthesis (so it can run on a different day or cadence), create a `retrieval_digest.yml` workflow and a `run_digest.py` entry point. Same structure as `weekly_synthesis.py` but simpler.

I'd recommend Option A for now — one fewer workflow to maintain, and Sunday is the natural day to review how the past week went.

### GitHub Actions changes for Option A

Add to `weekly.yml` env section:

```yaml
TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
TELEGRAM_ALLOWED_CHAT_ID: ${{ secrets.TELEGRAM_ALLOWED_CHAT_ID }}
```

These secrets already exist (used by `ask.yml`), so no new secrets needed.

---

## What the first few weeks look like

**Week 1:** You score briefs daily. The Sunday digest says "Not enough data for pattern detection yet. Hold steady." That's fine — it's still useful because it shows you the score summary and any low-score diagnoses.

**Week 2:** The digest can now compare this week vs. last week. Trend line starts. Recurring patterns are still thin.

**Week 3+:** Pattern detection has real data. The digest starts making specific tuning recommendations backed by evidence from retrieval logs. You decide whether to apply them.

**The key behavioral design:** the scoring takes 5 seconds and happens right after reading the brief (the context is fresh). The analysis is pushed to you on Sunday — you never have to remember to audit. The suggested change is exactly one thing, not a list. Low friction in, low friction out.

---

## File map

| File | Action |
|------|--------|
| `processors/brief_scorer.py` | Create |
| `processors/retrieval_digest.py` | Create |
| `tests/test_brief_scorer.py` | Create |
| `ask.py` | Modify (add score command interception) |
| `weekly_synthesis.py` | Modify (add digest generation and Telegram send) |
| `.github/workflows/weekly.yml` | Modify (add Telegram secrets to env) |
| `config.json` | Modify (add `brief_scores_file`) |
| `data/state/brief_scores.jsonl` | Created at runtime |

---

## Future extensions (not in this spec)

- `/brief score` could accept a score for a past date: `/brief score yesterday 3`
- The digest could auto-apply suggested changes if you reply "approve" to the Telegram message
- Score data could feed back into the vector store itself — observations from high-scoring days get a metadata boost, improving their retrieval ranking over time
- A `/brief why` command that reads today's retrieval log and explains what context was used, without needing to open the JSONL file
