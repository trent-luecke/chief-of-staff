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
import re
import sys
from datetime import date
from pathlib import Path

import anthropic

from lib.slack_post import post_to_thread
from lib.tasks import add_task
from processors.avoma_thread_state import (
    set_pending_correction, clear_pending_correction,
    set_pending_project_link, clear_pending_project_link,
)
from processors.query_tools import _sync_canvas

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

_PROPOSE_PROJECT_LINK_TOOL = {
    "name": "propose_project_link",
    "description": (
        "Suggest linking this call's observation to one or more existing projects. "
        "ONLY call this when a call participant is a known member of the project. "
        "Do NOT invent links. Bias hard toward missing a link over making a false one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "project_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "IDs of existing projects this call plausibly relates to.",
            },
            "rationale": {
                "type": "string",
                "description": "One sentence: which participant triggered the match and why.",
            },
        },
        "required": ["project_ids", "rationale"],
    },
}

_CONFIRMATIONS = frozenset({"yes", "confirm", "confirmed", "ok", "apply", "do it", "yep", "yeah"})
_REJECTIONS = frozenset({"no", "cancel", "nevermind", "never mind", "skip", "nope", "don't"})

_TASK_ADD_PATTERN = re.compile(
    r"^add\s+(all|\d[\d,\s]*(?:and\s+\d[\d,\s]*)*)$",
    re.IGNORECASE,
)


def _is_task_selection(text: str) -> bool:
    return bool(_TASK_ADD_PATTERN.match(text.strip()))


def _parse_task_indices(trigger_text: str, action_items: list) -> list[str]:
    """Return the action item strings selected by an 'add N [, M ...]' message."""
    m = re.match(r"^add\s+(.+)$", trigger_text.strip(), re.IGNORECASE)
    if not m:
        return []
    arg = m.group(1).strip().lower()
    if arg == "all":
        return list(action_items)
    # Normalise "and" to space so "1 and 3" → "1   3"
    arg = arg.replace("and", " ")
    indices = list(dict.fromkeys(int(n) - 1 for n in re.split(r"[,\s]+", arg) if n.strip().isdigit()))
    return [action_items[i] for i in indices if 0 <= i < len(action_items)]


def _handle_task_selection(
    thread_ts: str,
    trigger_text: str,
    state_record: dict,
    slack_bot_token: str,
    channel_id: str,
    storage,
    config: dict,
) -> None:
    transcript_json = state_record.get("transcript_json", {})
    action_items = transcript_json.get("action_items") or []
    selected = _parse_task_indices(trigger_text, action_items)

    if not selected:
        post_to_thread(slack_bot_token, channel_id, thread_ts, "No tasks added (no matching action items).")
        return

    metadata = {
        "avoma_uuid": state_record.get("avoma_uuid"),
        "thread_ts": thread_ts,
        "call_title": transcript_json.get("title", ""),
        "call_date": (transcript_json.get("start_at") or "")[:10],
    }
    for item in selected:
        add_task(storage, item, source="avoma", metadata=metadata)

    _sync_canvas(config, storage)

    count = len(selected)
    noun = "task" if count == 1 else "tasks"
    items_display = "\n".join(f"  ✓ {t}" for t in selected)
    post_to_thread(
        slack_bot_token, channel_id, thread_ts,
        f"Added {count} {noun}, canvas synced.\n{items_display}",
    )


def _project_context_block(storage) -> str:
    from lib.projects import list_projects
    try:
        projects = list_projects(storage, status="active")
        if not projects:
            return ""
        lines = ["## Active Projects (for link consideration)"]
        for p in projects:
            member_ids = [m["person_id"] for m in p.get("members", [])]
            lines.append(
                f"- id={p['id']}  name={p['canonical_name']}"
                f"  members={', '.join(member_ids) or 'none'}"
            )
        return "\n".join(lines)
    except Exception:
        return ""


def _handle_project_link_proposal(
    proposal: dict,
    state_record: dict,
    thread_ts: str,
    storage,
    slack_bot_token: str,
    channel_id: str,
) -> None:
    from lib.project_candidates import flag_candidate
    from processors.avoma_thread_state import set_pending_project_link

    transcript_json = state_record.get("transcript_json", {})
    obs_date = (transcript_json.get("start_at") or "")[:10] or date.today().isoformat()
    obs_entity = state_record.get("avoma_uuid") or thread_ts
    call_title = transcript_json.get("title", "")

    candidate_ids = []
    try:
        for pid in proposal.get("project_ids", []):
            c = flag_candidate(
                storage,
                project_id=pid,
                obs_date=obs_date,
                obs_entity=obs_entity,
                source_thread_ts=thread_ts,
                call_title=call_title,
            )
            candidate_ids.append(c["id"])

        if proposal.get("project_ids"):
            set_pending_project_link(storage, thread_ts, {
                "candidate_ids": candidate_ids,
                "project_ids": proposal["project_ids"],
                "obs_date": obs_date,
                "obs_entity": obs_entity,
                "call_title": call_title,
                "confirmation_prompt": "Reply 'yes' to link, 'no' to dismiss.",
            })
    except Exception:
        from lib.project_candidates import resolve_candidate as _resolve
        for cid in candidate_ids:
            _resolve(storage, cid, "dismissed")
        post_to_thread(slack_bot_token, channel_id, thread_ts,
                       "Failed to propose project link — please try again.")
        return

    projects_str = ", ".join(proposal["project_ids"])
    msg = (
        f"Project link suggested: {projects_str}\n"
        f"Reason: {proposal['rationale']}\n\n"
        "Reply 'yes' to confirm or 'no' to dismiss."
    )
    post_to_thread(slack_bot_token, channel_id, thread_ts, msg)


def _apply_project_link(
    pending_link: dict,
    storage,
    slack_bot_token: str,
    channel_id: str,
    thread_ts: str,
) -> None:
    from lib.project_candidates import resolve_candidate
    from lib.project_links import add_link

    obs_date = pending_link["obs_date"]
    obs_entity = pending_link["obs_entity"]
    call_title = pending_link["call_title"]
    applied = []

    for pid, cid in zip(
        pending_link.get("project_ids", []),
        pending_link.get("candidate_ids", []),
    ):
        add_link(
            storage,
            project_id=pid,
            obs_date=obs_date,
            obs_entity=obs_entity,
            source_thread_ts=thread_ts,
            call_title=call_title,
        )
        resolve_candidate(storage, cid, "confirmed")
        applied.append(pid)

    post_to_thread(
        slack_bot_token, channel_id, thread_ts,
        f"Linked to: {', '.join(applied)}.",
    )


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

    pending_link = state_record.get("pending_project_link")

    if pending_link and trigger_lower in _CONFIRMATIONS:
        try:
            _apply_project_link(pending_link, storage, slack_bot_token, channel_id, thread_ts)
        finally:
            clear_pending_project_link(storage, thread_ts)
        return

    if pending_link and trigger_lower in _REJECTIONS:
        from lib.project_candidates import resolve_candidate
        for cid in pending_link.get("candidate_ids", []):
            resolve_candidate(storage, cid, "dismissed")
        clear_pending_project_link(storage, thread_ts)
        post_to_thread(slack_bot_token, channel_id, thread_ts, "Project link dismissed.")
        return

    if pending and trigger_lower in _CONFIRMATIONS:
        _apply_correction(pending, state_record, storage, slack_bot_token, channel_id, thread_ts)
        clear_pending_correction(storage, thread_ts)
        return

    if pending and trigger_lower in _REJECTIONS:
        post_to_thread(slack_bot_token, channel_id, thread_ts, "Correction cancelled.")
        clear_pending_correction(storage, thread_ts)
        return

    if _is_task_selection(trigger_text):
        if pending:
            post_to_thread(
                slack_bot_token, channel_id, thread_ts,
                "There's a pending correction. Reply 'yes' to apply or 'no' to cancel it first.",
            )
            return
        _handle_task_selection(thread_ts, trigger_text, state_record, slack_bot_token, channel_id, storage, config)
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

    proj_ctx = _project_context_block(storage)
    user_content = (
        (proj_ctx + "\n\n") if proj_ctx else ""
    ) + (
        f"## Phase 1 Output\n{phase1_output}\n\n"
        f"## Call Analysis\n{json.dumps(transcript_json, indent=2)}\n\n"
        f"## Trent's message\n{trigger_text}"
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        system=_SYSTEM_PROMPT,
        tools=[_PROPOSE_TOOL, _PROPOSE_PROJECT_LINK_TOOL],
        messages=[{"role": "user", "content": user_content}],
    )

    correction_input = None
    project_link_input = None
    text_response = ""
    for block in response.content:
        if block.type == "tool_use" and block.name == "propose_correction":
            correction_input = block.input
        elif block.type == "tool_use" and block.name == "propose_project_link":
            project_link_input = block.input
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
        return

    if project_link_input:
        _handle_project_link_proposal(
            project_link_input, state_record, thread_ts, storage,
            slack_bot_token, channel_id,
        )
        return

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
