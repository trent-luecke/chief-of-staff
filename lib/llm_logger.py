import json
import re
import sys
from datetime import datetime, timezone

# $/1M tokens. Keys are normalized model IDs (date snapshot suffixes stripped —
# see _resolve_pricing). Rates verified against the Anthropic pricing table
# 2026-09: current Opus/Sonnet/Haiku are $5/$25, $3/$15, $1/$5. The pre-fix
# table had Opus at $15/$75 (stale) and omitted market-intel's dated Sonnet
# entirely, so those calls silently logged as $0.
MODEL_PRICING = {
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},  # e.g. claude-sonnet-4-20250514
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
}

_DATE_SUFFIX = re.compile(r"-\d{8}$")


def _resolve_pricing(model: str) -> dict | None:
    """Look up pricing, tolerating dated snapshot suffixes.

    Tries an exact match first, then strips a trailing -YYYYMMDD and retries.
    Returns None only for genuinely unknown families (still logged as $0 with
    a warning) so a new model string surfaces loudly instead of silently."""
    pricing = MODEL_PRICING.get(model)
    if pricing is not None:
        return pricing
    stripped = _DATE_SUFFIX.sub("", model)
    if stripped != model:
        return MODEL_PRICING.get(stripped)
    return None


_calls: list[dict] = []


def log_usage(caller: str, usage, model: str) -> None:
    try:
        pricing = _resolve_pricing(model)
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


# Git-anchored (tracked via data/state/ allow-list + merge=union in
# .gitattributes) so every workflow's costs accumulate on origin/main and are
# visible in the repo / Registry UI. Callers pass registry_storage(config) — a
# LocalStorage on the working tree — NOT build_storage (R2): most Claude-calling
# workflows have no R2 credentials, so an R2 log would silently drop their costs.
_LOG_KEY = "state/llm_calls.jsonl"


def flush(run_type: str, storage) -> None:
    global _calls
    snapshot = list(_calls)
    _calls = []
    if not snapshot:
        return
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for call in snapshot:
            entry = {"timestamp": timestamp, "run_type": run_type, **call}
            storage.append_line(_LOG_KEY, json.dumps(entry))
    except Exception as e:
        print(f"WARNING: llm_logger flush failed: {e}", file=sys.stderr)


def reset() -> None:
    global _calls
    _calls = []
