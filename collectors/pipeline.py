import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


@dataclass
class PipelineLead:
    name: str
    contact: str
    email: str
    status: str
    priority: str
    last_contacted: Optional[str]
    days_since_contact: Optional[int]
    estimated_value: Optional[float]
    source: str
    stale: bool


_TRIAL_STATUS = "In-Trial / Post Demo"
_ATTENTION_STATUSES = {
    "Out of Demo / Need Upate",  # intentional typo matches Notion DB
    "No-Show",
    "On-Hold",
    "No Trial / Post Demo",
}


def count_late_stage(leads: list[PipelineLead], statuses: list[str]) -> int:
    """Count leads whose status is in the late-stage list from config."""
    status_set = set(statuses)
    return sum(1 for lead in leads if lead.status in status_set)


def load_activity_overrides(activity_path: str) -> dict[str, str]:
    """Returns {email_lower: last_email_date} from the watcher's activity file."""
    try:
        with open(activity_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {
        email: record["last_email_date"]
        for email, record in data.get("leads", {}).items()
        if record.get("last_email_date")
    }


def fetch_pipeline_leads(
    cache_path: str,
    trial_followup_after_days: int = 5,
    stale_after_days: int = 14,
) -> tuple[list[PipelineLead], list[PipelineLead]]:
    """
    Reads the pipeline cache written nightly by the remote sync agent.
    Returns (trial_followup_leads, attention_needed_leads).
    """
    path = Path(cache_path).expanduser()
    if not path.exists():
        return [], []

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return [], []

    today = date.today()
    activity_path = str(Path(cache_path).parent / "pipeline_email_activity.json")
    activity_overrides = load_activity_overrides(activity_path)

    def _days_since(iso: Optional[str]) -> Optional[int]:
        if not iso:
            return None
        try:
            return (today - date.fromisoformat(iso[:10])).days
        except (ValueError, TypeError):
            return None

    leads = []
    for r in data.get("leads", []):
        email = r.get("email", "").lower()
        # Use the more recent of Notion's last_contacted or watcher-detected activity
        cache_date = r.get("last_contacted")
        activity_date = activity_overrides.get(email)
        effective_date = max(filter(None, [cache_date, activity_date])) if (cache_date or activity_date) else None

        days = _days_since(effective_date)
        # If activity data shows more recent contact than Notion, recompute stale from that.
        # Otherwise trust whatever Notion's checkbox/calc says.
        activity_is_newer = activity_date and (not cache_date or activity_date > cache_date)
        if activity_is_newer:
            stale = days is not None and days >= stale_after_days
        else:
            stale = bool(r.get("stale", False))

        leads.append(PipelineLead(
            name=r.get("name", ""),
            contact=r.get("contact", ""),
            email=email,
            status=r.get("status", ""),
            priority=r.get("priority", ""),
            last_contacted=effective_date,
            days_since_contact=days,
            estimated_value=r.get("estimated_value"),
            source=r.get("source", ""),
            stale=stale,
        ))

    trial_leads = [
        l for l in leads
        if l.status == _TRIAL_STATUS
        and (l.days_since_contact is None or l.days_since_contact >= trial_followup_after_days)
    ]

    attention_leads = [
        l for l in leads
        if l.status in _ATTENTION_STATUSES
        and (
            l.stale
            or l.days_since_contact is None
            or l.days_since_contact >= stale_after_days
        )
    ]

    return trial_leads, attention_leads
