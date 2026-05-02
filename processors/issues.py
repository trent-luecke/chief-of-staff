import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Optional

_KEY = "issues.json"


@dataclass
class Issue:
    id: str
    title: str
    source: str
    source_ref: str
    channel: str
    created_date: str
    last_seen_date: str
    status: str
    actions_needed: list[str]
    outside_parties: list[str]
    resolved_date: Optional[str]

    @property
    def age_days(self) -> int:
        return (date.today() - date.fromisoformat(self.created_date)).days


@dataclass
class IssueLog:
    issues: list[Issue] = field(default_factory=list)


def load_issues(storage) -> IssueLog:
    data = storage.read_json(_KEY)
    if data is None:
        return IssueLog()
    try:
        return IssueLog(issues=[Issue(**i) for i in data.get("issues", [])])
    except (TypeError, KeyError):
        return IssueLog()


def save_issues(log: IssueLog, storage) -> None:
    storage.write_json(_KEY, {"issues": [asdict(i) for i in log.issues]})


def add_or_update_issue(
    storage,
    source: str,
    source_ref: str,
    channel: str,
    title: str,
    actions_needed: Optional[list[str]] = None,
    outside_parties: Optional[list[str]] = None,
) -> None:
    log = load_issues(storage)
    existing_refs = {i.source_ref for i in log.issues}

    if source_ref in existing_refs:
        for issue in log.issues:
            if issue.source_ref == source_ref:
                issue.last_seen_date = date.today().isoformat()
        save_issues(log, storage)
        return

    log.issues.append(Issue(
        id=str(uuid.uuid4())[:8],
        title=title,
        source=source,
        source_ref=source_ref,
        channel=channel,
        created_date=date.today().isoformat(),
        last_seen_date=date.today().isoformat(),
        status="open",
        actions_needed=actions_needed or [],
        outside_parties=outside_parties or [],
        resolved_date=None,
    ))
    save_issues(log, storage)


def auto_resolve_issues(storage, resolve_after_days: int = 3) -> None:
    log = load_issues(storage)
    cutoff = date.today() - timedelta(days=resolve_after_days)
    for issue in log.issues:
        if issue.status == "open":
            if date.fromisoformat(issue.last_seen_date) < cutoff:
                issue.status = "resolved"
                issue.resolved_date = date.today().isoformat()
    save_issues(log, storage)


def get_open_issues(storage) -> list[Issue]:
    log = load_issues(storage)
    return [i for i in log.issues if i.status in ("open", "monitoring")]
