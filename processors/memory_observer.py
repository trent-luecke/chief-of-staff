import json
from datetime import date
from typing import Optional

from collectors.gmail import EmailThread
from collectors.pipeline import PipelineLead
from processors.brief import BriefContent
from processors.issues import Issue


def _load_known_decision_dates(obs_file: str) -> set[str]:
    known = set()
    try:
        with open(obs_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    if obs.get("type") == "decision":
                        known.add(obs.get("content", "").strip())
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return known


def _read_decisions(decisions_file: str, known_contents: set[str]) -> list[dict]:
    observations = []
    try:
        with open(decisions_file) as f:
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


def observe(
    obs_file: str,
    decisions_file: str,
    email_threads: list[EmailThread],
    still_open_ids: dict,
    pipeline_leads: list[PipelineLead],
    brief: BriefContent,
    issues: list[Issue],
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
    known_decision_contents = _load_known_decision_dates(obs_file)
    observations.extend(_read_decisions(decisions_file, known_decision_contents))

    if not observations:
        return

    with open(obs_file, "a") as f:
        for obs in observations:
            f.write(json.dumps(obs) + "\n")
