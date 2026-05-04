import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

_OBS_KEY = "memory/observations.jsonl"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PatternAnomaly:
    type: str       # "new" | "recurring" | "worsening"
    title: str
    description: str
    weeks_seen: int = 1


@dataclass
class AnomalyReport:
    anomalies: list[PatternAnomaly] = field(default_factory=list)


@dataclass
class UpcomingDemo:
    date: date
    title: str
    attendee_emails: list[str]
    lead_name: Optional[str]      # None = not in pipeline
    pipeline_stage: Optional[str]


@dataclass
class DemoScanReport:
    demos: list[UpcomingDemo] = field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _parse_kpi_context(context: str) -> dict[str, int]:
    result = {}
    for token in context.split():
        if "=" in token:
            k, _, v = token.partition("=")
            try:
                result[k] = int(v)
            except ValueError:
                pass
    return result


def _extract_patterns_section(content: str) -> list[str]:
    lines = content.splitlines()
    in_patterns = False
    bullets = []
    for line in lines:
        if line.strip() == "## Patterns":
            in_patterns = True
            continue
        if in_patterns:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                bullets.append(line[2:].strip())
    return bullets


def _week_bucket(obs_date: date, run_date: date) -> Optional[int]:
    delta = (run_date - obs_date).days
    if 0 <= delta < 7:
        return 0
    if 7 <= delta < 14:
        return 1
    if 14 <= delta < 21:
        return 2
    if 21 <= delta < 28:
        return 3
    return None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_observations_window(storage, run_date: date, days: int) -> list[dict]:
    cutoff = run_date - timedelta(days=days)
    obs = []
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            obs_date = date.fromisoformat(entry.get("date", "2000-01-01"))
            if cutoff <= obs_date <= run_date:
                obs.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue
    return obs


def _load_prior_weekly_patterns(
    storage, run_date: date, lookback_weeks: int = 4
) -> list[dict]:
    keys = storage.list_keys("weekly/")
    dated = []
    for key in keys:
        name = key.split("/")[-1].replace(".md", "")
        try:
            d = date.fromisoformat(name)
            if d < run_date:
                dated.append((d, key))
        except ValueError:
            continue
    dated.sort(reverse=True)
    result = []
    for d, key in dated[:lookback_weeks]:
        content = storage.read(key) or ""
        result.append({"date": d.isoformat(), "patterns": _extract_patterns_section(content)})
    return result


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

def _compute_weekly_metrics(obs: list[dict], run_date: date) -> list[dict]:
    labels = ["current week", "week -1", "week -2", "week -3"]
    buckets = []
    for i in range(4):
        week_end = run_date - timedelta(days=7 * i)
        week_start = run_date - timedelta(days=7 * (i + 1))
        buckets.append({
            "label": labels[i],
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "_stale_entities": set(),
            "issue_email_count": 0,
            "issue_slack_count": 0,
            "_kpi_date": None,
            "bugs_high": None,
            "cancellations_mtd": None,
        })

    for entry in obs:
        try:
            obs_date = date.fromisoformat(entry.get("date", ""))
        except ValueError:
            continue
        bucket_idx = _week_bucket(obs_date, run_date)
        if bucket_idx is None:
            continue
        b = buckets[bucket_idx]
        obs_type = entry.get("type", "")

        if obs_type == "pipeline_stale":
            entity = entry.get("entity", "")
            if entity:
                b["_stale_entities"].add(entity)
        elif obs_type == "issue_pattern":
            context = entry.get("context", "")
            if "slack" in context.lower():
                b["issue_slack_count"] += 1
            else:
                b["issue_email_count"] += 1
        elif obs_type == "kpi_snapshot":
            if b["_kpi_date"] is None or obs_date >= b["_kpi_date"]:
                ctx = _parse_kpi_context(entry.get("context", ""))
                b["bugs_high"] = ctx.get("bugs_high")
                b["cancellations_mtd"] = ctx.get("cancellations_mtd")
                b["_kpi_date"] = obs_date

    for b in buckets:
        b["pipeline_stale_count"] = len(b.pop("_stale_entities"))
        b.pop("_kpi_date", None)

    return buckets


def _compute_demo_trend(obs: list[dict], run_date: date) -> list[dict]:
    monthly: dict[str, dict] = {}
    for entry in obs:
        if entry.get("type") != "kpi_snapshot":
            continue
        try:
            obs_date = date.fromisoformat(entry.get("date", ""))
        except ValueError:
            continue
        month_key = obs_date.strftime("%Y-%m")
        existing = monthly.get(month_key)
        if existing is None:
            monthly[month_key] = entry
        else:
            try:
                if obs_date > date.fromisoformat(existing.get("date", "1970-01-01")):
                    monthly[month_key] = entry
            except ValueError:
                pass

    result = []
    for month_key in sorted(monthly.keys(), reverse=True)[:3]:
        entry = monthly[month_key]
        ctx = _parse_kpi_context(entry.get("context", ""))
        result.append({"month": month_key, "demos": ctx.get("demos", 0)})
    return result
