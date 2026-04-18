import anthropic
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from collectors.calendar import CalendarEvent


@dataclass
class Draft:
    subject: str
    body: str
    to: str
    draft_type: str
    context: str = ""
    created_date: str = field(default_factory=lambda: date.today().isoformat())


def _call_claude(api_key: str, model: str, prompt: str, max_tokens: int = 500) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _parse_draft(raw: str, fallback_to: str, draft_type: str, context: str = "") -> Optional[Draft]:
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    try:
        data = json.loads(raw)
        return Draft(
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            to=data.get("to", fallback_to),
            draft_type=draft_type,
            context=context,
        )
    except (json.JSONDecodeError, KeyError):
        return None


def generate_demo_followup(api_key: str, model: str, event: CalendarEvent) -> Optional[Draft]:
    if not event.attendees:
        return None
    to_email = event.attendees[0]
    prompt = f"""Write a warm, brief follow-up email after a sales demo call.

Meeting: {event.summary}
Time: {event.start.strftime('%B %-d at %-I:%M %p')}
Recipient email: {to_email}

Guidelines:
- 3-4 sentences max
- Thank them for their time
- Mention you'll send over next steps or resources
- Warm but professional tone, not salesy
- Use [Name] as placeholder for their first name

Respond with JSON only: {{"subject": "...", "body": "...", "to": "{to_email}"}}"""

    raw = _call_claude(api_key, model, prompt)
    draft = _parse_draft(raw, to_email, "demo_followup", context=event.summary)
    if draft is not None:
        draft.to = to_email
    return draft


def generate_lead_outreach(
    api_key: str,
    model: str,
    lead_name: str,
    lead_email: str,
    gym_name: str,
    snippet: str = "",
) -> Optional[Draft]:
    prompt = f"""Write a short, personalized cold outreach email for a gym facility.

Lead: {lead_name}
Gym: {gym_name}
Email: {lead_email}
Context about their gym: {snippet or "no additional context"}
Product: TeamBuildr OS — strength and conditioning software for gym owners

Guidelines:
- 3-4 sentences max
- Reference something specific about their gym if context is available
- Soft pitch: invite them to learn more, not to buy
- Subject line should feel personal, not like a marketing blast
- Sign from Trent at TeamBuildr OS

Respond with JSON only: {{"subject": "...", "body": "...", "to": "{lead_email}"}}"""

    raw = _call_claude(api_key, model, prompt)
    return _parse_draft(raw, lead_email, "lead_outreach", context=gym_name)


def generate_trial_followup(
    api_key: str,
    model: str,
    lead_name: str,
    lead_email: str,
    days_in_trial: int,
) -> Optional[Draft]:
    prompt = f"""Write a brief check-in email for a trial user who hasn't responded.

Lead: {lead_name}
Email: {lead_email}
Days in trial: {days_in_trial}
Product: TeamBuildr OS

Guidelines:
- 2-3 sentences max
- No pressure — just checking in and offering help
- Ask one simple open-ended question to start a conversation
- Sign from Trent

Respond with JSON only: {{"subject": "...", "body": "...", "to": "{lead_email}"}}"""

    raw = _call_claude(api_key, model, prompt)
    return _parse_draft(raw, lead_email, "trial_followup", context=f"{days_in_trial}d in trial")


def save_draft(draft: Draft, drafts_dir: str) -> str:
    os.makedirs(drafts_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    filename = f"{draft.draft_type}_{date.today().isoformat()}_{timestamp}.json"
    path = os.path.join(drafts_dir, filename)
    with open(path, "w") as f:
        json.dump({
            "subject": draft.subject, "body": draft.body, "to": draft.to,
            "draft_type": draft.draft_type, "context": draft.context,
            "created_date": draft.created_date,
        }, f, indent=2)
    return path


def load_todays_drafts(drafts_dir: str) -> list[Draft]:
    today = date.today().isoformat()
    drafts = []
    try:
        for filename in sorted(os.listdir(drafts_dir)):
            if today in filename and filename.endswith(".json"):
                with open(os.path.join(drafts_dir, filename)) as f:
                    data = json.load(f)
                drafts.append(Draft(**data))
    except FileNotFoundError:
        pass
    return drafts
