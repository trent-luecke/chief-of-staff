"""Weekly retrieval digest: analyze brief scores + retrieval logs via Claude."""

import json
import os
from datetime import date, timedelta
from typing import Optional

import anthropic


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


def load_scores(scores_file: str, since: date) -> list[dict]:
    """Load scores from since date onward. Last score per day wins."""
    daily: dict[str, dict] = {}
    try:
        with open(scores_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                entry_date = date.fromisoformat(entry["date"])
                if entry_date >= since:
                    daily[entry["date"]] = entry
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

    user_message = _build_user_message(
        this_week_scores, this_week_logs, all_scores, config_snapshot
    )

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
