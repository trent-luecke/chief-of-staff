#!/usr/bin/env python3
"""Add a note from a Slack slash command. Called by note_add.yml.

Mirrors scripts/slack_add_task.py. Person links use the same fuzzy-match +
interactive-disambiguation pattern as /task; project links use best-match-or-skip;
unknown tags are dropped (the tag vocabulary stays curated in the Registry UI).
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.storage import LocalStorage
from lib.notes import add_note


def _load(path: Path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def fuzzy_match_people(raw_name: str, registry_path: Path) -> list:
    """Return [{id, canonical_name}] for every person whose name/aliases match raw_name."""
    if not raw_name or not raw_name.strip():
        return []
    registry = _load(registry_path, {})
    needle = raw_name.lower()
    matches = []
    for person in registry.get("people", []):
        candidates = [person.get("canonical_name", "")] + person.get("aliases", [])
        if any(needle in c.lower() or c.lower() in needle for c in candidates if c):
            matches.append({"id": person["id"], "canonical_name": person.get("canonical_name", person["id"])})
    return matches


def best_match_project(raw_name: str, registry_path: Path):
    """Return {id, canonical_name} for the first project matching raw_name, else None."""
    if not raw_name or not raw_name.strip():
        return None
    registry = _load(registry_path, {})
    needle = raw_name.lower()
    for proj in registry.get("projects", []):
        candidates = [proj.get("canonical_name", "")] + proj.get("aliases", [])
        if any(needle in c.lower() or c.lower() in needle for c in candidates if c):
            return {"id": proj["id"], "canonical_name": proj.get("canonical_name", proj["id"])}
    return None


def resolve_tag(raw_tag: str, tags_path: Path):
    """Return (resolved_tag_id_or_None, dropped_tag_or_None).

    A known tag (case-insensitive) resolves; an unknown non-empty tag is dropped
    and returned (normalized) so the caller can mention it in the confirmation.
    """
    if not raw_tag or not raw_tag.strip():
        return (None, None)
    normalized = raw_tag.strip().upper().replace(" ", "_")
    tags = _load(tags_path, [])
    for t in tags:
        if t.get("id", "").upper() == normalized:
            return (t["id"], None)
    return (None, normalized)


def format_confirmation(body, person_name, project_name, tag, dropped_tag, project_missed=None):
    parts = [f"Note added: {body}"]
    if person_name:
        parts.append(f"→ {person_name}")
    if project_name:
        parts.append(f"⊕ {project_name}")
    if tag:
        parts.append(f"[{tag}]")
    line = " — ".join(parts)
    notices = []
    if dropped_tag:
        notices.append(f"tag {dropped_tag} not found, skipped")
    if project_missed:
        notices.append(f"no project match for '{project_missed}'")
    if notices:
        line += f" ({'; '.join(notices)})"
    return line


def _post_json(response_url: str, payload: dict) -> None:
    if not response_url:
        return
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        response_url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Warning: failed to post to Slack response_url: {e}", file=sys.stderr)


def post_to_slack(response_url: str, text: str, replace: bool = False) -> None:
    payload = {"response_type": "ephemeral", "text": text}
    if replace:
        payload["replace_original"] = True
    _post_json(response_url, payload)


def post_ambiguous_people(response_url, raw_name, matches, body, project_raw, tag):
    """Post interactive buttons (one per candidate person) for note person disambiguation."""
    if not response_url:
        print("Warning: missing response_url — cannot post interactive message", file=sys.stderr)
        return
    capped = matches[:4]
    overflow = f"\n_Showing first 4 of {len(matches)} matches._" if len(matches) > 4 else ""
    buttons = []
    for person in capped:
        value = json.dumps({"body": body, "project_raw": project_raw, "tag": tag,
                            "person_raw": person["canonical_name"]})
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": person["canonical_name"]},
            "action_id": f"link_note_person_{person['id']}",
            "value": value,
        })
    none_value = json.dumps({"body": body, "project_raw": project_raw, "tag": tag, "person_raw": ""})
    buttons.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "No person"},
        "action_id": "link_note_person_none",
        "value": none_value,
    })
    _post_json(response_url, {
        "response_type": "ephemeral",
        "text": f"Multiple matches for '{raw_name}' — who did you mean?",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"Multiple matches for *{raw_name}* — who did you mean?{overflow}"}},
            {"type": "actions", "elements": buttons},
        ],
    })


def main():
    body = os.environ.get("NOTE_BODY", "").strip()
    person_raw = os.environ.get("PERSON_RAW", "").strip()
    project_raw = os.environ.get("PROJECT_RAW", "").strip()
    tag_raw = os.environ.get("TAG_RAW", "").strip()
    response_url = os.environ.get("RESPONSE_URL", "")

    if not body:
        print("Error: NOTE_BODY is required", file=sys.stderr)
        sys.exit(1)

    data_dir = ROOT / "data"
    people_path = data_dir / "people_registry.json"
    projects_path = data_dir / "projects_registry.json"
    tags_path = data_dir / "notes_tags.json"

    # Person: fuzzy match; ambiguous → buttons (note not created yet)
    person_id, person_name = None, None
    if person_raw:
        matches = fuzzy_match_people(person_raw, people_path)
        if len(matches) == 1:
            person_id = matches[0]["id"]
            person_name = matches[0]["canonical_name"]
        elif len(matches) > 1 and response_url:
            post_ambiguous_people(response_url, person_raw, matches, body, project_raw, tag_raw)
            print(f"Ambiguous person '{person_raw}' — posted buttons, note not created")
            return
        elif len(matches) > 1:
            person_id = matches[0]["id"]
            person_name = matches[0]["canonical_name"]
        # len == 0: leave unlinked; mentioned implicitly (person omitted from confirmation)

    # Project: best-match-or-skip
    project_id, project_name, project_missed = None, None, None
    if project_raw:
        proj = best_match_project(project_raw, projects_path)
        if proj:
            project_id, project_name = proj["id"], proj["canonical_name"]
        else:
            project_missed = project_raw

    # Tag: known resolves, unknown dropped
    tag, dropped_tag = resolve_tag(tag_raw, tags_path)

    storage = LocalStorage(base_dir=str(data_dir))
    add_note(storage, body=body, tags=[tag] if tag else [],
             person_id=person_id, project_id=project_id, task_id=None)

    confirmation = format_confirmation(body, person_name, project_name, tag, dropped_tag, project_missed)
    post_to_slack(response_url, confirmation, replace=bool(person_raw))
    print(confirmation)


if __name__ == "__main__":
    main()
