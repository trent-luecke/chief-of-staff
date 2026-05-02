"""Weekly retrieval digest: analyze brief scores + retrieval logs via Claude."""

import json
from datetime import date, timedelta
from typing import Optional

import anthropic


_SCORES_KEY = "state/brief_scores.jsonl"
_RETRIEVAL_LOG_KEY = "state/retrieval_log.jsonl"

_SYSTEM_PROMPT = """\
You are analyzing the performance of a morning brief retrieval system. \
The system uses vector search (Pinecone + Voyage AI) to find relevant context \
for a daily email brief. The user scores each brief 1–5 after reading it.

Your job: analyze the scores and retrieval logs for this week, identify \
what went wrong on low-scoring days, find recurring patterns across all \
historical scores, and suggest ONE concrete config change.

Be direct and specific. No preamble. No hedging.

Respond with exactly four sections using these headers:

SCORE SUMMARY
Show the daily scores, this week's average, last week's average (if available), trend direction.

LOW-SCORE DIAGNOSIS
For each day scoring 2 or below: one sentence connecting the user's note \
to a specific finding in the retrieval log (what was missing, what was \
noise, what was excluded and why). If there are no low scores, say so. \
If retrieval logs are unavailable, say so and note that diagnosis will \
improve once retrieval logging is enabled.

RECURRING PATTERNS
Look at ALL historical scores. Are the same keywords, entities, or failure \
modes showing up repeatedly? Call them out. If the history is too short \
to detect patterns, say so.

SUGGESTED CHANGE
Propose exactly ONE config change for next week. Reference the specific \
evidence from the logs. Include the current value and proposed new value. \
If no change is warranted, say "Hold steady — not enough data yet" and explain why.\
"""


def load_scores(storage, since: date) -> list[dict]:
    """Load scores from since date onward. Last score per day wins."""
    daily: dict[str, dict] = {}
    content = storage.read(_SCORES_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry_date = date.fromisoformat(entry["date"])
            if entry_date >= since:
                daily[entry["date"]] = entry
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return sorted(daily.values(), key=lambda x: x["date"])


def load_retrieval_logs(storage, since: date) -> list[dict]:
    """Load retrieval log entries from since date onward, brief trigger only."""
    logs = []
    content = storage.read(_RETRIEVAL_LOG_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry_date = date.fromisoformat(entry["date"])
            if entry_date >= since:
                logs.append(entry)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return logs


def load_all_scores(storage) -> list[dict]:
    """Load all historical scores for recurring pattern detection."""
    scores = []
    content = storage.read(_SCORES_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            scores.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return scores


def _build_user_message(
    this_week_scores: list[dict],
    this_week_logs: list[dict],
    all_scores: list[dict],
    config_snapshot: dict,
) -> str:
    parts = [
        "## This week's scores",
        json.dumps(this_week_scores, indent=2),
        "",
        "## This week's retrieval logs",
        json.dumps(this_week_logs, indent=2) if this_week_logs else "(none — retrieval logging not yet enabled)",
        "",
        "## All historical scores (for pattern detection)",
        json.dumps(all_scores, indent=2),
        "",
        "## Current retrieval config",
        json.dumps(config_snapshot, indent=2),
    ]
    return "\n".join(parts)


def generate_digest(
    storage,
    api_key: str,
    model: str,
    config_snapshot: dict,
    run_date: date,
) -> str:
    """Generate the weekly retrieval digest via Claude. Returns formatted text."""
    since = run_date - timedelta(days=7)
    scores = load_scores(storage, since)
    logs = load_retrieval_logs(storage, since)
    all_scores = load_all_scores(storage)

    if not scores:
        return (
            "No brief scores recorded this week. "
            "Score your briefs with: /brief score [1-5] [optional note]"
        )

    user_message = _build_user_message(scores, logs, all_scores, config_snapshot)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text
