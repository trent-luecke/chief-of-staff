from dataclasses import dataclass, field
from collectors.gmail import EmailThread
from collectors.notion_inbox import InboxItem


@dataclass
class LoopSummary:
    new_email_loops: list[dict] = field(default_factory=list)
    new_notion_loops: list[dict] = field(default_factory=list)
    resolved_email_ids: list[str] = field(default_factory=list)
    resolved_notion_ids: list[str] = field(default_factory=list)
    still_open_email_ids: list[str] = field(default_factory=list)
    still_open_notion_ids: list[str] = field(default_factory=list)


def build_loop_summary(
    email_threads: list[EmailThread],
    notion_items: list[InboxItem],
    resolved: dict[str, list[str]],
    still_open: dict[str, list[str]],
) -> LoopSummary:
    still_open_email_set = set(still_open.get("email", []))
    still_open_notion_set = set(still_open.get("notion", []))

    new_email_loops = [
        {
            "thread_id": t.id,
            "subject": t.subject,
            "from": t.last_sender,
            "snippet": t.snippet,
        }
        for t in email_threads
        if t.id not in still_open_email_set
    ]
    new_notion_loops = [
        {
            "item_id": n.id,
            "name": n.name,
            "urgency": n.urgency,
            "type": n.item_type,
        }
        for n in notion_items
        if n.id not in still_open_notion_set
    ]

    return LoopSummary(
        new_email_loops=new_email_loops,
        new_notion_loops=new_notion_loops,
        resolved_email_ids=list(resolved.get("email", [])),
        resolved_notion_ids=list(resolved.get("notion", [])),
        still_open_email_ids=list(still_open_email_set),
        still_open_notion_ids=list(still_open_notion_set),
    )
