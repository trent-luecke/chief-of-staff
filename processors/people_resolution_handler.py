"""Handle Telegram replies to the people-resolution notification."""

from __future__ import annotations

import re
from datetime import datetime, timezone

# Maximum age of a pending resolution state before we treat it as stale.
_MAX_AGE_DAYS = 7


def _is_stale(state: dict) -> bool:
    sent_at = state.get("sent_at", "")
    if not sent_at:
        return True
    try:
        sent = datetime.fromisoformat(sent_at)
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - sent).days
        return age > _MAX_AGE_DAYS
    except ValueError:
        return True


def _parse_commands(reply_text: str) -> tuple[list[tuple[int, str, str]], list[str]]:
    """Parse reply into (commands, skipped_segments).

    commands: list of (index, command, argument) tuples
    skipped_segments: segments that contained no valid command pattern

    Handles comma-separated commands and ignores Telegram quote blocks.
    Only lines/segments matching '^\\d+ (confirm|alias|new|skip)' are parsed.
    """
    commands = []
    skipped = []
    pattern = re.compile(
        r"^\s*(\d+)\s+(confirm|alias|new|skip)(?:\s+(.+))?$",
        re.IGNORECASE,
    )
    # Split on commas to support "1 confirm, 2 new Name, 3 skip"
    segments = re.split(r",\s*", reply_text)
    for segment in segments:
        matched = False
        # Each segment may be multi-line (Telegram quote block + command);
        # scan each line for a matching command.
        for line in segment.splitlines():
            m = pattern.match(line.strip())
            if m:
                index = int(m.group(1))
                command = m.group(2).lower()
                argument = (m.group(3) or "").strip()
                commands.append((index, command, argument))
                matched = True
                break  # only first match per segment
        if not matched:
            clean = segment.strip()
            if clean:
                skipped.append(clean[:60])
    return commands, skipped


def _find_entity(state: dict, index: int) -> dict | None:
    for entity in state.get("entities", []):
        if entity.get("index") == index:
            return entity
    return None


def _find_person(registry: dict, person_id: str) -> dict | None:
    for person in registry.get("people", []):
        if person.get("id") == person_id:
            return person
    return None


def _add_alias(person: dict, alias: str) -> None:
    aliases = person.setdefault("aliases", [])
    if alias not in aliases:
        aliases.append(alias)


def _new_person_id(name: str, registry: dict) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    existing_ids = {p["id"] for p in registry.get("people", [])}
    if base not in existing_ids:
        return base
    for i in range(2, 20):
        candidate = f"{base}-{i}"
        if candidate not in existing_ids:
            return candidate
    return base


def handle_resolution_reply(reply_text: str, storage) -> str:
    """Parse a Telegram reply and apply registry mutations. Returns an ack string."""
    state = storage.read_json("people_unresolved_state.json")
    if not state or _is_stale(state):
        return "No pending resolution — message may be stale."

    commands, skipped_segments = _parse_commands(reply_text)
    if not commands:
        return "No valid commands found. Expected: N confirm / N alias <id> / N new <Name> / N skip"

    registry = storage.read_json("people_registry.json", default={"version": 1, "people": []})
    skiplist = registry.setdefault("skiplist", [])

    ack_lines = ["Done:"]

    for index, command, argument in commands:
        entity_rec = _find_entity(state, index)
        if not entity_rec:
            ack_lines.append(f"  • Entity {index}: not found in pending state.")
            continue

        entity = entity_rec["entity"]
        entity_type = entity_rec.get("type")

        if command == "confirm":
            if entity_type != "fuzzy_match":
                ack_lines.append(
                    f"  • Entity {index} ({entity!r}): no candidate to confirm"
                    f" — use 'alias <person-id>' or 'new <name>' instead."
                )
                continue
            candidate_id = entity_rec.get("candidate_id")
            person = _find_person(registry, candidate_id)
            if not person:
                ack_lines.append(
                    f"  • Entity {index} ({entity!r}): candidate '{candidate_id}' not found in registry."
                )
                continue
            _add_alias(person, entity)
            candidate_name = entity_rec.get("candidate_name", candidate_id)
            ack_lines.append(f"  • {entity!r} → aliased to {candidate_name}")

        elif command == "alias":
            if not argument:
                ack_lines.append(f"  • Entity {index} ({entity!r}): 'alias' requires a person ID argument.")
                continue
            person = _find_person(registry, argument)
            if not person:
                ack_lines.append(
                    f"  • Entity {index} ({entity!r}): person '{argument}' not found in registry."
                )
                continue
            _add_alias(person, entity)
            ack_lines.append(f"  • {entity!r} → aliased to {person['canonical_name']}")

        elif command == "new":
            if not argument:
                ack_lines.append(f"  • Entity {index} ({entity!r}): 'new' requires a full name argument.")
                continue
            new_id = _new_person_id(argument, registry)
            registry["people"].append({
                "id": new_id,
                "canonical_name": argument,
                "aliases": [entity],
                "email": None,
                "type": "unknown",
                "pipeline_record": None,
                "people_file": None,
                "created": datetime.now(timezone.utc).date().isoformat(),
                "last_seen": datetime.now(timezone.utc).date().isoformat(),
            })
            ack_lines.append(f"  • {entity!r} → new person stub created ({argument})")

        elif command == "skip":
            if entity not in skiplist:
                skiplist.append(entity)
            ack_lines.append(f"  • {entity!r} → added to skiplist")

    if skipped_segments:
        ack_lines.append(f"  Skipped unrecognised: {'; '.join(skipped_segments)}")

    storage.write_json("people_registry.json", registry)
    return "\n".join(ack_lines)
