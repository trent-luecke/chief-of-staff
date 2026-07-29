"""Shared identity resolution for the people registry.

Consolidates find-by-email / find-by-name / slug / stub-id logic previously
duplicated across scripts/build_people_registry.py, scripts/resolve_observations.py,
processors/memory_observer.py, processors/avoma_phase1.py and scripts/avoma_per_call.py.

The registry (`data/people_registry.json`) is git-anchored on origin/main and must
be read/written via lib.storage.registry_storage(config) (LocalStorage on the working
tree), NEVER via build_storage (R2).
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 85
REGISTRY_KEY = "people_registry.json"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def unique_id(base: str, existing_ids) -> str:
    existing = set(existing_ids)
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def is_internal(email: str, internal_domains) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    return any(e.endswith(f"@{d.lower()}") for d in internal_domains)


def name_from_email(email: str) -> str:
    local = (email or "").split("@", 1)[0]
    parts = [p for p in re.split(r"[._-]+", local) if p]
    if not parts:
        return email or ""
    return " ".join(p.capitalize() for p in parts)


def load_people(storage) -> list:
    data = storage.read_json(REGISTRY_KEY, default={"version": 1, "people": []})
    return data.get("people", [])


def build_lookup(people) -> tuple:
    """Return (email_index, alias_list).

    email_index: {email_lower: person_id} from each person's `email` + '@' aliases.
    alias_list: [(person_id, text_lower)] from non-email aliases + canonical_name.
    First writer wins on collisions (setdefault).
    """
    email_index: dict = {}
    alias_list: list = []
    for p in people:
        pid = p["id"]
        primary = (p.get("email") or "").strip().lower()
        if primary:
            email_index.setdefault(primary, pid)
        for alias in p.get("aliases", []):
            a = (alias or "").strip().lower()
            if not a:
                continue
            if "@" in a:
                email_index.setdefault(a, pid)
            else:
                alias_list.append((pid, a))
        cname = (p.get("canonical_name") or "").strip().lower()
        if cname:
            alias_list.append((pid, cname))
    return email_index, alias_list


def find_by_email(email, email_index) -> Optional[str]:
    if not email:
        return None
    return email_index.get(email.strip().lower())


def find_by_name(name, alias_list, threshold: int = FUZZY_THRESHOLD) -> tuple:
    """Return (person_id, score). person_id is None if best score < threshold."""
    if not name:
        return None, 0
    target = name.strip().lower()
    best_id, best_score = None, 0
    for pid, alias in alias_list:
        score = fuzz.token_sort_ratio(target, alias)
        if score > best_score:
            best_id, best_score = pid, score
    if best_score >= threshold:
        return best_id, best_score
    return None, best_score


def resolve(name, email, email_index, alias_list, threshold: int = FUZZY_THRESHOLD) -> Optional[str]:
    """Find-only resolution (never creates). Email exact match wins, then fuzzy name."""
    hit = find_by_email(email, email_index)
    if hit:
        return hit
    pid, _ = find_by_name(name, alias_list, threshold)
    return pid
