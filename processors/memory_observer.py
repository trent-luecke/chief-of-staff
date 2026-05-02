import json
from datetime import date

from collectors.gmail import EmailThread
from collectors.pipeline import PipelineLead
from processors.brief import BriefContent
from processors.issues import Issue

_OBS_KEY = "memory/observations.jsonl"
_DECISIONS_FILE = "data/memory/decisions.md"  # human-authored, raw open()


def _load_known_decision_dates(storage) -> set[str]:
    known = set()
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            if obs.get("type") == "decision":
                known.add(obs.get("content", "").strip())
        except json.JSONDecodeError:
            continue
    return known


def _read_decisions(decisions_file: str, known_contents: set[str]) -> list[dict]:
    observations = []
    try:
        with open(decisions_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Format: YYYY-MM-DD: <text>
                if ":" not in line:
                    continue
                date_part, _, text = line.partition(":")
                text = text.strip()
                if text and text not in known_contents:
                    observations.append({
                        "date": date.today().isoformat(),
                        "type": "decision",
                        "entity": "manual",
                        "content": text,
                        "source": "manual",
                    })
    except FileNotFoundError:
        pass
    return observations


def _kpi_snapshot_exists_today(storage) -> bool:
    """Return True if a kpi_snapshot for today already exists in storage."""
    today = date.today().isoformat()
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            if obs.get("type") == "kpi_snapshot" and obs.get("date") == today:
                return True
        except json.JSONDecodeError:
            continue
    return False


def _build_kpi_snapshot(
    pipeline_leads,
    sales_data: dict,
    demos_data: dict,
    bugs: list,
    cancellations: dict,
) -> dict:
    """Build a kpi_snapshot observation dict from collected KPI data."""
    today = date.today().isoformat()

    sales_revenue = sales_data.get("revenue", 0.0) if sales_data else 0.0
    sales_count = sales_data.get("count", 0) if sales_data else 0
    demo_count = demos_data.get("count", 0) if demos_data else 0
    cancel_count = cancellations.get("count", 0) if cancellations else 0

    # Pipeline breakdown by status
    pipeline_by_status: dict[str, int] = {}
    for lead in (pipeline_leads or []):
        status = getattr(lead, "status", None) or lead.get("status", "Unknown") if isinstance(lead, dict) else getattr(lead, "status", "Unknown")
        pipeline_by_status[status] = pipeline_by_status.get(status, 0) + 1

    pipeline_str = ", ".join(f"{count} {status}" for status, count in pipeline_by_status.items())
    if not pipeline_str:
        pipeline_str = "0 leads"

    # Bug breakdown by priority
    open_bugs = [b for b in (bugs or []) if (b.get("status") if isinstance(b, dict) else getattr(b, "status", "")) != "Done"]
    bug_count = len(open_bugs)
    def _priority(b):
        return b.get("priority_level") if isinstance(b, dict) else getattr(b, "priority_level", "")
    high = sum(1 for b in open_bugs if _priority(b) == "High")
    moderate = sum(1 for b in open_bugs if _priority(b) == "Moderate")
    low = sum(1 for b in open_bugs if _priority(b) == "Low")

    content = (
        f"KPI snapshot {today}: "
        f"Sales MTD ${sales_revenue:,.0f} ({sales_count} deals). "
        f"Demos MTD: {demo_count}. "
        f"Pipeline: {pipeline_str}. "
        f"Open bugs: {bug_count} ({high} High, {moderate} Moderate, {low} Low). "
        f"Cancellations MTD: {cancel_count}."
    )

    context = (
        f"sales_revenue={int(sales_revenue)} sales_count={sales_count} "
        f"demos={demo_count} open_bugs={bug_count} bugs_high={high} "
        f"cancellations_mtd={cancel_count}"
    )

    return {
        "date": today,
        "type": "kpi_snapshot",
        "entity": "daily",
        "content": content,
        "source": "kpi",
        "context": context,
    }


def observe(
    storage,
    decisions_file: str,
    email_threads: list[EmailThread],
    still_open_ids: dict,
    pipeline_leads: list[PipelineLead],
    brief: BriefContent,
    issues: list[Issue],
    sales_data: dict | None = None,
    demos_data: dict | None = None,
    bugs: list | None = None,
    cancellations: dict | None = None,
) -> None:
    today = date.today().isoformat()
    observations = []

    # email_loop: threads still open from previous run
    still_open_email = set(still_open_ids.get("email", []))
    thread_map = {t.id: t for t in email_threads}
    for thread_id in still_open_email:
        thread = thread_map.get(thread_id)
        if thread:
            observations.append({
                "date": today,
                "type": "email_loop",
                "entity": f"thread:{thread.subject}",
                "content": "Thread open multiple days, no reply",
                "source": "state",
                "context": thread.snippet[:200] if thread.snippet else "",
            })

    # pipeline_stale
    for lead in pipeline_leads:
        if lead.stale or (lead.days_since_contact and lead.days_since_contact > 7):
            days = lead.days_since_contact or 0
            observations.append({
                "date": today,
                "type": "pipeline_stale",
                "entity": lead.name.lower().replace(" ", "-"),
                "content": f"{lead.name} stale {days} days, status: {lead.status}",
                "source": "pipeline",
            })

    # top_priority
    for priority in (brief.top_3_priorities or []):
        observations.append({
            "date": today,
            "type": "top_priority",
            "entity": "priorities",
            "content": priority,
            "source": "brief",
        })

    # issue_pattern
    for issue in issues:
        try:
            age_days = issue.age_days
        except (ValueError, TypeError, AttributeError):
            age_days = 0
        observations.append({
            "date": today,
            "type": "issue_pattern",
            "entity": issue.channel or issue.source,
            "content": f"{issue.title} (age: {age_days}d, status: {issue.status})",
            "source": "issues",
            "context": f"source: {issue.source}#{issue.channel}",
        })

    # decisions from decisions.md (only new ones)
    known_decision_contents = _load_known_decision_dates(storage)
    observations.extend(_read_decisions(decisions_file, known_decision_contents))

    # kpi_snapshot — written once per day
    # None means "collector not configured"; [] or {"count":0} means "ran but found nothing" — both trigger snapshot
    has_kpi = any(p is not None for p in [sales_data, demos_data, bugs, cancellations])
    if has_kpi and not _kpi_snapshot_exists_today(storage):
        observations.append(_build_kpi_snapshot(
            pipeline_leads=pipeline_leads,
            sales_data=sales_data or {},
            demos_data=demos_data or {},
            bugs=bugs or [],
            cancellations=cancellations or {},
        ))

    if not observations:
        return

    for obs in observations:
        storage.append_line(_OBS_KEY, json.dumps(obs))
