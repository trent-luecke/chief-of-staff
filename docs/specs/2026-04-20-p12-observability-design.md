# P12 Observability — Design Spec

## Goal

Capture per-call Claude API usage (tokens + estimated cost) to a local append-only log, surfaced as a weekly cost summary in the weekly synthesis email. No external services.

---

## Log Entry Format

One JSON line per Claude API call, appended to `data/logs/run_log.jsonl`:

```json
{
  "timestamp": "2026-04-20T07:12:34Z",
  "run_type": "daily_brief",
  "caller": "brief",
  "model": "claude-sonnet-4-6",
  "input_tokens": 4521,
  "output_tokens": 312,
  "estimated_cost_usd": 0.0182
}
```

**Fields:**
- `timestamp` — ISO 8601 UTC, written at flush time
- `run_type` — entry point that triggered the run: `daily_brief`, `weekly_synthesis`, `telegram_query`, `email_reply`
- `caller` — processor name: `brief`, `people`, `memory_synthesizer`, `drafts`, `weekly_synthesizer`, `query_classify`, `query_answer`, `feedback`
- `model` — model ID passed to the API call
- `input_tokens`, `output_tokens` — from `response.usage`
- `estimated_cost_usd` — calculated at write time from pricing constants

---

## Architecture

### `lib/llm_logger.py` (new)

Module-level accumulator. Three public functions:

```python
def log_usage(caller: str, usage, model: str) -> None: ...
def flush(run_type: str, log_file: str) -> None: ...
def reset() -> None: ...  # for tests only
```

**`log_usage`** appends a dict to a module-level `_calls` list. Silent on failure (bad `usage` object → skip). Called immediately after each `client.messages.create()`.

**`flush`** writes all accumulated calls to `log_file` as JSONL (one line per call), then clears `_calls`. Creates `data/logs/` if it doesn't exist. Non-fatal — on any write error, prints a warning and returns without raising.

**`reset`** clears `_calls` — used in tests to isolate state between test cases.

**Pricing constants** (per million tokens):

| Model | Input | Output |
|---|---|---|
| `claude-sonnet-4-6` | $3.00 | $15.00 |
| `claude-haiku-4-5-20251001` | $0.80 | $4.00 |
| `claude-opus-4-7` | $15.00 | $75.00 |

Unknown model → cost logged as `0.0`, warning printed to stderr.

### Processor changes (8 files, 1 line each)

After every `client.messages.create()` call, add:

```python
from lib.llm_logger import log_usage
log_usage("caller_name", response.usage, model)
```

Files and caller names:

| File | Caller name |
|---|---|
| `processors/brief.py` | `brief` |
| `processors/weekly_synthesizer.py` | `weekly_synthesizer` |
| `processors/people.py` | `people` |
| `processors/drafts.py` | `drafts` |
| `processors/memory_synthesizer.py` | `memory_synthesizer` |
| `processors/query.py` (classify call) | `query_classify` |
| `processors/query.py` (answer call) | `query_answer` |
| `processors/feedback.py` | `feedback` |

### Entry point changes (4 files)

Each entry point wraps its main logic in a `try/finally` so `flush(run_type, config["logs_file"])` is always called — even on failure — with whatever calls were accumulated before the error.

| Entry point | `run_type` |
|---|---|
| `main.py` | `daily_brief` |
| `weekly_synthesis.py` | `weekly_synthesis` |
| `ask.py` | `telegram_query` |
| `check_replies.py` | `email_reply` |

### `config.json` change

Add one key:

```json
"logs_file": "data/logs/run_log.jsonl"
```

### `data/logs/.gitkeep`

Directory committed to repo so logs persist across GitHub Actions runs (same pattern as `data/memory/`, `data/weekly/`).

---

## Weekly Synthesis Integration

Add `_load_week_costs(log_file: str, run_date: date) -> dict` to `processors/weekly_synthesizer.py`:

- Reads `run_log.jsonl`, filters to the 7-day window ending `run_date`
- Returns `{"call_count": int, "total_cost_usd": float}`
- Missing file or corrupt lines → return `{"call_count": 0, "total_cost_usd": 0.0}`

Add `log_file: str | None = None` to `synthesize_week()`'s signature. When provided, `synthesize_week` calls `_load_week_costs` and passes the result to `_build_prompt` as a new `costs` parameter. When `None`, costs are skipped (zero-cost default). `weekly_synthesis.py` passes `config["logs_file"]`.

`_build_prompt` appends one line to the prompt when `costs` is non-zero:

```
**This week:** {call_count} Claude calls, ~${total_cost_usd:.2f}
```

This line appears at the top of the prompt context so Claude can reference it in the meta observation if relevant.

---

## Error Handling

- `log_usage()` — silent on any exception (bad usage object, etc.)
- `flush()` — prints warning to stderr on write failure, does not raise, does not affect the brief
- `_load_week_costs()` — returns zero counts on missing file or any read error
- Unknown model in pricing table — cost logged as `0.0`, warning to stderr

---

## Testing

All tests in `tests/test_llm_logger.py`:

1. `test_log_usage_accumulates_calls` — two `log_usage` calls, verify `_calls` has 2 entries
2. `test_log_usage_calculates_cost_correctly` — known token counts + Sonnet pricing → expected cost
3. `test_log_usage_unknown_model_zero_cost` — unknown model ID → cost is 0.0
4. `test_flush_writes_jsonl(tmp_path)` — flush to temp file, read back, verify fields
5. `test_flush_clears_accumulator(tmp_path)` — after flush, `_calls` is empty
6. `test_flush_non_fatal_on_bad_path` — flush to `/nonexistent/dir/log.jsonl` → no exception raised
7. `test_reset_clears_calls` — `log_usage` then `reset()`, verify `_calls` is empty
8. `test_load_week_costs_sums_7_days` — write log entries across 8 days, verify only 7 counted
9. `test_load_week_costs_missing_file` — missing log → returns zero counts
10. `test_load_week_costs_corrupt_lines` — corrupt JSON lines skipped, valid ones counted

No new tests for the 8 processor files or 4 entry points — the one-liner additions are covered by `test_llm_logger.py`.

---

## Files Changed

| File | Action |
|---|---|
| `lib/llm_logger.py` | Create |
| `tests/test_llm_logger.py` | Create |
| `processors/brief.py` | +1 line |
| `processors/weekly_synthesizer.py` | +1 line (log_usage) + `_load_week_costs` + `_build_prompt` update |
| `processors/people.py` | +1 line |
| `processors/drafts.py` | +1 line |
| `processors/memory_synthesizer.py` | +1 line |
| `processors/query.py` | +2 lines |
| `processors/feedback.py` | +1 line |
| `main.py` | +1 line (flush) |
| `weekly_synthesis.py` | +1 line (flush) |
| `ask.py` | +1 line (flush) |
| `check_replies.py` | +1 line (flush) |
| `config.json` | +1 key |
| `data/logs/.gitkeep` | Create |
