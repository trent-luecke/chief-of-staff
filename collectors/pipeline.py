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

    def _days_since(iso: Optional[str]) -> Optional[int]:
        if not iso:
            return None
        try:
            return (today - date.fromisoformat(iso[:10])).days
        except (ValueError, TypeError):
            return None

    leads = [
        PipelineLead(
            name=r.get("name", ""),
            contact=r.get("contact", ""),
            email=r.get("email", ""),
            status=r.get("status", ""),
            priority=r.get("priority", ""),
            last_contacted=r.get("last_contacted"),
            days_since_contact=_days_since(r.get("last_contacted")),
            estimated_value=r.get("estimated_value"),
            source=r.get("source", ""),
            stale=bool(r.get("stale", False)),
        )
        for r in data.get("leads", [])
    ]

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
