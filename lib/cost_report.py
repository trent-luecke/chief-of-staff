"""Aggregate the LLM run log into a per-job / per-model / per-window cost view.

`lib/llm_logger.py` appends one JSONL line per Claude call to the git-anchored
`data/state/llm_calls.jsonl`. This module turns that raw stream into the
summary that answers "where is the API spend going, and what should we cut" —
without which the earlier Phase 12 logging was write-only.

`summarize()` is pure (takes parsed entries + a reference date) so it is unit
testable; `build_summary_from_storage()` is the thin I/O wrapper the CLI and
the daily brief use.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timezone

LOG_KEY = "state/llm_calls.jsonl"       # matches lib.llm_logger._LOG_KEY
SUMMARY_KEY = "state/cost_summary.json"  # tracked in git via data/state/ allow-list

_WINDOWS = {"last_7d": 7, "last_30d": 30}


def parse_log(raw: str | None) -> list[dict]:
    """Parse run_log.jsonl content into a list of entry dicts, skipping blank
    and malformed lines (the log is append-only and never rewritten, so a
    partial write must never abort the whole report)."""
    entries: list[dict] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return entries


def _entry_date(entry: dict) -> date | None:
    ts = entry.get("timestamp", "")
    try:
        return date.fromisoformat(ts[:10])
    except (ValueError, TypeError):
        return None


def _agg(entries: list[dict]) -> dict:
    return {
        "calls": len(entries),
        "input_tokens": sum(int(e.get("input_tokens") or 0) for e in entries),
        "output_tokens": sum(int(e.get("output_tokens") or 0) for e in entries),
        "cost_usd": round(sum(float(e.get("estimated_cost_usd") or 0.0) for e in entries), 6),
    }


def _grouped(entries: list[dict], key: str) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        buckets[str(e.get(key, "unknown"))].append(e)
    rows = [{key: name, **_agg(items)} for name, items in buckets.items()]
    rows.sort(key=lambda r: r["cost_usd"], reverse=True)
    return rows


def summarize(entries: list[dict], today: date | None = None) -> dict:
    """Build the cost summary. `today` is injectable for deterministic tests."""
    today = today or datetime.now(timezone.utc).date()

    windows: dict[str, dict] = {}
    for name, days in _WINDOWS.items():
        cutoff = date.fromordinal(today.toordinal() - (days - 1))
        in_window = [e for e in entries if (d := _entry_date(e)) and d >= cutoff]
        windows[name] = _agg(in_window)
    windows["all_time"] = _agg(entries)

    # The trailing 30 days is the decision window for "what to cut".
    cutoff_30 = date.fromordinal(today.toordinal() - 29)
    recent = [e for e in entries if (d := _entry_date(e)) and d >= cutoff_30]

    by_day_buckets: dict[str, list[dict]] = defaultdict(list)
    for e in recent:
        d = _entry_date(e)
        if d:
            by_day_buckets[d.isoformat()].append(e)
    by_day = [{"date": day, **_agg(items)} for day, items in sorted(by_day_buckets.items())]

    return {
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "reference_date": today.isoformat(),
        "total_calls": len(entries),
        "totals": _agg(entries),
        "windows": windows,
        "by_job": _grouped(recent, "run_type"),
        "by_caller": _grouped(recent, "caller"),
        "by_model": _grouped(recent, "model"),
        "by_day": by_day,
    }


def build_summary_from_storage(storage, today: date | None = None) -> dict:
    raw = storage.read(LOG_KEY)
    return summarize(parse_log(raw), today=today)


def refresh(read_storage, write_storage=None, today: date | None = None) -> dict:
    """Read the call log, build the summary, and persist it.

    `read_storage` holds the JSONL call log; `write_storage` (defaults to
    read_storage) is where the summary JSON is written. In production both are
    the git-anchored registry_storage so the summary is committed to main."""
    summary = build_summary_from_storage(read_storage, today=today)
    (write_storage or read_storage).write_json(SUMMARY_KEY, summary)
    return summary


def format_table(summary: dict) -> str:
    """Human-readable summary for stdout / logs."""
    w = summary["windows"]
    lines = [
        f"LLM cost summary (ref {summary.get('reference_date', '?')})",
        f"  last 7d:  ${w['last_7d']['cost_usd']:.2f}  ({w['last_7d']['calls']} calls)",
        f"  last 30d: ${w['last_30d']['cost_usd']:.2f}  ({w['last_30d']['calls']} calls)",
        f"  all time: ${w['all_time']['cost_usd']:.2f}  ({w['all_time']['calls']} calls)",
        "",
        "  By job (last 30d):",
    ]
    for row in summary["by_job"]:
        lines.append(f"    {row['run_type']:<20} ${row['cost_usd']:>8.2f}  {row['calls']:>5} calls")
    lines.append("")
    lines.append("  By call site (last 30d):")
    for row in summary.get("by_caller", []):
        lines.append(f"    {row['caller']:<20} ${row['cost_usd']:>8.2f}  {row['calls']:>5} calls")
    lines.append("")
    lines.append("  By model (last 30d):")
    for row in summary["by_model"]:
        lines.append(f"    {row['model']:<28} ${row['cost_usd']:>8.2f}  {row['calls']:>5} calls")
    return "\n".join(lines)
