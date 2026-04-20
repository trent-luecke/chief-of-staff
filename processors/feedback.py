from dataclasses import dataclass
from typing import Literal, Optional
import json
import os
import re
from datetime import datetime
import anthropic


@dataclass
class FeedbackResult:
    classification: Literal["action_signal", "delivery_note", "unclear"]
    capture_type: Optional[str]
    capture_target: Optional[str]
    capture_content: Optional[str]
    delivery_note: Optional[str]
    clarification_question: Optional[str]


def classify_feedback(api_key: str, model: str, reply_body: str, brief_subject: str) -> FeedbackResult:
    client = anthropic.Anthropic(api_key=api_key)
    system = """You classify email replies to a morning brief as feedback.

Three categories:
- action_signal: reactive instruction about something in the brief ("ignore that email", "elevate Apex", "flag Marcus as urgent")
- delivery_note: instruction about how future briefs should be formatted or prioritized ("executive summary too long", "cut gym scout section")
- unclear: can't determine intent

Respond with JSON only, no other text.

Schema:
{
  "classification": "action_signal|delivery_note|unclear",
  "capture_type": "flag|todo|note|idea or null",
  "capture_target": "person/company name or null",
  "capture_content": "what the action is or null",
  "delivery_note": "the tuning instruction in clear imperative form or null",
  "clarification_question": "what to ask the user if unclear, or null"
}"""

    try:
        message = client.messages.create(
            model=model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": f"Brief subject: {brief_subject}\n\nReply: {reply_body}"}],
        )
        raw = message.content[0].text.strip()
        m = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
        data = json.loads(m.group(1).strip() if m else raw)
        return FeedbackResult(
            classification=data.get("classification", "unclear"),
            capture_type=data.get("capture_type"),
            capture_target=data.get("capture_target"),
            capture_content=data.get("capture_content"),
            delivery_note=data.get("delivery_note"),
            clarification_question=data.get("clarification_question"),
        )
    except Exception:
        return FeedbackResult(
            classification="unclear",
            capture_type=None,
            capture_target=None,
            capture_content=None,
            delivery_note=None,
            clarification_question="Sorry, I couldn't parse your feedback. Could you rephrase?",
        )


def append_brief_feedback(feedback_file: str, note: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d")
    line = f"## {timestamp} — {note}\n"
    dir_ = os.path.dirname(feedback_file)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    with open(feedback_file, "a") as f:
        f.write(line)
