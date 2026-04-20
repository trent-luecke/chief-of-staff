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
