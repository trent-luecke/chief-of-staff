import json
import re
import anthropic
from dataclasses import dataclass, field
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.gmail_personal import PersonalEmail
from collectors.local_data import Project, RecurringTask
from processors.loops import LoopSummary
from processors.issues import Issue
from processors.drafts import Draft


SYSTEM_PROMPT = """\
You are an AI Chief of Staff for Trent Luecke — VP of Sales at TeamBuildr OS (B2B SaaS for strength and conditioning coaches) and founder of Vero (gym AI side project). You also help with his personal life, LinkedIn content, and a weekly content podcast.

Deliver an expansive, actionable morning brief. Be direct. No filler. Prioritize ruthlessly.

Rules:
- Open issues from prior days appear in top_3_priorities with age and source: "[ISSUE: N days, Slack #channel] title"
- Issues are the highest-priority items if they are multi-day or involve customer-facing problems
- recurring_due lists tasks due today by name and cadence — do not bury these in priorities
- drafts_ready lists email drafts generated and waiting for review — just name and context
- personal_items lists anything from personal Gmail that needs attention — brief, not buried
- meeting_prep lists prep notes for internal meetings today — last session summary and open items
- inbox contains raw quick-capture notes from iPhone — surface urgent items in top_3_priorities, map ideas to active projects where relevant, flag anything actionable today

Respond ONLY in JSON with these exact keys:
{
  "executive_summary": "2-3 sentence synthesis of the day ahead",
  "top_3_priorities": ["3 action items, open issues called out with age and source"],
  "watch_outs": ["0-3 risks or things that could go wrong today"],
  "schedule_notes": "one sentence about schedule shape",
  "personal_items": ["personal email items needing attention, empty list if none"],
  "recurring_due": ["recurring tasks due today with cadence"],
  "drafts_ready": ["drafts ready to review and send"],
  "meeting_prep": ["prep notes for today's internal meetings, empty list if none"]
}
"""


@dataclass
class BriefContent:
    executive_summary: str
    top_3_priorities: list[str] = field(default_factory=list)
    watch_outs: list[str] = field(default_factory=list)
    schedule_notes: str = ""
    personal_items: list[str] = field(default_factory=list)
    recurring_due: list[str] = field(default_factory=list)
    drafts_ready: list[str] = field(default_factory=list)
    meeting_prep: list[str] = field(default_factory=list)


def _build_prompt(
    today_events: list[CalendarEvent],
    tomorrow_events: list[CalendarEvent],
    email_threads: list[EmailThread],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    open_issues: list[Issue],
    personal_emails: list[PersonalEmail],
    drafts: list[Draft],
    meeting_prep: list[str],
    inbox_text: str,
) -> str:
    def fmt_event(e: CalendarEvent) -> str:
        return f"  {e.start.strftime('%I:%M%p').lstrip('0')} — {e.summary}"

    def fmt_issue(i: Issue) -> str:
        return f"  [{i.age_days}d, {i.source}#{i.channel}] {i.title} (status: {i.status})"

    def fmt_draft(d: Draft) -> str:
        return f"  {d.draft_type}: {d.context} → to {d.to}"

    sections = [
        "## Open Issues (surface in priorities with age and source)",
        *([fmt_issue(i) for i in open_issues] or ["  (none)"]),
        "",
        "## Today's Calendar",
        *([fmt_event(e) for e in today_events] or ["  (no events)"]),
        "",
        "## Tomorrow Preview",
        *([fmt_event(e) for e in tomorrow_events] or ["  (no events)"]),
        "",
        "## Work Emails Needing Attention",
        *([f"  {t.subject} from {t.last_sender}" for t in email_threads] or ["  (none)"]),
        "",
        "## Personal Items (allowlisted personal Gmail)",
        *([f"  {e.sender}: {e.subject} — {e.snippet[:80]}" for e in personal_emails] or ["  (none)"]),
        "",
        "## Email Drafts Ready for Review",
        *([fmt_draft(d) for d in drafts] or ["  (none)"]),
        "",
        "## Meeting Prep (internal meetings today)",
        *([f"  {m}" for m in meeting_prep] or ["  (no tracked internal meetings today)"]),
        "",
        "## Active Projects",
        *([f"  {p.name} [{p.status}] — Next: {p.next_step}" for p in projects] or ["  (none)"]),
        "",
        "## Recurring Tasks Due Today",
        *([f"  {t.name} ({t.schedule})" for t in due_tasks] or ["  (none)"]),
        "",
        "## Quick Capture Inbox (raw notes from iPhone — categorize and surface)",
        inbox_text if inbox_text else "  (empty)",
        "",
        "## Open Loop Summary",
        f"  Resolved since yesterday: {len(loop_summary.resolved_email_ids)} items",
        f"  Still open: {len(loop_summary.still_open_email_ids)} items",
    ]
    return "\n".join(sections)


def generate_brief(
    api_key: str,
    model: str,
    today_events: list[CalendarEvent],
    tomorrow_events: list[CalendarEvent],
    email_threads: list[EmailThread],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    open_issues: list[Issue] = None,
    personal_emails: list[PersonalEmail] = None,
    drafts: list[Draft] = None,
    meeting_prep: list[str] = None,
    inbox_text: str = "",
) -> BriefContent:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(
        today_events, tomorrow_events, email_threads, projects, due_tasks,
        loop_summary,
        open_issues or [],
        personal_emails or [],
        drafts or [],
        meeting_prep or [],
        inbox_text or "",
    )
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned non-JSON response: {e}\nRaw response: {raw[:200]}") from e
    return BriefContent(
        executive_summary=data.get("executive_summary", ""),
        top_3_priorities=data.get("top_3_priorities", []),
        watch_outs=data.get("watch_outs", []),
        schedule_notes=data.get("schedule_notes", ""),
        personal_items=data.get("personal_items", []),
        recurring_due=data.get("recurring_due", []),
        drafts_ready=data.get("drafts_ready", []),
        meeting_prep=data.get("meeting_prep", []),
    )
