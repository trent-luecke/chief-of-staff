import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import anthropic
from lib.llm_logger import log_usage

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
        week_start = run_date - timedelta(days=7 * i + 6)
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


# ---------------------------------------------------------------------------
# Anomaly detection — prompt + Claude call
# ---------------------------------------------------------------------------

_ANOMALY_SYSTEM_PROMPT = """\
You are analyzing weekly trend data for Trent Luecke — VP of Sales at TeamBuildr OS \
(B2B SaaS for strength and conditioning coaches).

Review the metric deltas and pattern history. Surface 0–3 genuinely notable anomalies only.

An anomaly is worth surfacing if:
- A metric is 2× or more above its 4-week average (type: "worsening")
- A pattern has appeared in 3+ of the last 4 synthesized pattern lists (type: "recurring")
- A new pattern this week is absent from all prior 4 weeks AND supported by raw metric counts \
(type: "new")
- Month-over-month demo count dropped 20%+ (type: "worsening")

Cite specific numbers. If nothing clearly meets these thresholds, return {"anomalies": []}.

Respond ONLY in JSON:
{"anomalies": [{"type": "new"|"recurring"|"worsening", "title": "short label", \
"description": "1-2 sentences with specific numbers", "weeks_seen": 1}]}
"""


def _build_anomaly_prompt(
    current_synthesis,
    run_date: date,
    weekly_metrics: list[dict],
    demo_trend: list[dict],
    prior_patterns: list[dict],
) -> str:
    lines = [f"## Current week (ending {run_date.isoformat()})", ""]

    lines.append("**Current patterns:**")
    for p in current_synthesis.patterns:
        lines.append(f"- {p}")
    lines.append("")

    lines.append("## Weekly metrics (current + prior 3 weeks)")
    lines.append("")
    lines.append("| Week | Stale Leads | Issues (email) | Issues (Slack) | Bugs High | Cancellations MTD |")
    lines.append("|---|---|---|---|---|---|")
    for m in weekly_metrics:
        bugs = m["bugs_high"] if m["bugs_high"] is not None else "—"
        cancel = m["cancellations_mtd"] if m["cancellations_mtd"] is not None else "—"
        lines.append(
            f"| {m['label']} ({m['week_start']}) "
            f"| {m['pipeline_stale_count']} "
            f"| {m['issue_email_count']} "
            f"| {m['issue_slack_count']} "
            f"| {bugs} "
            f"| {cancel} |"
        )
    lines.append("")

    if demo_trend:
        lines.append("## Demo trend (last 3 months, demos MTD at month-end)")
        lines.append("")
        for m in demo_trend:
            lines.append(f"- {m['month']}: {m['demos']} demos")
        lines.append("")

    lines.append("## Prior 4 weeks — synthesized patterns")
    lines.append("")
    for pw in prior_patterns:
        lines.append(f"**Week ending {pw['date']}:**")
        for p in pw["patterns"]:
            lines.append(f"- {p}")
        if not pw["patterns"]:
            lines.append("- (none recorded)")
        lines.append("")

    return "\n".join(lines)


def detect_anomalies(
    storage,
    current_synthesis,
    run_date: date,
    api_key: str,
    model: str,
    lookback_weeks: int = 4,
) -> AnomalyReport:
    prior_patterns = _load_prior_weekly_patterns(storage, run_date, lookback_weeks)
    if len(prior_patterns) < 2:
        return AnomalyReport()

    obs = _load_observations_window(storage, run_date, days=90)
    weekly_metrics = _compute_weekly_metrics(obs, run_date)
    demo_trend = _compute_demo_trend(obs, run_date)

    prompt = _build_anomaly_prompt(current_synthesis, run_date, weekly_metrics, demo_trend, prior_patterns)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=800,
        system=_ANOMALY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    log_usage("pattern_detector", response.usage, model)

    raw = response.content[0].text.strip()
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return AnomalyReport()

    anomalies = []
    for item in data.get("anomalies", [])[:3]:
        anomalies.append(PatternAnomaly(
            type=item.get("type", "new"),
            title=item.get("title", ""),
            description=item.get("description", ""),
            weeks_seen=item.get("weeks_seen", 1),
        ))
    return AnomalyReport(anomalies=anomalies)


# ---------------------------------------------------------------------------
# Demo scan
# ---------------------------------------------------------------------------

def _load_pipeline_lead_details(storage) -> dict[str, dict]:
    data = storage.read_json("pipeline_cache.json", default={})
    result = {}
    for r in data.get("leads", []):
        if r.get("email") and r.get("status") not in {"Closed", "Lost"}:
            result[r["email"].lower()] = {
                "name": r.get("name", ""),
                "status": r.get("status", ""),
            }
    return result


def _is_demo_event(event, demo_cfg: dict) -> bool:
    demo_keywords = [kw.lower() for kw in demo_cfg.get("demo_keywords", ["demo"])]
    internal_domains = [d.lower() for d in demo_cfg.get("internal_domains", ["teambuildr.com"])]

    title = event.summary.lower()
    desc = (event.description or "").lower()

    # Rule 1: demo keyword in description
    if not any(kw in desc for kw in demo_keywords):
        return False

    # Rule 2: "OS" product name in title or description (word-boundary match)
    if not (re.search(r'\bOS\b', event.summary) or re.search(r'\bOS\b', event.description or "")):
        return False

    # Rule 3: at least one external attendee
    has_external = any(
        not any(email.lower().endswith(f"@{domain}") for domain in internal_domains)
        for email in event.attendees
    )
    if not has_external:
        return False

    # Rule 4: not declined by calendar owner
    if event.declined:
        return False

    return True


def scan_upcoming_demos(
    config: dict,
    user_email: str,
    run_date: date,
    storage,
) -> DemoScanReport:
    from collectors.calendar import fetch_date_range_events

    demo_cfg = config.get("demo_scan", {})
    lookforward = demo_cfg.get("lookforward_days", 28)
    internal_domains = [d.lower() for d in demo_cfg.get("internal_domains", ["teambuildr.com"])]

    all_cal_ids = list(config.get("calendar_ids", [])) + list(demo_cfg.get("sales_rep_calendar_ids", []))
    start = run_date + timedelta(days=1)
    end = run_date + timedelta(days=lookforward + 1)

    events = fetch_date_range_events(all_cal_ids, start, end, user_email)
    lead_details = _load_pipeline_lead_details(storage)

    demos = []
    for event in events:
        if not _is_demo_event(event, demo_cfg):
            continue

        external_emails = [
            email for email in event.attendees
            if not any(email.lower().endswith(f"@{domain}") for domain in internal_domains)
        ]

        lead_name = None
        pipeline_stage = None
        for email in external_emails:
            details = lead_details.get(email.lower())
            if details:
                lead_name = details["name"]
                pipeline_stage = details["status"]
                break

        demos.append(UpcomingDemo(
            date=event.start.date(),
            title=event.summary,
            attendee_emails=external_emails,
            lead_name=lead_name,
            pipeline_stage=pipeline_stage,
        ))

    return DemoScanReport(demos=demos, total=len(demos))
