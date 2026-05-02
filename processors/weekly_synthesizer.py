import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import anthropic

from processors.state import load_snapshot

_OBS_KEY = "memory/observations.jsonl"


@dataclass
class WeeklySynthesis:
    executive_summary: str
    patterns: list[str] = field(default_factory=list)
    resolved_this_week: list[str] = field(default_factory=list)
    carry_forwards: list[str] = field(default_factory=list)
    meta_observation: str = ""


def _load_week_observations(storage, run_date: date) -> list[dict]:
    cutoff = run_date - timedelta(days=7)
    observations = []
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            obs_date = date.fromisoformat(obs.get("date", "2000-01-01"))
            if cutoff <= obs_date <= run_date:  # upper bound excludes future-dated observations
                observations.append(obs)
        except (json.JSONDecodeError, ValueError):
            continue
    return observations


def _load_week_state_delta(storage, run_date: date) -> tuple[int, int]:
    """Returns (resolved_count, still_open_count) comparing start-of-week to end-of-week snapshots."""
    start_date = run_date - timedelta(days=7)
    start_snap = load_snapshot(start_date, storage)
    end_snap = load_snapshot(run_date, storage)
    if not start_snap or not end_snap:
        return 0, 0
    start_ids = set(start_snap.open_email_thread_ids)
    end_ids = set(end_snap.open_email_thread_ids)
    resolved_count = len(start_ids - end_ids)
    still_open_count = len(start_ids & end_ids)
    return resolved_count, still_open_count


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
                    if cutoff <= entry_date <= run_date:  # upper bound excludes future-dated entries
                        call_count += 1
                        total_cost += entry.get("estimated_cost_usd", 0.0)
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    return {"call_count": call_count, "total_cost_usd": round(total_cost, 6)}


SYSTEM_PROMPT = """\
You are an AI Chief of Staff for Trent Luecke — VP of Sales at TeamBuildr OS (B2B SaaS for strength and conditioning coaches).

Write a weekly synthesis — a narrative reflection, not a list of events. Surface patterns, what closed, what's accumulating, and the 1-3 most important carry-forwards into next week.

Respond ONLY in JSON with these exact keys:
{
  "executive_summary": "2-3 sentence narrative paragraph — the shape of the week overall",
  "patterns": ["recurring themes that showed up across multiple days, max 3"],
  "resolved_this_week": ["things that closed or were completed, empty list if none"],
  "carry_forwards": ["1-3 highest-priority items heading into next week"],
  "meta_observation": "one operational insight the data reveals that you might not have noticed"
}
"""


def _build_prompt(
    observations: list[dict],
    resolved_count: int,
    still_open_count: int,
    open_issue_titles: list[str],
    captures_text: str,
    run_date: date,
    costs: dict | None = None,
) -> str:
    week_start = (run_date - timedelta(days=7)).isoformat()
    week_end = run_date.isoformat()

    grouped: dict[str, list[dict]] = {}
    for obs in observations:
        obs_type = obs.get("type", "other")
        grouped.setdefault(obs_type, []).append(obs)

    lines = []

    if costs and costs.get("call_count", 0) > 0:
        lines += [
            f"**This week:** {costs['call_count']} Claude calls, ~${costs['total_cost_usd']:.4f}",
            "",
        ]

    lines += [
        f"## Week of {week_start} → {week_end}",
        "",
        f"**Email threads resolved: {resolved_count}**",
        f"**Email threads still open: {still_open_count}**",
        "",
    ]

    if open_issue_titles:
        lines += ["**Open issues:**"] + [f"  - {t}" for t in open_issue_titles] + [""]

    if captures_text and captures_text.strip():
        lines += ["**Action captures logged this week:**", captures_text.strip(), ""]

    if grouped:
        lines.append("**Observations by type:**")
        for obs_type, obs_list in grouped.items():
            lines.append(f"\n### {obs_type}")
            for obs in obs_list:
                lines.append(f"  [{obs['date']}] {obs['entity']}: {obs['content']}")
                if obs.get("context"):
                    lines.append(f"    → {obs['context']}")

    if not grouped and not open_issue_titles and not (captures_text and captures_text.strip()):
        lines.append("_No observations, issues, or captures recorded this week._")

    return "\n".join(lines)


def synthesize_week(
    storage,
    api_key: str,
    model: str,
    run_date: date | None = None,
    log_file: str | None = None,
) -> WeeklySynthesis:
    from processors.issues import get_open_issues
    from lib.captures import load_recent_captures

    if run_date is None:
        run_date = date.today()

    observations = _load_week_observations(storage, run_date)
    resolved_count, still_open_count = _load_week_state_delta(storage, run_date)

    open_issues = get_open_issues(storage)
    open_issue_titles = [i.title for i in open_issues]

    captures_text = load_recent_captures(storage, max_chars=1500)

    costs = _load_week_costs(log_file, run_date) if log_file else None

    prompt = _build_prompt(
        observations=observations,
        resolved_count=resolved_count,
        still_open_count=still_open_count,
        open_issue_titles=open_issue_titles,
        captures_text=captures_text,
        run_date=run_date,
        costs=costs,
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    from lib.llm_logger import log_usage
    log_usage("weekly_synthesizer", response.usage, model)

    raw = response.content[0].text.strip()
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Weekly synthesizer returned non-JSON: {e}\nRaw: {raw[:200]}") from e

    return WeeklySynthesis(
        executive_summary=data.get("executive_summary", ""),
        patterns=data.get("patterns", []),
        resolved_this_week=data.get("resolved_this_week", []),
        carry_forwards=data.get("carry_forwards", []),
        meta_observation=data.get("meta_observation", ""),
    )
