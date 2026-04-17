import json
import re
import anthropic
from dataclasses import dataclass, field
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.local_data import Project, RecurringTask
from processors.loops import LoopSummary


SYSTEM_PROMPT = """\
You are an AI Chief of Staff for Trent Luecke, VP of Sales at TeamBuildr OS \
(a B2B SaaS company serving strength & conditioning coaches). \
Your job is to deliver a sharp, actionable morning brief.

Be direct. No filler. Prioritize ruthlessly. Surface only what matters for today.
Respond in JSON with exactly these keys:
- executive_summary: 2-3 sentence synthesis of the day ahead
- top_3_priorities: list of exactly 3 action items, ordered by importance
- watch_outs: list of 0-3 risks or things that could go wrong today
- schedule_notes: one sentence about schedule shape (back-to-backs, gaps, etc.)
"""


@dataclass
class BriefContent:
    executive_summary: str
    top_3_priorities: list[str] = field(default_factory=list)
    watch_outs: list[str] = field(default_factory=list)
    schedule_notes: str = ""


def _build_prompt(
    today_events: list[CalendarEvent],
    tomorrow_events: list[CalendarEvent],
    email_threads: list[EmailThread],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
) -> str:
    def fmt_event(e: CalendarEvent) -> str:
        time = e.start.strftime("%I:%M%p").lstrip("0")
        return f"  {time} — {e.summary}"

    def fmt_email(t: EmailThread) -> str:
        return f"  {t.subject} from {t.last_sender}"

    sections = [
        "## Today's Calendar",
        *([fmt_event(e) for e in today_events] or ["  (no events)"]),
        "",
        "## Tomorrow's Preview",
        *([fmt_event(e) for e in tomorrow_events] or ["  (no events)"]),
        "",
        "## Emails Needing Attention",
        *([fmt_email(t) for t in email_threads] or ["  (none)"]),
        "",
        "## Open Loops",
        f"  Resolved since yesterday: {len(loop_summary.resolved_email_ids)} emails, "
        f"{len(loop_summary.resolved_notion_ids)} inbox items",
        f"  Still open from prior days: {len(loop_summary.still_open_email_ids)} emails, "
        f"{len(loop_summary.still_open_notion_ids)} inbox items",
        f"  New today: {len(loop_summary.new_email_loops)} emails, "
        f"{len(loop_summary.new_notion_loops)} inbox items",
        "",
        "## Active Projects",
        *([f"  {p.name} [{p.status}] — Next: {p.next_step}" for p in projects] or ["  (none)"]),
        "",
        "## Recurring Tasks Due Today",
        *([f"  {t.name} ({t.schedule})" for t in due_tasks] or ["  (none)"]),
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
) -> BriefContent:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(
        today_events, tomorrow_events, email_threads, projects, due_tasks, loop_summary
    )

    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    # Strip markdown code block if present
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()

    data = json.loads(raw)
    return BriefContent(
        executive_summary=data.get("executive_summary", ""),
        top_3_priorities=data.get("top_3_priorities", []),
        watch_outs=data.get("watch_outs", []),
        schedule_notes=data.get("schedule_notes", ""),
    )
