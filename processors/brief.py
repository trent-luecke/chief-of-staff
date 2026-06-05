import json
import re
from datetime import date
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

Deliver a morning brief readable in ~2 minutes. Two blocks only (metric flags are pre-computed and not your responsibility).

act_today — everything that needs Trent today. Collapse priorities, watch-outs, drafts, meeting prep, and pipeline attention into one ruthlessly prioritized list. Max 7 items. Each item is a plain action sentence with context and urgency woven in naturally — no brackets, no source tags. Multi-day open issues and customer-facing problems are highest priority. Issues with age (from the Open Issues section) belong here as plain sentences: "The Midwest deal has been stalled 3 days — follow up today." Omit if genuinely nothing to do.

what_moved — read-only awareness of what changed since yesterday. Only restate items from the "What Moved Yesterday" section of the prompt. Do not invent or infer events not listed there. One plain sentence per item, past tense. If no events section was provided, return an empty list. Max 7 items.

Respond ONLY in JSON with these exact keys:
{
  "act_today": ["action items as plain sentences — context and urgency woven in"],
  "what_moved": ["read-only awareness items, past tense, one sentence each"]
}
"""


@dataclass
class BriefContent:
    act_today: list[str] = field(default_factory=list)
    what_moved: list[str] = field(default_factory=list)
    metric_flags: list[str] = field(default_factory=list)


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
    brief_prefs_context: str = "",
    storage=None,
    what_moved_context: str = "",
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

    sections = [f"## Today's Date\n{date.today().strftime('%A, %B %-d, %Y')} (use this as the authoritative date — any memory referencing past dates is historical context, not upcoming)\n"]

    if brief_feedback_context:
        sections += [
            "## Delivery Instructions (from your feedback — follow these when writing the brief)",
            brief_feedback_context,
            "",
        ]
    if brief_prefs_context:
        sections += [
            "## Active Brief Preferences (follow these when writing the brief)",
            brief_prefs_context,
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
    def fmt_email(t: EmailThread) -> str:
        prefix = "[AWAITING REPLY] " if not t.needs_reply else ""
        snippet = f" — {t.snippet[:120]}" if t.snippet else ""
        return f"  {prefix}{t.subject} from {t.last_sender}{snippet}"

    sections += section("## Work Emails (last 24h)",
                        [fmt_email(t) for t in email_threads])
    sections += section("## Email Drafts Ready for Review",
                        [fmt_draft(d) for d in drafts])
    sections += section("## Meeting Prep (internal meetings today)",
                        [f"  {m}" for m in meeting_prep])
    sections += section("## Active Projects",
                        [f"  {p.name} [{p.status}] — Next: {p.next_step}" for p in projects[:7]])

    # Structured projects from registry (tasks + recent call history)
    if storage is not None:
        try:
            from lib.projects import project_context_for_brief
            project_ctx = project_context_for_brief(storage)
            if project_ctx:
                proj_lines = []
                for entry in project_ctx:
                    p = entry["project"]
                    proj_lines.append(f"  ### {p['canonical_name']}")
                    if entry["open_tasks"]:
                        proj_lines.append("  Open tasks:")
                        for t in entry["open_tasks"]:
                            proj_lines.append(f"    - {t['title']}")
                    if entry["linked_obs"]:
                        recent = entry["linked_obs"][-3:]
                        proj_lines.append(f"  Recent calls ({len(entry['linked_obs'])} in last 14 days):")
                        for lk in recent:
                            proj_lines.append(f"    - {lk['call_title']} ({lk['obs_date']})")
                    proj_lines.append("")
                sections += section("## Structured Projects (tasks + recent calls)", proj_lines)
        except Exception:
            pass  # non-fatal — brief continues without this section

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
    if what_moved_context and what_moved_context.strip():
        sections += [what_moved_context, ""]
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
    brief_prefs_context: str = "",
    storage=None,
    metric_flags: list[str] = None,
    what_moved_context: str = "",
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
        brief_prefs_context=brief_prefs_context,
        storage=storage,
        what_moved_context=what_moved_context,
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
        act_today=data.get("act_today", []),
        what_moved=data.get("what_moved", []),
        metric_flags=metric_flags or [],
    )
