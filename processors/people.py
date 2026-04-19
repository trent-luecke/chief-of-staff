import re
import os
import json
import tempfile
from pathlib import Path
from datetime import date

import anthropic

MARKER = "<!-- AUTO-UPDATED: do not edit below this line -->"
MAX_ROUTINE = 5


def build_email_index(people_dir: str) -> dict[str, str]:
    """Scan *.md in people_dir; return {email_lower: filepath} for files with **Email:** fields."""
    if not Path(people_dir).is_dir():
        return {}
    index = {}
    for path in Path(people_dir).glob("*.md"):
        content = path.read_text()
        m = re.search(r'\*\*Email:\*\*\s*([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})', content, re.IGNORECASE)
        if m:
            index[m.group(1).lower()] = str(path)
    return index


def read_auto_section(filepath: str) -> dict:
    """Parse the machine-written section. Returns {"significant": [...], "routine": [...], "open_threads": [...]}."""
    content = Path(filepath).read_text()
    if MARKER not in content:
        return {"significant": [], "routine": [], "open_threads": []}

    auto = content.split(MARKER, 1)[1]

    def _extract_list(header: str, text: str) -> list[str]:
        pattern = rf'\*\*{re.escape(header)}\*\*(.*?)(?=\n\*\*|\Z)'
        m = re.search(pattern, text, re.DOTALL)
        if not m:
            return []
        lines = []
        for line in m.group(1).strip().splitlines():
            line = line.strip()
            if line.startswith("- "):
                line = line[2:]
            if line and line != "(none)":
                lines.append(line)
        return lines

    return {
        "significant": _extract_list("Significant touchpoints:", auto),
        "routine": _extract_list(f"Recent touchpoints (last {MAX_ROUTINE}):", auto),
        "open_threads": _extract_list("Open threads:", auto),
    }


def write_auto_section(
    filepath: str,
    significant: list[str],
    routine: list[str],
    open_threads: list[str],
) -> None:
    """Replace everything from MARKER onward. The human section above is never touched."""
    content = Path(filepath).read_text()
    human_part = content.split(MARKER, 1)[0].rstrip()
    today = date.today().isoformat()

    lines = ["", MARKER, "## Activity", f"**Last seen:** {today}", ""]

    lines.append("**Significant touchpoints:**")
    for tp in significant:
        lines.append(f"- {tp}")
    if not significant:
        lines.append("- (none)")
    lines.append("")

    lines.append(f"**Recent touchpoints (last {MAX_ROUTINE}):**")
    for tp in routine[:MAX_ROUTINE]:
        lines.append(f"- {tp}")
    if not routine:
        lines.append("- (none)")
    lines.append("")

    lines.append("**Open threads:**")
    for t in open_threads:
        lines.append(f"- {t}")
    if not open_threads:
        lines.append("- (none)")
    lines.append("")

    new_content = human_part + "\n" + "\n".join(lines)

    # Atomic write: write to temp file then rename to avoid partial writes on crash
    path = Path(filepath)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(new_content)
        os.replace(tmp_path, filepath)
    except Exception:
        os.unlink(tmp_path)
        raise


def _extract_email(sender: str) -> str:
    """Extract bare email from 'Display Name <email>' or return input unchanged."""
    m = re.search(r'<([^>]+)>', sender)
    return m.group(1).strip() if m else sender.strip()


def _assess_with_claude(
    touchpoints_by_file: dict[str, list[dict]],
    unmatched_dms: list,
    api_key: str,
    model: str,
) -> dict:
    """One Claude call per run. Returns {"touchpoint_assessments": [...], "new_profiles": [...]}."""
    if not touchpoints_by_file and not unmatched_dms:
        return {"touchpoint_assessments": [], "new_profiles": []}

    tp_list = []
    for filepath, tps in touchpoints_by_file.items():
        for tp in tps:
            tp_list.append({
                "key": tp["subject"],
                "filepath": filepath,
                "date": tp["date"],
                "source": tp["source"],
                "subject": tp["subject"],
            })

    dm_list = [
        {
            "user_id": dm.user_id,
            "display_name": dm.display_name,
            "email": dm.email,
            "messages": dm.messages[:3],
        }
        for dm in unmatched_dms
    ]

    prompt = f"""Assess the following for the chief-of-staff people store.

TOUCHPOINTS (new interactions to assess for significance):
{json.dumps(tp_list, indent=2)}

For each touchpoint, decide if it is SIGNIFICANT: does it contain an open deliverable, stated commitment, key decision, or follow-up dependency? Return only touchpoints that ARE significant.

UNMATCHED SLACK DMS (people with no existing profile):
{json.dumps(dm_list, indent=2)}

For each Slack DM, decide if this person is worth tracking (recurring relationship, pending deliverable, or follow-up needed).

Respond ONLY in JSON:
{{
  "touchpoint_assessments": [
    {{"key": "<key from input>", "filepath": "<filepath>", "significant": true, "reason": "<one line>"}}
  ],
  "new_profiles": [
    {{"user_id": "<id>", "worth_tracking": true, "suggested_filename": "firstname-lastname.md",
       "display_name": "<name>", "email": "<email>", "reason": "<one line>"}}
  ]
}}

Only include items where significant/worth_tracking is true. Empty arrays are fine."""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    m = re.search(r'```(?:json)?\n?(.*?)```', raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"touchpoint_assessments": [], "new_profiles": []}


def _create_profile(profile_data: dict, people_dir: str) -> None:
    """Create a new contact file pre-populated with Slack data. Human sections left empty."""
    filename = profile_data.get("suggested_filename", f"{profile_data.get('user_id', 'unknown')}.md")
    filepath = Path(people_dir) / filename
    if filepath.exists():
        return
    display_name = profile_data.get("display_name", profile_data.get("user_id", "Unknown"))
    email = profile_data.get("email", "")
    user_id = profile_data.get("user_id", "")
    content = f"# {display_name}\n\n"
    if email:
        content += f"**Email:** {email}\n"
    if user_id:
        content += f"**Slack user ID:** {user_id}\n"
    content += "\n## Relationship\n\n## Notes\n"
    filepath.write_text(content)


def enrich_people(
    calendar_events: list,
    email_threads: list,
    slack_dms: list,
    people_dir: str,
    api_key: str,
    model: str,
) -> str:
    """Enrich contact files and return people context string for the brief prompt."""
    index = build_email_index(people_dir)
    today = date.today().isoformat()

    matched_files: set[str] = set()
    new_touchpoints: dict[str, list[dict]] = {}
    new_open_threads: dict[str, list[str]] = {}
    unmatched_dms = []

    for event in calendar_events:
        for attendee_email in event.attendees:
            filepath = index.get(attendee_email.lower())
            if filepath:
                matched_files.add(filepath)
                new_touchpoints.setdefault(filepath, []).append(
                    {"date": today, "source": "calendar", "subject": event.summary}
                )

    for thread in email_threads:
        email = _extract_email(thread.last_sender).lower()
        filepath = index.get(email)
        if filepath:
            matched_files.add(filepath)
            new_touchpoints.setdefault(filepath, []).append(
                {"date": today, "source": "email", "subject": thread.subject}
            )
            if thread.needs_reply:
                new_open_threads.setdefault(filepath, []).append(
                    f'"{thread.subject}" — needs reply'
                )

    for dm in slack_dms:
        if dm.email:
            filepath = index.get(dm.email.lower())
            if filepath:
                matched_files.add(filepath)
                preview = dm.messages[0][:60] if dm.messages else "DM"
                new_touchpoints.setdefault(filepath, []).append(
                    {"date": today, "source": "slack", "subject": preview}
                )
            else:
                unmatched_dms.append(dm)

    assessment = _assess_with_claude(new_touchpoints, unmatched_dms, api_key, model)

    sig_by_file: dict[str, list[str]] = {}
    sig_subjects_by_file: dict[str, set[str]] = {}
    for hit in assessment.get("touchpoint_assessments", []):
        fp = hit.get("filepath", "")
        reason = hit.get("reason", "")
        key = hit.get("key", "")
        for tp in new_touchpoints.get(fp, []):
            if tp["subject"] == key:
                tp_str = f"{tp['date']} | {tp['source']} | \"{tp['subject']}\""
                if reason:
                    tp_str += f" | {reason}"
                sig_by_file.setdefault(fp, []).append(tp_str)
                sig_subjects_by_file.setdefault(fp, set()).add(tp["subject"])
                break

    for filepath in matched_files:
        if not Path(filepath).exists():
            continue
        existing = read_auto_section(filepath)
        significant = list(existing["significant"]) + sig_by_file.get(filepath, [])
        sig_subjects = sig_subjects_by_file.get(filepath, set())
        routine_new = [
            f"{tp['date']} | {tp['source']} | \"{tp['subject']}\""
            for tp in new_touchpoints.get(filepath, [])
            if tp["subject"] not in sig_subjects
        ]
        routine = (routine_new + existing["routine"])[:MAX_ROUTINE]
        open_threads = new_open_threads.get(filepath, []) + [
            t for t in existing["open_threads"]
            if t not in new_open_threads.get(filepath, [])
        ]
        write_auto_section(filepath, significant, routine, open_threads)

    for profile_data in assessment.get("new_profiles", []):
        if profile_data.get("worth_tracking"):
            _create_profile(profile_data, people_dir)
            new_path = str(Path(people_dir) / profile_data.get("suggested_filename", ""))
            if Path(new_path).exists():
                matched_files.add(new_path)

    context_parts = []
    for filepath in sorted(matched_files):
        if Path(filepath).exists():
            context_parts.append(Path(filepath).read_text())

    return "\n\n---\n\n".join(context_parts)
