import sys
from datetime import date
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

CANVAS_ANCHOR = "Chief of Staff — Task Board"


def setup_canvas(token: str, user_email: str, config_path: str = "config.json") -> dict:
    """One-time setup: open bot DM with user, create canvas, store IDs in config.json."""
    import json

    client = WebClient(token=token)

    user_resp = client.users_lookupByEmail(email=user_email)
    user_id = user_resp["user"]["id"]

    # Find existing DM channel — avoids needing im:write scope
    channel_id = None
    dm_list = client.conversations_list(types="im", limit=200)
    for ch in dm_list.get("channels", []):
        if ch.get("user") == user_id:
            channel_id = ch["id"]
            break

    if not channel_id:
        raise RuntimeError(
            "No DM channel found with this user. "
            "Send the bot a message in Slack first, then re-run this script."
        )

    markdown = _render([], [])
    canvas_resp = client.conversations_canvases_create(
        channel_id=channel_id,
        document_content={"type": "markdown", "markdown": markdown},
    )
    canvas_id = canvas_resp["canvas_id"]

    with open(config_path) as f:
        config_data = json.load(f)
    config_data["slack_canvas"] = {"canvas_id": canvas_id, "channel_id": channel_id}
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    return {"canvas_id": canvas_id, "channel_id": channel_id}


def sync_task_canvas(token: str, canvas_id: str, open_tasks: list, recent_completions: list) -> None:
    """Rewrite the task canvas with current state. Non-fatal on errors."""
    client = WebClient(token=token)
    markdown = _render(open_tasks, recent_completions)

    try:
        resp = client.canvases_sections_lookup(
            canvas_id=canvas_id,
            criteria={"contains_text": CANVAS_ANCHOR},
        )
        sections = resp.get("sections", [])
        if sections:
            client.canvases_edit(
                canvas_id=canvas_id,
                changes=[{
                    "operation": "replace",
                    "section_id": sections[0]["id"],
                    "document_content": {"type": "markdown", "markdown": markdown},
                }],
            )
            return
    except SlackApiError:
        pass

    # Anchor not found — insert fresh
    try:
        client.canvases_edit(
            canvas_id=canvas_id,
            changes=[{
                "operation": "insert_at_end",
                "document_content": {"type": "markdown", "markdown": markdown},
            }],
        )
    except SlackApiError as e:
        print(f"WARNING: canvas sync failed: {e}", file=sys.stderr)


def _render(open_tasks: list, recent_completions: list) -> str:
    lines = [f"# {CANVAS_ANCHOR}", "", f"*Updated {date.today().isoformat()}*", ""]
    lines.append("## Open")
    if open_tasks:
        for t in open_tasks:
            due = f" *(due {t['due_date']})*" if t.get("due_date") else ""
            lines.append(f"- [ ] {t['title']}{due}")
    else:
        lines.append("*No open tasks.*")
    if recent_completions:
        lines.extend(["", "## Completed This Week"])
        for t in recent_completions:
            lines.append(f"- [x] ~~{t['title']}~~ *(done {t['completed_at']})*")
    return "\n".join(lines)
