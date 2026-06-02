"""Phase 2 Avoma conversation handler — Q&A and gate-confirmed corrections.

After Phase 1 posts output to the thread, subsequent replies route here.
Claude gets the Phase 1 output and transcript analysis as context.

- Questions → text answer posted to thread; no writes.
- Edit requests → Claude calls propose_correction; bot posts proposal;
  pending_correction written to state. A confirmation applies writes.
- "no"/"cancel" → clears pending_correction.

Correction write routing:
  observation_correction → append new correction-type obs to observations.jsonl
  people_file → append correction block in place to data/people/<file>.md
  payload → Notion paste block re-posted (no file write; it's paste-only)
"""

from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path

import anthropic

from lib.slack_post import post_to_thread
from processors.avoma_thread_state import set_pending_correction, clear_pending_correction

_OBS_KEY = "memory/observations.jsonl"

_SYSTEM_PROMPT = (
    "You are Trent Luecke's AI Chief of Staff. A sales call was just analyzed and the output "
    "was posted to the thread. Trent has replied with a question or a correction.\n\n"
    "If it's a question about the call: answer directly and concisely from the data provided.\n"
    "If it's an edit or correction: call propose_correction with a precise description of what "
    "would change and where. Be specific: name the target (observation log, people file path, "
    "or Notion payload). If the Notion payload block would change, include a corrected version "
    "in notion_payload. confirmation_prompt should say exactly what Trent needs to reply to confirm.\n\n"
    "No preamble. Be concise."
)

_PROPOSE_TOOL = {
    "name": "propose_correction",
    "description": "Propose a write that requires Trent's confirmation before applying.",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Plain English: what changes, where, and why.",
            },
            "writes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["observation_correction", "people_file", "payload"],
                        },
                        "target": {
                            "type": "string",
                            "description": "observations.jsonl, people file path, or 'notion_payload'",
                        },
                        "value": {"type": "string", "description": "The correction or new value."},
                    },
                    "required": ["type", "target", "value"],
                },
            },
            "notion_payload": {
                "type": ["string", "null"],
                "description": "Corrected Notion paste block if the payload is affected, else null.",
            },
            "confirmation_prompt": {
                "type": "string",
                "description": "Message asking Trent to confirm, e.g. 'Reply yes to apply this correction.'",
            },
        },
        "required": ["description", "writes", "notion_payload", "confirmation_prompt"],
    },
}

_CONFIRMATIONS = frozenset({"yes", "confirm", "confirmed", "ok", "apply", "do it", "yep", "yeah"})
_REJECTIONS = frozenset({"no", "cancel", "nevermind", "never mind", "skip", "nope", "don't"})


def run_phase2(
    thread_ts: str,
    trigger_text: str,
    state_record: dict,
    slack_bot_token: str,
    channel_id: str,
    storage,
    config: dict,
    anthropic_api_key: str,
) -> None:
    """Handle a Phase 2 message. Routes to pending correction check or fresh Claude call."""
    pending = state_record.get("pending_correction")
    trigger_lower = trigger_text.strip().lower()

    if pending and trigger_lower in _CONFIRMATIONS:
        _apply_correction(pending, state_record, storage, slack_bot_token, channel_id, thread_ts)
        clear_pending_correction(storage, thread_ts)
        return

    if pending and trigger_lower in _REJECTIONS:
        post_to_thread(slack_bot_token, channel_id, thread_ts, "Correction cancelled.")
        clear_pending_correction(storage, thread_ts)
        return

    _handle_fresh_message(thread_ts, trigger_text, state_record, slack_bot_token, channel_id, storage, config, anthropic_api_key)


def _handle_fresh_message(
    thread_ts: str,
    trigger_text: str,
    state_record: dict,
    slack_bot_token: str,
    channel_id: str,
    storage,
    config: dict,
    anthropic_api_key: str,
) -> None:
    phase1_output = state_record.get("phase1_output", "")
    transcript_json = state_record.get("transcript_json", {})
    model = config.get("ai_model", "claude-sonnet-4-6")

    user_content = (
        f"## Phase 1 Output\n{phase1_output}\n\n"
        f"## Call Analysis\n{json.dumps(transcript_json, indent=2)}\n\n"
        f"## Trent's message\n{trigger_text}"
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        system=_SYSTEM_PROMPT,
        tools=[_PROPOSE_TOOL],
        messages=[{"role": "user", "content": user_content}],
    )

    correction_input = None
    text_response = ""
    for block in response.content:
        if block.type == "tool_use" and block.name == "propose_correction":
            correction_input = block.input
        elif block.type == "text":
            text_response = block.text.strip()

    if correction_input:
        set_pending_correction(storage, thread_ts, {
            "description": correction_input["description"],
            "writes": correction_input["writes"],
            "notion_payload": correction_input.get("notion_payload"),
            "confirmation_prompt": correction_input["confirmation_prompt"],
        })
        msg = f"Proposed correction: {correction_input['description']}\n\n{correction_input['confirmation_prompt']}"
        if correction_input.get("notion_payload"):
            msg += f"\n\n{correction_input['notion_payload']}"
        post_to_thread(slack_bot_token, channel_id, thread_ts, msg)
    else:
        post_to_thread(slack_bot_token, channel_id, thread_ts, text_response or "(no response)")


def _apply_correction(
    pending: dict,
    state_record: dict,
    storage,
    slack_bot_token: str,
    channel_id: str,
    thread_ts: str,
) -> None:
    applied: list[str] = []

    for write in pending.get("writes", []):
        write_type = write.get("type")
        target = write.get("target", "")
        value = write.get("value", "")

        if write_type == "observation_correction":
            _append_correction_obs(storage, state_record.get("avoma_uuid"), pending["description"], value)
            applied.append("appended correction observation")

        elif write_type == "people_file":
            _apply_people_file_write(target, value)
            applied.append(f"updated {target}")

        elif write_type == "payload":
            applied.append("Notion payload noted (paste manually)")

    if pending.get("notion_payload"):
        ack = f"Correction applied ({'; '.join(applied)}).\n\nCorrected Notion payload:\n{pending['notion_payload']}"
    else:
        ack = f"Correction applied: {'; '.join(applied) or 'no writes'}."

    post_to_thread(slack_bot_token, channel_id, thread_ts, ack)


def _append_correction_obs(storage, supersedes_uuid: str | None, description: str, value: str) -> None:
    obs = {
        "date": date.today().isoformat(),
        "source": "avoma_correction",
        "type": "correction",
        "supersedes_uuid": supersedes_uuid,
        "content": f"Correction to call analysis: {description}. {value}",
        "primary_person_id": None,
    }
    storage.append_line(_OBS_KEY, json.dumps(obs))


def _apply_people_file_write(target_path: str, value: str) -> None:
    path = Path(target_path)
    if not path.exists():
        print(f"WARNING: people file not found: {target_path}", file=sys.stderr)
        return
    current = path.read_text(encoding="utf-8")
    block = f"\n\n## Correction ({date.today().isoformat()})\n{value}\n"
    path.write_text(current + block, encoding="utf-8")
