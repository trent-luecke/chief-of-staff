import json
import re
import anthropic
from dataclasses import dataclass, field
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.local_data import Project, RecurringTask
from collectors.pipeline import PipelineLead
from collectors.gym_scout import GymScoutLead
from processors.loops import LoopSummary
from processors.issues import Issue
from processors.drafts import Draft


SYSTEM_PROMPT = """\
You are an AI Chief of Staff for Trent Luecke — VP of Sales at TeamBuildr OS (B2B SaaS for strength and conditioning coaches) and founder of Vero (gym AI side project). You also help with his personal life, LinkedIn content, and a weekly content podcast.

Deliver a concise, actionable morning brief. Be direct. No filler. Prioritize ruthlessly. Omit sections with nothing meaningful to say.

Rules:
- Open issues from prior days appear in top_3_priorities with age and source: "[ISSUE: N days, Slack #channel] title"
- Issues are the highest-priority items if they are multi-day or involve customer-facing problems
- recurring_due lists tasks due today by name and cadence — do not bury these in priorities
- drafts_ready lists email drafts generated and waiting for review — just name and context
- personal_items lists any personal or life items needing attention — brief, not buried
- meeting_prep lists prep notes for internal meetings today — last session summary and open items
- inbox contains raw quick-capture notes from iPhone — surface urgent items in top_3_priorities, map ideas to active projects where relevant, flag anything actionable today
- pipeline_attention lists open opportunities that have gone cold or need a nudge — surface the highest-priority ones; trial follow-up drafts appear in drafts_ready
- gym_scout_leads lists new gym leads found this week — remind to check and send outreach drafts from the Gym Scout email

Respond ONLY in JSON with these exact keys:
{
  "executive_summary": "2-3 sentence synthesis of the day ahead",
  "top_3_priorities": ["3 action items, open issues called out with age and source"],
  "watch_outs": ["0-3 risks or things that could go wrong today"],
  "schedule_notes": "one sentence about schedule shape",
  "personal_items": ["personal email items needing attention, empty list if none"],
  "recurring_due": ["recurring tasks due today with cadence"],
  "drafts_ready": ["drafts ready to review and send"],
  "meeting_prep": ["prep notes for today's internal meetings, empty list if none"],
  "pipeline_attention": ["open pipeline opps needing a nudge, empty list if none"]
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
    pipeline_attention: list[str] = field(default_factory=list)


def _build_prompt(
    today_events: list[CalendarEvent],
    tomorrow_events: list[CalendarEvent],
    email_threads: list[EmailThread],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    open_issues: list[Issue],
    drafts: list[Draft],
    meeting_prep: list[str],
    inbox_text: str,
    attention_leads: list[PipelineLead] = None,
    gym_scout_leads: list[GymScoutLead] = None,
    people_context: str = "",
    memory_context: str = "",
    captures_context: str = "",
    brief_feedback_context: str = "",
) -> str:
    def fmt_event(e: CalendarEvent) -> str:
        return f"  {e.start.strftime('%I:%M%p').lstrip('0')} — {e.summary}"

    def fmt_issue(i: Issue) -> str:
        return f"  [{i.age_days}d, {i.source}#{i.channel}] {i.title} (status: {i.status})"

    def fmt_draft(d: Draft) -> str:
        return f"  {d.draft_type}: {d.context} → to {d.to}"

    def fmt_attention_lead(l: PipelineLead) -> str:
        days = f"{l.days_since_contact}d ago" if l.days_since_contact is not None else "no contact date"
        val = f"${l.estimated_value:,.0f}" if l.estimated_value else ""
        parts = [f"  {l.name}"]
        if l.contact:
            parts[0] += f" ({l.contact})"
        parts[0] += f" — {l.status}, last contacted {days}"
        if val:
            parts[0] += f", est. {val}"
        if l.stale:
            parts[0] += " [STALE]"
        return parts[0]

    def fmt_gym_lead(g: GymScoutLead) -> str:
        name = g.gym_name or "Unknown gym"
        loc = f" in {g.location}" if g.location else ""
        owner = f" (owner: {g.owner_name})" if g.owner_name else ""
        confidence = "confirmed" if g.match == "yes" else "possible"
        return f"  {name}{loc}{owner} — {confidence} ICP match, {g.category}"

    def section(header: str, lines: list[str]) -> list[str]:
        if not lines:
            return []
        return [header, *lines, ""]

    sections = []

    if brief_feedback_context:
        sections += [
            "## Delivery Instructions (from your feedback — follow these when writing the brief)",
            brief_feedback_context,
            "",
        ]
    if memory_context:
        sections += [memory_context, ""]
    if people_context:
        sections += [
            "## People Context (background — use to identify missed deliverables and add relationship context to existing sections, do not create a new section)",
            people_context,
            "",
        ]

    sections += section("## Open Issues (surface in priorities with age and source)",
                        [fmt_issue(i) for i in open_issues])
    sections += section("## Today's Calendar",
                        [fmt_event(e) for e in today_events])
    if tomorrow_events:
        sections += section("## Tomorrow Preview",
                            [fmt_event(e) for e in tomorrow_events])
    sections += section("## Work Emails Needing Attention",
                        [f"  {t.subject} from {t.last_sender}" for t in email_threads])
    sections += section("## Email Drafts Ready for Review",
                        [fmt_draft(d) for d in drafts])
    sections += section("## Meeting Prep (internal meetings today)",
                        [f"  {m}" for m in meeting_prep])
    sections += section("## Active Projects",
                        [f"  {p.name} [{p.status}] — Next: {p.next_step}" for p in projects[:7]])
    sections += section("## Recurring Tasks Due Today",
                        [f"  {t.name} ({t.schedule})" for t in due_tasks])
    if inbox_text and inbox_text.strip():
        sections += ["## Quick Capture Inbox (raw notes from iPhone — categorize and surface)",
                     inbox_text, ""]
    if captures_context and captures_context.strip():
        sections += ["## Action Captures (logged via Telegram — surface relevant items)",
                     captures_context, ""]
    sections += section("## Pipeline — Open Opps Needing Attention (gone cold or stalled)",
                        [fmt_attention_lead(l) for l in (attention_leads or [])])
    sections += section("## Gym Scout — New Leads This Week (outreach reminder)",
                        [fmt_gym_lead(g) for g in (gym_scout_leads or [])])

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
    drafts: list[Draft] = None,
    meeting_prep: list[str] = None,
    inbox_text: str = "",
    attention_leads: list[PipelineLead] = None,
    gym_scout_leads: list[GymScoutLead] = None,
    people_context: str = "",
    memory_context: str = "",
    captures_context: str = "",
    brief_feedback_context: str = "",
) -> BriefContent:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(
        today_events, tomorrow_events, email_threads, projects, due_tasks,
        loop_summary,
        open_issues or [],
        drafts or [],
        meeting_prep or [],
        inbox_text or "",
        attention_leads=attention_leads or [],
        gym_scout_leads=gym_scout_leads or [],
        people_context=people_context,
        memory_context=memory_context,
        captures_context=captures_context,
        brief_feedback_context=brief_feedback_context,
    )
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    from lib.llm_logger import log_usage
    log_usage("brief", response.usage, model)
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
        pipeline_attention=data.get("pipeline_attention", []),
    )
