"""Log retrieval results for auditing and future tuning."""

import json
from datetime import datetime, timezone

_LOG_KEY = "state/retrieval_log.jsonl"


def log_retrieval(
    storage,
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
    """Append a retrieval log entry via the storage backend."""
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
    storage.append_line(_LOG_KEY, json.dumps(entry))
