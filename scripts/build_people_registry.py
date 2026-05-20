"""Build and update the people registry from all known sources.

Sources scanned in order:
  1. data/people/*.md — existing people files (filename → ID)
  2. data/pipeline_cache.json — leads
  3. data/memory/observations.jsonl — Avoma participant strings

Merge rules per the migration spec:
  - Exact email match  → auto-merge (update existing person)
  - Exact name match   → auto-merge (token_sort_ratio == 100)
  - Fuzzy name >85%    → flag in people_unresolved.json, do NOT auto-merge
  - No match           → create stub; pipeline leads get type "lead",
                         Avoma unknowns get type "unknown" (also flagged)

Writes:
  data/people_registry.json   — canonical identity spine (updated in place)
  data/people_unresolved.json — candidates that need manual review
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

REGISTRY_FILE = Path("data/people_registry.json")
UNRESOLVED_FILE = Path("data/people_unresolved.json")
PEOPLE_DIR = Path("data/people")
PIPELINE_CACHE = Path("data/pipeline_cache.json")
OBSERVATIONS_FILE = Path("data/memory/observations.jsonl")

INTERNAL_DOMAIN = "teambuildr.com"
FUZZY_THRESHOLD = 85

SYSTEM_ENTITY_SKIPLIST = {"priorities", "manual", "issues", "general", "daily"}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "people": []}


def _save_registry(registry: dict) -> None:
    REGISTRY_FILE.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _load_unresolved() -> dict:
    if UNRESOLVED_FILE.exists():
        return json.loads(UNRESOLVED_FILE.read_text(encoding="utf-8"))
    return {"unresolved": [], "previously_notified": []}


def _save_unresolved(data: dict) -> None:
    UNRESOLVED_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def _is_internal(email: str) -> bool:
    return email.lower().endswith(f"@{INTERNAL_DOMAIN}")


def _build_lookup(people: list) -> tuple[dict, list]:
    """Build fast-lookup structures.

    Returns:
        email_index: lowercase email → person id
        alias_list:  [(canonical_name, [non-email aliases], person_id), ...]
    """
    email_index: dict[str, str] = {}
    alias_list: list[tuple[str, list[str], str]] = []
    for p in people:
        email = (p.get("email") or "").lower().strip()
        if email:
            email_index[email] = p["id"]
        names = [p["canonical_name"]] + [
            a for a in p.get("aliases", []) if "@" not in a
        ]
        alias_list.append((p["canonical_name"], names, p["id"]))
    return email_index, alias_list


def _find_by_email(email: str, email_index: dict) -> str | None:
    return email_index.get(email.lower().strip())


def _find_by_name(name: str, alias_list: list) -> tuple[str | None, int]:
    """Return (person_id, score) for best name match. Score is 0..100."""
    best_id, best_score = None, 0
    for _canonical, aliases, pid in alias_list:
        for alias in aliases:
            score = fuzz.token_sort_ratio(name.lower(), alias.lower())
            if score > best_score:
                best_score, best_id = score, pid
    return best_id, best_score


def _update_last_seen(people: list, pid: str) -> None:
    today = date.today().isoformat()
    for p in people:
        if p["id"] == pid:
            p["last_seen"] = today
            return


def _add_alias(people: list, pid: str, alias: str) -> None:
    for p in people:
        if p["id"] == pid:
            if alias not in p.get("aliases", []):
                p.setdefault("aliases", []).append(alias)
            return


def _unique_id(base: str, existing_ids: set) -> str:
    new_id, counter = base, 2
    while new_id in existing_ids:
        new_id = f"{base}-{counter}"
        counter += 1
    return new_id


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _resolve(
    name: str,
    email: str | None,
    source: str,
    people: list,
    email_index: dict,
    alias_list: list,
    unresolved_list: list,
    *,
    default_type: str = "unknown",
    pipeline_record: str | None = None,
    people_file: str | None = None,
) -> str | None:
    """Find or create a person. Returns person_id, or None if flagged-only."""
    today = date.today().isoformat()

    # 1. Exact email match
    if email:
        pid = _find_by_email(email, email_index)
        if pid:
            _update_last_seen(people, pid)
            _add_alias(people, pid, email)
            return pid

    # 2. Exact / fuzzy name match
    if name:
        pid, score = _find_by_name(name, alias_list)
        if score == 100:
            # Exact name match — auto-merge
            _update_last_seen(people, pid)
            if email:
                _add_alias(people, pid, email)
                if email.lower() not in email_index:
                    email_index[email.lower()] = pid
            return pid
        if score >= FUZZY_THRESHOLD:
            # Near match — flag for manual review, do NOT auto-merge
            _flag_unresolved(unresolved_list, name, email, source, candidate_id=pid, score=score)
            return None

    # 3. No match — create stub
    person_type = default_type
    if email and _is_internal(email):
        person_type = "internal"

    existing_ids = {p["id"] for p in people}
    new_id = _unique_id(_slug(name) if name else _slug(email or "unknown"), existing_ids)

    aliases = []
    if name:
        aliases.append(name)
    if email:
        aliases.append(email)

    new_person = {
        "id": new_id,
        "canonical_name": name or email or "Unknown",
        "aliases": aliases,
        "email": email or "",
        "type": person_type,
        "pipeline_record": pipeline_record,
        "people_file": people_file,
        "created": today,
        "last_seen": today,
    }
    people.append(new_person)

    # Update lookup structures in place for subsequent resolutions
    if email:
        email_index[email.lower()] = new_id
    non_email_aliases = [a for a in aliases if "@" not in a]
    alias_list.append((new_person["canonical_name"], non_email_aliases, new_id))

    if person_type == "unknown":
        _flag_unresolved(unresolved_list, name or email, email, source, candidate_id=None, score=0)

    return new_id


def _flag_unresolved(
    unresolved_list: list,
    entity: str | None,
    email: str | None,
    source: str,
    candidate_id: str | None,
    score: int,
) -> None:
    today = date.today().isoformat()
    unresolved_list.append({
        "entity": entity,
        "email": email,
        "source": source,
        "candidate_id": candidate_id,
        "candidate_score": score,
        "added": today,
    })


# ---------------------------------------------------------------------------
# Source scanners
# ---------------------------------------------------------------------------

def _scan_people_files(people: list, email_index: dict, alias_list: list, unresolved_list: list) -> int:
    """Ensure every data/people/*.md has a registry entry. Returns count added."""
    if not PEOPLE_DIR.exists():
        return 0
    added = 0
    today = date.today().isoformat()
    for path in sorted(PEOPLE_DIR.glob("*.md")):
        file_id = path.stem
        canonical_name = file_id.replace("-", " ").title()
        email: str | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                canonical_name = line[2:].strip()
            if "**Email:**" in line:
                email = line.split("**Email:**", 1)[1].strip()
        people_file = f"data/people/{path.name}"

        # If already exists by file_id, just refresh
        existing = next((p for p in people if p["id"] == file_id), None)
        if existing:
            existing["last_seen"] = today
            if not existing.get("people_file"):
                existing["people_file"] = people_file
            continue

        # Check by email
        if email:
            pid = _find_by_email(email, email_index)
            if pid:
                p = next(p for p in people if p["id"] == pid)
                p["last_seen"] = today
                if not p.get("people_file"):
                    p["people_file"] = people_file
                continue

        # Create new entry using file_id as the canonical id
        person_type = "internal" if email and _is_internal(email) else "unknown"
        aliases = [canonical_name]
        if email:
            aliases.append(email)
        new_person = {
            "id": file_id,
            "canonical_name": canonical_name,
            "aliases": aliases,
            "email": email or "",
            "type": person_type,
            "pipeline_record": None,
            "people_file": people_file,
            "created": today,
            "last_seen": today,
        }
        people.append(new_person)
        if email:
            email_index[email.lower()] = file_id
        non_email = [a for a in aliases if "@" not in a]
        alias_list.append((canonical_name, non_email, file_id))
        added += 1
    return added


def _scan_pipeline_cache(people: list, email_index: dict, alias_list: list, unresolved_list: list) -> int:
    """Scan pipeline_cache.json leads. Returns count of new people added."""
    if not PIPELINE_CACHE.exists():
        return 0
    raw = json.loads(PIPELINE_CACHE.read_text(encoding="utf-8"))
    leads = raw if isinstance(raw, list) else raw.get("leads", [])
    added = 0
    for lead in leads:
        name = (lead.get("name") or "").strip()
        email = (lead.get("email") or "").strip() or None
        if not name:
            continue
        pid = _resolve(
            name=name, email=email, source="pipeline",
            people=people, email_index=email_index, alias_list=alias_list,
            unresolved_list=unresolved_list,
            default_type="lead", pipeline_record=name,
        )
        if pid and not next((p for p in people if p["id"] == pid), {}).get("pipeline_record"):
            next(p for p in people if p["id"] == pid)["pipeline_record"] = name
        if pid:
            added += 1
    return added


def _scan_observations(people: list, email_index: dict, alias_list: list, unresolved_list: list) -> int:
    """Scan observations.jsonl for unique Avoma participant names. Returns count added."""
    if not OBSERVATIONS_FILE.exists():
        return 0
    seen_names: set[str] = set()
    added = 0
    for line in OBSERVATIONS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obs.get("type") != "meeting_transcript":
            continue
        ctx = obs.get("context", "")
        # Extract participants=... (always last token group in context)
        idx = ctx.find("participants=")
        if idx < 0:
            continue
        participants_str = ctx[idx + len("participants="):]
        # Truncate at any subsequent key=value pair
        m = re.search(r"\s+\w+=", participants_str)
        if m:
            participants_str = participants_str[: m.start()]
        for raw in participants_str.split(","):
            name = raw.strip()
            if not name or name in seen_names:
                continue
            if name.lower() in SYSTEM_ENTITY_SKIPLIST or name.startswith("#"):
                continue
            seen_names.add(name)
            pid = _resolve(
                name=name, email=None, source="avoma",
                people=people, email_index=email_index, alias_list=alias_list,
                unresolved_list=unresolved_list,
                default_type="unknown",
            )
            if pid:
                added += 1
    return added


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    registry = _load_registry()
    people = registry["people"]
    unresolved_data = _load_unresolved()
    new_unresolved: list[dict] = []

    email_index, alias_list = _build_lookup(people)

    print("Scanning people files...")
    n = _scan_people_files(people, email_index, alias_list, new_unresolved)
    print(f"  {n} new entries from people files.")

    print("Scanning pipeline cache...")
    n = _scan_pipeline_cache(people, email_index, alias_list, new_unresolved)
    print(f"  {n} entries touched from pipeline cache.")

    print("Scanning observations...")
    n = _scan_observations(people, email_index, alias_list, new_unresolved)
    print(f"  {n} entries touched from observations.")

    registry["people"] = people
    _save_registry(registry)
    print(f"Registry saved: {len(people)} total people.")

    # Merge new unresolved into existing, deduplicating by entity string
    existing_entities = {u.get("entity") for u in unresolved_data.get("unresolved", [])}
    genuinely_new = [u for u in new_unresolved if u.get("entity") not in existing_entities]
    unresolved_data.setdefault("unresolved", []).extend(genuinely_new)
    _save_unresolved(unresolved_data)
    print(f"Unresolved: {len(genuinely_new)} new entries flagged.")


if __name__ == "__main__":
    sys.exit(main())
