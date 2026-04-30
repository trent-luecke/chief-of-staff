# P14 Phase 2 — Retrieval logging spec

**Date:** 2026-04-30  
**Status:** Draft, to be implemented alongside Phase 2 semantic retrieval  
**Parent:** `docs/superpowers/specs/2026-04-29-p14-vector-memory-layer-design.md`

---

## Purpose

Every time the semantic retriever runs, log exactly what it returned: which vectors, what scores, what made it into the prompt, and what got cut. Without this, there's no way to debug a bad brief ("why did it mention X and not Y?") and no way to tune retrieval parameters over time.

This log is the foundation for a future feedback loop (P15 or Phase 4) where brief quality scores get paired with retrieval data to guide parameter tuning. But even without that future work, the log is immediately useful for manual inspection and debugging.

---

## Log location

`data/state/retrieval_log.jsonl`

Append-only, one JSON line per retrieval run. Same commit-to-repo pattern as `observations.jsonl` and the daily state files. Gets committed back on each GitHub Actions run.

For Telegram queries, log to the same file with a different `trigger` field so both retrieval paths share one audit trail.

---

## Schema

Each line is a JSON object with this shape:

```json
{
  "date": "2026-04-30",
  "timestamp": "2026-04-30T07:01:14Z",
  "trigger": "brief",
  "query_text_preview": "Calendar: Apex onboarding call, TGMC check-in | Email: Contract renewal follow-up, Stripe migration... | Pipeline: Patrick Labat, Drew DeVine | Issues: athletes can't see programs",
  "query_text_tokens": 87,
  "retrieval_mode": "semantic",
  "pinned_memories": [
    {
      "file": "onboarding-playbook.md",
      "topic": "onboarding-playbook",
      "tokens": 120
    }
  ],
  "pinned_tokens_used": 120,
  "memory_results": [
    {
      "id": "mem:pipeline-stale-post-demo.md",
      "namespace": "memories",
      "score": 0.82,
      "topic": "pipeline-stale-post-demo",
      "content_preview": "Tzach Feinsilver flagged every day...",
      "included": true,
      "tokens": 95
    },
    {
      "id": "mem:apex-trial.md",
      "namespace": "memories",
      "score": 0.74,
      "topic": "apex-trial",
      "content_preview": "Apex has been flagged stale for 8...",
      "included": true,
      "tokens": 80
    }
  ],
  "observation_results": [
    {
      "id": "2026-04-29:pipeline_stale:patrick-labat",
      "namespace": "observations",
      "score": 0.79,
      "type": "pipeline_stale",
      "entity": "patrick-labat",
      "content_preview": "Patrick Labat — TGMC stale 45 days...",
      "included": true,
      "tokens": 22
    },
    {
      "id": "2026-04-28:email_loop:thread:Contract",
      "namespace": "observations",
      "score": 0.61,
      "type": "email_loop",
      "entity": "thread:Contract",
      "content_preview": "Thread open multiple days, no reply...",
      "included": true,
      "tokens": 30
    },
    {
      "id": "2026-04-27:issue_pattern:athlete-programs",
      "namespace": "observations",
      "score": 0.38,
      "type": "issue_pattern",
      "entity": "athlete-programs",
      "content_preview": "Athletes can't see their programs...",
      "included": false,
      "excluded_reason": "below_score_threshold"
    }
  ],
  "token_budget": 550,
  "pinned_budget_used": 120,
  "memory_budget_used": 175,
  "observation_budget_used": 52,
  "total_tokens_used": 347,
  "budget_remaining": 203,
  "items_returned": 4,
  "items_excluded": 1,
  "config_snapshot": {
    "retrieval_mode": "auto",
    "top_k": 20,
    "memory_budget_pct": 0.6,
    "observation_budget_pct": 0.4,
    "score_threshold": null
  }
}
```

---

## Field reference

**Top-level fields:**

- `date` — the brief date (YYYY-MM-DD)
- `timestamp` — ISO 8601 UTC when retrieval ran
- `trigger` — what initiated this retrieval: `"brief"` for the morning brief, `"telegram"` for a Telegram query, `"manual"` for a debug/test run
- `query_text_preview` — first 500 chars of the concatenated query string sent to Voyage for embedding. Enough to see what went into the query without logging the full thing.
- `query_text_tokens` — approximate token count of the query string (use `len(text) / 4` — doesn't need to be exact)
- `retrieval_mode` — which mode actually ran: `"semantic"`, `"file"`, or `"file_fallback"` (meaning semantic was attempted but Pinecone was unreachable)

**Pinned memories:**

- `pinned_memories` — list of pinned memory files that were force-included (bypassing vector ranking)
- `pinned_tokens_used` — total tokens consumed by pinned memories

**Vector results (memory_results and observation_results):**

Each result object has:

- `id` — the Pinecone vector ID
- `namespace` — which namespace it came from
- `score` — cosine similarity score from Pinecone (0.0 to 1.0)
- `topic` or `type`/`entity` — the metadata fields, depending on namespace
- `content_preview` — first 80 chars of the text that would be inserted into the prompt
- `included` — boolean, whether this result actually made it into the prompt
- `tokens` — approximate token count (only present if included)
- `excluded_reason` — only present if `included` is false. Values: `"below_score_threshold"`, `"budget_exhausted"`, `"duplicate_of_pinned"`, `"expired"`, `"suppressed"`

**Budget accounting:**

- `token_budget` — the total budget (550 by default)
- `pinned_budget_used`, `memory_budget_used`, `observation_budget_used` — how much each section consumed
- `total_tokens_used` — sum of the above
- `budget_remaining` — tokens left unused
- `items_returned` — count of results that made it into the prompt
- `items_excluded` — count of results that were fetched from Pinecone but didn't make the cut

**Config snapshot:**

A frozen copy of the retrieval config at the time of the run. When you're looking at logs from two weeks ago wondering why results looked different, this tells you what the settings were. Fields:

- `retrieval_mode` — what was configured (not what actually ran — see top-level `retrieval_mode` for that)
- `top_k` — how many results were requested from Pinecone per namespace
- `memory_budget_pct` — fraction of remaining budget (after pinned) allocated to memory results
- `observation_budget_pct` — fraction allocated to observation results
- `score_threshold` — minimum cosine score to include a result, or `null` if no threshold is set

---

## Implementation

The logging function should live in a new file: `processors/retrieval_logger.py`. Keep it separate from the retriever itself so the retriever stays clean.

```python
"""Log retrieval results for auditing and future tuning."""

import json
import os
from datetime import datetime, timezone


def log_retrieval(
    log_file: str,
    date_str: str,
    trigger: str,
    query_text: str,
    retrieval_mode: str,
    pinned_memories: list[dict],
    memory_results: list[dict],
    observation_results: list[dict],
    token_budget: int,
    config_snapshot: dict,
) -> None:
    """Append a retrieval log entry to the JSONL file."""
    pinned_tokens = sum(m.get("tokens", 0) for m in pinned_memories)
    mem_tokens = sum(r.get("tokens", 0) for r in memory_results if r.get("included"))
    obs_tokens = sum(r.get("tokens", 0) for r in observation_results if r.get("included"))
    total = pinned_tokens + mem_tokens + obs_tokens

    included_count = (
        len(pinned_memories)
        + sum(1 for r in memory_results if r.get("included"))
        + sum(1 for r in observation_results if r.get("included"))
    )
    excluded_count = (
        sum(1 for r in memory_results if not r.get("included"))
        + sum(1 for r in observation_results if not r.get("included"))
    )

    entry = {
        "date": date_str,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "query_text_preview": query_text[:500],
        "query_text_tokens": len(query_text) // 4,
        "retrieval_mode": retrieval_mode,
        "pinned_memories": pinned_memories,
        "pinned_tokens_used": pinned_tokens,
        "memory_results": memory_results,
        "observation_results": observation_results,
        "token_budget": token_budget,
        "pinned_budget_used": pinned_tokens,
        "memory_budget_used": mem_tokens,
        "observation_budget_used": obs_tokens,
        "total_tokens_used": total,
        "budget_remaining": token_budget - total,
        "items_returned": included_count,
        "items_excluded": excluded_count,
        "config_snapshot": config_snapshot,
    }

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
```

**Where to call it:** inside `memory_retriever.py`, at the end of the `retrieve_memories` function (or its new semantic equivalent), after results are selected and formatted but before the formatted string is returned. The retriever builds the result objects during its selection loop, then passes them to `log_retrieval` as a final step.

The log call should be wrapped in try/except — logging failure should never block the brief. Print a warning if it fails, same pattern as the vector ingest error handling.

---

## Wiring into the retriever

The modified `retrieve_memories` function will need to track results as structured objects during its selection loop anyway (to do budget accounting, deduplication, expiry filtering). The log just captures those objects before they get flattened into the output string.

Rough shape of the retriever's internal flow:

```
1. Load pinned memories from .md files → pinned_list
2. Deduct pinned tokens from budget
3. Build query string from today's signals
4. Embed query via Voyage (input_type="query")
5. Query Pinecone memories namespace (top_k=20)
6. Query Pinecone observations namespace (top_k=20)
7. Post-filter: remove expired, suppressed, duplicates of pinned
8. Score-rank remaining results
9. Fill memory budget (60% of remaining) from memory results
10. Fill observation budget (40% of remaining) from observation results
11. Format into "## Cross-Day Memory" string
12. Call log_retrieval() with all the structured data from steps 1-10
13. Return the formatted string
```

Step 12 is the logging. Everything it needs is already computed by steps 1-10.

---

## Config

Add to the `vector` block in `config.json`:

```json
"retrieval_log_file": "data/state/retrieval_log.jsonl"
```

---

## Telegram query logging

When `query.py` uses the semantic retriever for a Telegram question, the same `log_retrieval` function gets called with `trigger="telegram"` and the user's query text as the query string. This means both retrieval paths — morning brief and ad-hoc Telegram questions — share one log file, distinguishable by the `trigger` field.

---

## What this enables later

**Manual debugging (immediate):** When a brief feels off, open `retrieval_log.jsonl`, find today's entry, and see exactly what context was provided. Was the relevant memory fetched but excluded for budget reasons? Was it never fetched at all (bad query construction)? Was it fetched with a low score (embedding quality issue)? Each failure mode has a different fix.

**A/B comparison (immediate):** Toggle `retrieval_mode` between `"semantic"` and `"file"`, run the same day's data twice, compare the retrieval logs. The `retrieval_mode` field tells you which method produced which results.

**Automated tuning (future — P15 or Phase 4):** Pair retrieval logs with brief quality scores. A weekly Claude job reads the logs + scores and proposes parameter changes:

- "Briefs scored 4+ when memory results had scores above 0.65. Consider setting `score_threshold` to 0.6."
- "Observation results were included in 80% of high-scoring briefs but only 30% of low-scoring ones. Consider increasing `observation_budget_pct` to 0.5."
- "Pipeline lead names in the query correlated with higher retrieval scores for pipeline-related memories. Keep them in query construction."

The config snapshot in each log entry makes this analysis possible even if you've changed parameters between then and now — you always know what settings produced each result.

---

## Retention

The log file will grow at ~1 line per day (brief) plus occasional Telegram queries. Each line is roughly 1-3 KB depending on how many results come back. After a year that's maybe 500 KB. No rotation needed — just let it accumulate. It's your training data.

If the file ever gets unwieldy, the `date` field makes it easy to truncate old entries: `head -n -365` or similar.
