"""Nightly batch job: resolve observations.jsonl to person IDs.

Builds data/people_resolution.json — a sidecar index mapping observation
line numbers to resolved person IDs. Does NOT touch observations.jsonl.

Resolution strategy per observation type:
  meeting_transcript  — parse participants= from context field
  pipeline_stale      — match entity slug against registry pipeline_record
  email_loop          — best-effort cross-ref via people file open threads
  top_priority        — system-level, primary_person_id: null
  issue_pattern       — system-level, primary_person_id: null
  kpi_snapshot        — system-level, primary_person_id: null
  decision            — system-level, primary_person_id: null
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

from lib.notify import notify_user

REGISTRY_FILE = Path("data/people_registry.json")
RESOLUTION_FILE = Path("data/people_resolution.json")
OBSERVATIONS_FILE = Path("data/memory/observations.jsonl")
PEOPLE_DIR = Path("data/people")

FUZZY_THRESHOLD = 85
INTERNAL_DOMAIN = "teambuildr.com"
SYSTEM_TYPES = {"top_priority", "issue_pattern", "kpi_snapshot", "decision"}


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict]:
    if not REGISTRY_FILE.exists():
        return []
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    return data.get("people", [])


def _build_lookup(people: list) -> tuple[dict, list, set]:
    """Build lookup structures.

    Returns:
        email_index:   lowercase email → person id
        alias_list:    [(canonical_name, [non-email aliases], person_id), ...]
        internal_ids:  set of person_ids with type "internal"
    """
    email_index: dict[str, str] = {}
    alias_list: list[tuple[str, list[str], str]] = []
    internal_ids: set[str] = set()
    for p in people:
        email = (p.get("email") or "").lower().strip()
        if email:
            email_index[email] = p["id"]
        if p.get("type") == "internal":
            internal_ids.add(p["id"])
        names = [p["canonical_name"]] + [
            a for a in p.get("aliases", []) if "@" not in a
        ]
        alias_list.append((p["canonical_name"], names, p["id"]))
    return email_index, alias_list, internal_ids


def _find_by_email(email: str, email_index: dict) -> str | None:
    return email_index.get(email.lower().strip())


def _find_by_name(name: str, alias_list: list) -> tuple[str | None, int]:
    best_id, best_score = None, 0
    for _canonical, aliases, pid in alias_list:
        for alias in aliases:
            score = fuzz.token_sort_ratio(name.lower(), alias.lower())
            if score > best_score:
                best_score, best_id = score, pid
    if best_score >= FUZZY_THRESHOLD:
        return best_id, best_score
    return None, best_score


# ---------------------------------------------------------------------------
# Pipeline slug matching
# ---------------------------------------------------------------------------

def _pipeline_record_to_slug(pipeline_record: str) -> str:
    """'Mike Woodby — Apex Holland' → 'mike-woodby'."""
    # Split on em-dash or double dash and take the first part (person name)
    name_part = re.split(r"\s+[—–-]{1,2}\s+", pipeline_record)[0].strip()
    return re.sub(r"[^a-z0-9]+", "-", name_part.lower().strip()).strip("-")


def _build_pipeline_slug_index(people: list) -> dict:
    """Map slugified pipeline_record → person_id."""
    index: dict[str, str] = {}
    for p in people:
        pr = p.get("pipeline_record")
        if pr:
            slug = _pipeline_record_to_slug(pr)
            index[slug] = p["id"]
    return index


# ---------------------------------------------------------------------------
# Email loop resolution
# ---------------------------------------------------------------------------

def _build_email_loop_index(people: list) -> dict:
    """Build a rough index for email_loop observations.

    Checks people file 'Open threads:' sections and pipeline cache emails.
    Returns a dict of lowercase subject fragment → person_id.
    """
    index: dict[str, str] = {}
    if not PEOPLE_DIR.exists():
        return index
    for path in PEOPLE_DIR.glob("*.md"):
        pid = None
        # Find person_id for this file
        stem = path.stem
        for p in people:
            if p.get("people_file") == f"data/people/{path.name}" or p["id"] == stem:
                pid = p["id"]
                break
        if not pid:
            continue
        content = path.read_text(encoding="utf-8")
        in_threads = False
        for line in content.splitlines():
            if "open threads" in line.lower():
                in_threads = True
                continue
            if in_threads:
                if line.startswith("#") or (line.startswith("**") and ":" in line):
                    in_threads = False
                    continue
                thread_text = line.strip().lstrip("-").strip()
                if thread_text:
                    index[thread_text.lower()] = pid
    return index


# ---------------------------------------------------------------------------
# Observation resolvers
# ---------------------------------------------------------------------------

def _resolve_meeting_transcript(
    obs: dict,
    email_index: dict,
    alias_list: list,
    internal_ids: set,
) -> tuple[str | None, list[str], str]:
    """Return (primary_person_id, related_person_ids, confidence)."""
    ctx = obs.get("context", "")
    idx = ctx.find("participants=")
    if idx < 0:
        return None, [], "unresolved"

    participants_str = ctx[idx + len("participants="):]
    m = re.search(r"\s+\w+=", participants_str)
    if m:
        participants_str = participants_str[: m.start()]

    resolved: list[tuple[str, int]] = []  # (person_id, score)
    for raw in participants_str.split(","):
        name = raw.strip()
        if not name:
            continue
        pid, score = _find_by_name(name, alias_list)
        if pid:
            resolved.append((pid, score))

    if not resolved:
        return None, [], "unresolved"

    # Separate internal (reps) from external (prospects)
    external = [(pid, score) for pid, score in resolved if pid not in internal_ids]
    internal = [(pid, score) for pid, score in resolved if pid in internal_ids]

    if external:
        # First external participant by position is primary
        primary_id = external[0][0]
        primary_score = external[0][1]
        related = [pid for pid, _ in external[1:]] + [pid for pid, _ in internal]
    else:
        # All internal (e.g. team sync) — use first participant
        primary_id = resolved[0][0]
        primary_score = resolved[0][1]
        related = [pid for pid, _ in resolved[1:]]

    confidence = "exact" if primary_score == 100 else "fuzzy"
    return primary_id, related, confidence


def _resolve_pipeline_stale(
    obs: dict,
    pipeline_slug_index: dict,
) -> tuple[str | None, list[str], str]:
    entity = obs.get("entity", "")
    pid = pipeline_slug_index.get(entity)
    if pid:
        return pid, [], "exact"
    return None, [], "unresolved"


def _resolve_email_loop(
    obs: dict,
    email_loop_index: dict,
    alias_list: list,
) -> tuple[str | None, list[str], str]:
    entity = obs.get("entity", "")
    # entity format: "thread:RE: Contract Renewal"
    subject = entity.removeprefix("thread:").lower().strip()
    if not subject:
        return None, [], "unresolved"

    # Exact substring match in index
    for fragment, pid in email_loop_index.items():
        if fragment in subject or subject in fragment:
            return pid, [], "fuzzy"

    # Fuzzy name match as last resort
    pid, score = _find_by_name(subject, alias_list)
    if pid:
        return pid, [], "fuzzy"

    return None, [], "unresolved"


# ---------------------------------------------------------------------------
# Main resolution loop
# ---------------------------------------------------------------------------

def resolve_all(
    people: list,
    email_index: dict,
    alias_list: list,
    internal_ids: set,
    pipeline_slug_index: dict,
    email_loop_index: dict,
) -> tuple[dict, list, list]:
    """Walk every observation line and build resolution mappings.

    Returns:
        resolutions:      line_number (str) → resolution dict
        unresolved_lines: list of int line numbers
        unresolved_entities: list of entity strings for unresolved lines
    """
    if not OBSERVATIONS_FILE.exists():
        return {}, [], []

    resolutions: dict[str, dict] = {}
    unresolved_lines: list[int] = []
    unresolved_entities: list[str] = []

    for i, raw_line in enumerate(OBSERVATIONS_FILE.read_text(encoding="utf-8").splitlines()):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obs = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        obs_type = obs.get("type", "")

        # System-level types — explicitly not person-keyed
        if obs_type in SYSTEM_TYPES:
            resolutions[str(i)] = {
                "primary_person_id": None,
                "related_person_ids": [],
                "confidence": "system",
            }
            continue

        # Observations that already carry person IDs (post-migration)
        if obs.get("primary_person_id") is not None:
            resolutions[str(i)] = {
                "primary_person_id": obs["primary_person_id"],
                "related_person_ids": obs.get("related_person_ids", []),
                "confidence": "embedded",
            }
            continue

        primary_id: str | None = None
        related: list[str] = []
        confidence = "unresolved"

        if obs_type == "meeting_transcript":
            primary_id, related, confidence = _resolve_meeting_transcript(
                obs, email_index, alias_list, internal_ids
            )
        elif obs_type == "pipeline_stale":
            primary_id, related, confidence = _resolve_pipeline_stale(obs, pipeline_slug_index)
        elif obs_type == "email_loop":
            primary_id, related, confidence = _resolve_email_loop(obs, email_loop_index, alias_list)

        if primary_id is not None:
            resolutions[str(i)] = {
                "primary_person_id": primary_id,
                "related_person_ids": related,
                "confidence": confidence,
            }
        else:
            unresolved_lines.append(i)
            entity = obs.get("entity", "")
            if entity and entity not in unresolved_entities:
                unresolved_entities.append(entity)

    return resolutions, unresolved_lines, unresolved_entities


# ---------------------------------------------------------------------------
# Unresolved entity classification (for Telegram notification)
# ---------------------------------------------------------------------------

def _best_candidate(
    entity: str,
    alias_list: list,
) -> tuple[str | None, str | None, int]:
    """Return (person_id, canonical_name, score) for the best fuzzy match, ignoring threshold."""
    best_id, best_canonical, best_score = None, None, 0
    for canonical, aliases, pid in alias_list:
        for alias in aliases:
            score = fuzz.token_sort_ratio(entity.lower(), alias.lower())
            if score > best_score:
                best_score, best_id, best_canonical = score, pid, canonical
    if best_score >= 50:
        return best_id, best_canonical, best_score
    return None, None, 0


def _classify_entity(
    entity: str,
    email_index: dict,
    alias_list: list,
) -> dict:
    """Classify an unresolved entity for the Slack notification and state file."""
    if entity.startswith("#"):
        return {
            "entity": entity,
            "candidate_id": None,
            "candidate_name": None,
            "confidence": None,
            "type": "system_entity",
        }

    pid, canonical, score = _best_candidate(entity, alias_list)
    if pid:
        return {
            "entity": entity,
            "candidate_id": pid,
            "candidate_name": canonical,
            "confidence": round(score / 100, 2),
            "type": "fuzzy_match",
        }

    return {
        "entity": entity,
        "candidate_id": None,
        "candidate_name": None,
        "confidence": None,
        "type": "no_match",
    }


def _build_notification(classified: list[dict]) -> str:
    n = len(classified)
    noun = "entity" if n == 1 else "entities"
    return (
        f"{n} unresolved {noun} from tonight's run.\n\n"
        "Open your people tracker HTML artifact to reconcile new items."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    people = _load_registry()
    if not people:
        print("Registry is empty — run build_people_registry.py first.")
        return

    email_index, alias_list, internal_ids = _build_lookup(people)
    pipeline_slug_index = _build_pipeline_slug_index(people)
    email_loop_index = _build_email_loop_index(people)

    print("Resolving observations...")
    resolutions, unresolved_lines, unresolved_entities = resolve_all(
        people, email_index, alias_list, internal_ids,
        pipeline_slug_index, email_loop_index,
    )

    output = {
        "resolved_at": date.today().isoformat() + "T00:00:00",
        "resolutions": resolutions,
        "unresolved_lines": unresolved_lines,
        "unresolved_entities": unresolved_entities,
    }
    RESOLUTION_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    total = len(resolutions) + len(unresolved_lines)
    print(
        f"Done: {len(resolutions)} resolved, {len(unresolved_lines)} unresolved"
        f" (of {total} total observations)."
    )

    if not unresolved_entities:
        return

    # Classify each entity and send a Slack notification
    classified = [
        {"index": i + 1, **_classify_entity(entity, email_index, alias_list)}
        for i, entity in enumerate(unresolved_entities)
    ]

    notification_text = _build_notification(classified)

    import json as _json
    with open("config.json") as _f:
        _config = _json.load(_f)
    notify_user(notification_text, _config)


if __name__ == "__main__":
    sys.exit(main())
