#!/usr/bin/env python3
"""Per-call Avoma processor — runs every 30 min Mon–Fri during business hours.

For each new external Avoma transcript in the last 90 minutes:
  - Writes a meeting_transcript observation (deduped by UUID)
  - Resolves/stubs attendees in data/people_registry.json
  - Sends a structured Telegram message with summary, action items, proposed tasks
  - Stores proposed tasks keyed by Telegram message_id for reply-based approval
"""

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

_LOOKBACK_HOURS = 2  # generous overlap window; UUID dedup prevents doubles
_PENDING_TASKS_KEY = "state/pending_avoma_tasks.json"
_PENDING_ACTIONS_KEY = "state/pending_avoma_actions.json"
_REGISTRY_FILE = _ROOT / "data" / "people_registry.json"
_FUZZY_THRESHOLD = 85
_INTERNAL_DOMAIN = "teambuildr.com"

_SALES_REP_MAP = {
    "ryan@teambuildr.com": "Ryan",
    "lmartin@teambuildr.com": "Martin",
    "chris@teambuildr.com": "Chris",
    "jeff@teambuildr.com": "Jeff",
    "quinn@teambuildr.com": "Quinn",
    "trent@teambuildr.com": "Trent",
}

_NO_SHOW_KEYWORDS = ("no-show", "no show", "did not attend", "didn't attend", "no one joined", "no one showed")
_STRONG_SIGNAL_KEYWORDS = ("contract", "pricing", "timeline", "next step", "trial", "ready to start", "implement", "reference", "sign up", "sign-up")


# ---------------------------------------------------------------------------
# Helpers (mirrors avoma_sync.py; kept local to avoid coupling to a script)
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _is_internal(s: str) -> bool:
    return s.lower().endswith(f"@{_INTERNAL_DOMAIN}")


def _extract_lead_name(title: str) -> str:
    prefixes = (
        "TeamBuildr OS Demo - ", "TeamBuildr OS Demo | ", "TeamBuildr OS Demo: ",
        "TeamBuildr Demo - ", "TeamBuildr Demo | ", "TeamBuildr Demo: ",
        "Demo - ", "Demo | ", "Demo: ",
        "Follow Up - ", "Follow Up | ", "Follow Up: ",
        "Follow-Up - ", "Follow-Up | ", "Follow-Up: ",
        "Onboarding - ", "Onboarding | ", "Onboarding: ",
        "Onboarding Session - ", "Onboarding Call - ",
    )
    for prefix in prefixes:
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title.strip()


def _format_call_date(start_at: str) -> str:
    try:
        return datetime.fromisoformat(start_at.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return date.today().isoformat()


def _infer_pipeline_status(transcript) -> str:
    summary_lower = transcript.summary.lower()
    if any(kw in summary_lower for kw in _NO_SHOW_KEYWORDS):
        return "No-Show"
    ct = transcript.call_type
    if ct == "demo":
        if transcript.buying_signals and any(
            any(kw in s.lower() for kw in _STRONG_SIGNAL_KEYWORDS)
            for s in transcript.buying_signals
        ):
            return "In-Trial / Post Demo"
        return "No Trial / Post Demo"
    if ct == "follow_up":
        return "On-Hold" if transcript.objections else "Out of Demo / Need Update"
    return "Post Demo"


def _infer_account_owner(participants: list[str]) -> str:
    for p in participants:
        p_lower = p.lower().strip()
        for email, name in _SALES_REP_MAP.items():
            if email.lower() in p_lower:
                return name
        for email, name in _SALES_REP_MAP.items():
            first = name.lower()
            if first in p_lower.split() or p_lower.startswith(first + " "):
                return name
    return "Unknown"


# ---------------------------------------------------------------------------
# People registry helpers
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    if _REGISTRY_FILE.exists():
        return json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "people": []}


def _save_registry(registry: dict) -> None:
    _REGISTRY_FILE.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _build_lookup(people: list) -> tuple[dict, list]:
    email_index: dict[str, str] = {}
    alias_list: list[tuple[str, list[str], str]] = []
    for p in people:
        email = (p.get("email") or "").lower().strip()
        if email:
            email_index[email] = p["id"]
        names = [p["canonical_name"]] + [a for a in p.get("aliases", []) if "@" not in a]
        alias_list.append((p["canonical_name"], names, p["id"]))
    return email_index, alias_list


def _unique_id(base: str, existing_ids: set) -> str:
    new_id, counter = base, 2
    while new_id in existing_ids:
        new_id = f"{base}-{counter}"
        counter += 1
    return new_id


def _resolve_participants(
    participants: list[str],
    people: list,
    email_index: dict,
    alias_list: list,
) -> list[dict]:
    """Resolve each participant to a registry entry or create a stub.

    Returns list of dicts: {name, person_id, is_new, is_internal, is_stub_only}.
    Stubs added to `people`, `email_index`, and `alias_list` in-place.
    Internal TeamBuildr people get person_id but is_internal=True.
    """
    from rapidfuzz import fuzz

    today = date.today().isoformat()
    resolved: list[dict] = []
    existing_ids = {p["id"] for p in people}

    for participant in participants:
        participant = participant.strip()
        if not participant:
            continue

        is_email = "@" in participant
        is_internal = _is_internal(participant) if is_email else any(
            participant.lower() in name.lower() or name.lower() in participant.lower()
            for _, names, _ in alias_list
            for name in names
            if _INTERNAL_DOMAIN in (name + "")
        )

        # Email match
        if is_email:
            pid = email_index.get(participant.lower())
            if pid:
                # update last_seen
                for p in people:
                    if p["id"] == pid:
                        p["last_seen"] = today
                resolved.append({"name": participant, "person_id": pid, "is_new": False,
                                  "is_internal": p.get("type") == "internal", "is_stub_only": False})
                continue
            # Email not in registry — create stub if not internal
            if _is_internal(participant):
                resolved.append({"name": participant, "person_id": None, "is_new": False,
                                  "is_internal": True, "is_stub_only": False})
                continue
            # External email without registry entry
            display = participant.split("@")[0]
            new_id = _unique_id(_slug(display), existing_ids)
            existing_ids.add(new_id)
            stub = {
                "id": new_id,
                "canonical_name": display,
                "aliases": [display, participant],
                "email": participant,
                "type": "unknown",
                "pipeline_record": None,
                "people_file": None,
                "created": today,
                "last_seen": today,
            }
            people.append(stub)
            email_index[participant.lower()] = new_id
            alias_list.append((display, [display], new_id))
            resolved.append({"name": participant, "person_id": new_id, "is_new": True,
                              "is_internal": False, "is_stub_only": True})
            continue

        # Name match
        best_id, best_score = None, 0
        for _canonical, aliases, pid in alias_list:
            for alias in aliases:
                score = fuzz.token_sort_ratio(participant.lower(), alias.lower())
                if score > best_score:
                    best_score, best_id = score, pid

        if best_score >= _FUZZY_THRESHOLD and best_id:
            for p in people:
                if p["id"] == best_id:
                    p["last_seen"] = today
                    is_int = p.get("type") == "internal"
                    break
            else:
                is_int = False
            resolved.append({"name": participant, "person_id": best_id, "is_new": False,
                              "is_internal": is_int, "is_stub_only": False})
            continue

        # No match — create stub (skip internal-looking names)
        if any(rep_name.lower() == participant.lower().split()[0] for rep_name in _SALES_REP_MAP.values()):
            resolved.append({"name": participant, "person_id": None, "is_new": False,
                              "is_internal": True, "is_stub_only": False})
            continue

        new_id = _unique_id(_slug(participant) if participant else "unknown", existing_ids)
        existing_ids.add(new_id)
        stub = {
            "id": new_id,
            "canonical_name": participant,
            "aliases": [participant],
            "email": "",
            "type": "unknown",
            "pipeline_record": None,
            "people_file": None,
            "created": today,
            "last_seen": today,
        }
        people.append(stub)
        alias_list.append((participant, [participant], new_id))
        resolved.append({"name": participant, "person_id": new_id, "is_new": True,
                          "is_internal": False, "is_stub_only": True})

    return resolved


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

_OBS_KEY = "memory/observations.jsonl"


def _load_ingested_uuids(storage) -> set[str]:
    uuids: set[str] = set()
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            if obs.get("source") == "avoma" and obs.get("type") == "meeting_transcript":
                ctx = obs.get("context", "")
                for part in ctx.split():
                    if part.startswith("avoma_uuid="):
                        uuids.add(part.split("=", 1)[1])
        except json.JSONDecodeError:
            continue
    return uuids


def _write_observation(t, resolved_people: list, storage) -> None:
    from processors.memory_observer import _transcript_to_observation, _load_registry as _load_obs_registry

    # Use the canonical memory_observer helper to build the observation dict
    email_index, alias_list, internal_ids = _load_obs_registry()
    obs = _transcript_to_observation(t, alias_list, internal_ids)
    storage.append_line(_OBS_KEY, json.dumps(obs))


# ---------------------------------------------------------------------------
# Telegram message builder
# ---------------------------------------------------------------------------

def _build_message(t, lead_name: str, resolved_people: list) -> str:
    call_label = t.call_type.replace("_", " ").title() if t.call_type else "Call"
    participants_display = ", ".join(
        r["name"] for r in resolved_people if not r["is_internal"]
    ) or ", ".join(t.participants[:5])

    lines = [
        f"🎙️ {t.title} — {call_label}",
        participants_display,
        "",
        "📋 Summary",
        t.summary or "(no summary)",
    ]

    if t.action_items:
        lines += ["", "✅ Action Items — reply 'yes' or '1,2' to add to tasks; 'closed 1,2' or 'closed all' once done"]
        for i, item in enumerate(t.action_items[:8], 1):
            lines.append(f"  {i}. {item}")

    new_stubs = [r for r in resolved_people if r["is_new"] and not r["is_internal"]]
    if new_stubs:
        names = ", ".join(r["name"] for r in new_stubs)
        lines += ["", f"⚠️ New contact(s) — stub only, no file yet: {names}"]

    if t.os_interested and t.call_type in ("demo", "follow_up", "onboarding"):
        notion_block = _build_notion_prompt(t, lead_name)
        if notion_block:
            lines += ["", notion_block]

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3990] + "\n…(truncated)"
    return msg


def _derive_proposed_tasks(t) -> list[str]:
    """Extract tasks addressed to Trent or ownership-unclear from action_items."""
    tasks: list[str] = []
    rep_names_lower = {name.lower() for name in _SALES_REP_MAP.values()}
    trent_keywords = {"trent", "vp", "i will", "i'll", "follow up", "send", "schedule", "book"}
    generic_keywords = {"follow up", "send", "schedule", "book", "reach out", "connect"}

    for item in t.action_items:
        item_lower = item.lower()
        # Skip if clearly assigned to a prospect
        is_rep_task = any(rn in item_lower for rn in rep_names_lower) or any(kw in item_lower for kw in trent_keywords)
        is_generic = any(kw in item_lower for kw in generic_keywords)
        if is_rep_task or is_generic:
            tasks.append(item)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t_item in tasks:
        if t_item not in seen:
            seen.add(t_item)
            unique.append(t_item)
    return unique[:5]


def _build_notion_prompt(t, lead_name: str) -> str:
    call_date = _format_call_date(t.start_at)
    call_label = t.call_type.replace("_", " ").title()
    owner = _infer_account_owner(t.participants)

    if t.call_type == "onboarding":
        completed = "; ".join(t.onboarding_completed) if t.onboarding_completed else "none noted"
        next_steps = "; ".join(t.onboarding_next_steps) if t.onboarding_next_steps else "none noted"
        action_items_str = "; ".join(t.action_items[:6]) if t.action_items else "none"
        return (
            "📤 Notion Onboarding Update — paste into Claude Desktop\n"
            f"Update the onboarding tracker for {lead_name}. "
            f"Call date: {call_date}. "
            f"Summary: {t.summary} "
            f"Completed: {completed}. "
            f"Next steps: {next_steps}. "
            f"Action items: {action_items_str}."
        )
    else:
        status = _infer_pipeline_status(t)
        signals = "; ".join(t.buying_signals[:3]) if t.buying_signals else "none"
        objections = "; ".join(t.objections[:3]) if t.objections else "none"
        action_items_str = "; ".join(t.action_items[:6]) if t.action_items else "none"
        return (
            "📤 Notion Pipeline Update — paste into Claude Desktop\n"
            f"Update the pipeline record for {lead_name}. "
            f"Call date: {call_date}. Type: {call_label}. Owner: {owner}. "
            f"Inferred status: {status}. "
            f"Summary: {t.summary} "
            f"Buying signals: {signals}. "
            f"Objections: {objections}. "
            f"Action items: {action_items_str}."
        )


# ---------------------------------------------------------------------------
# Pending tasks store
# ---------------------------------------------------------------------------

def _is_recent(entry: dict, cutoff: int, today: str) -> bool:
    try:
        return date.fromisoformat(entry.get("created", today)).toordinal() >= cutoff
    except (ValueError, TypeError):
        return True  # keep on parse error rather than silently drop

def _save_pending_tasks(storage, message_id: int, t, proposed_tasks: list[str]) -> None:
    if not message_id or not proposed_tasks:
        return
    pending = storage.read_json(_PENDING_TASKS_KEY, default={})
    pending[str(message_id)] = {
        "call_title": t.title,
        "call_uuid": t.uuid,
        "call_type": t.call_type,
        "proposed_tasks": proposed_tasks,
        "created": date.today().isoformat(),
    }
    storage.write_json(_PENDING_TASKS_KEY, pending)


def _save_pending_actions(storage, message_id: int, t, resolved_people: list) -> None:
    """Store all action items keyed by message_id so the reply handler can resolve them."""
    if not message_id or not t.action_items:
        return
    pending = storage.read_json(_PENDING_ACTIONS_KEY, default={})
    # Purge entries older than 14 days
    today = date.today().isoformat()
    cutoff = date.fromisoformat(today).toordinal() - 14
    pending = {k: v for k, v in pending.items() if _is_recent(v, cutoff, today)}
    external = [r for r in resolved_people if not r["is_internal"] and r["person_id"]]
    pending[str(message_id)] = {
        "call_title": t.title,
        "call_uuid": t.uuid,
        "call_date": t.start_at[:10] if t.start_at else today,
        "participants": [{"person_id": r["person_id"], "name": r["name"]} for r in external],
        "action_items": t.action_items[:8],
        "created": today,
    }
    storage.write_json(_PENDING_ACTIONS_KEY, pending)


# ---------------------------------------------------------------------------
# Per-transcript processor
# ---------------------------------------------------------------------------

def process_transcript(
    t,
    storage,
    config: dict,
    bot_token: str,
    chat_id: str,
    people: list,
    email_index: dict,
    alias_list: list,
) -> None:
    lead_name = _extract_lead_name(t.title)

    # Resolve participants against registry
    resolved_people = _resolve_participants(t.participants, people, email_index, alias_list)

    # Write observation
    try:
        _write_observation(t, resolved_people, storage)
    except Exception as e:
        print(f"  WARNING: observation write failed for {t.uuid}: {e}", file=sys.stderr)

    # Build and send Telegram message
    msg = _build_message(t, lead_name, resolved_people)
    try:
        from lib.telegram import send_message
        message_id = send_message(bot_token, chat_id, msg)
        print(f"  Telegram sent for: {t.title} (msg_id={message_id})")
    except Exception as e:
        print(f"  WARNING: Telegram send failed for {t.uuid}: {e}", file=sys.stderr)
        message_id = None

    # Store action items for reply-based task approval
    if message_id and t.action_items:
        try:
            _save_pending_tasks(storage, message_id, t, t.action_items[:8])
        except Exception as e:
            print(f"  WARNING: pending tasks write failed: {e}", file=sys.stderr)

    if message_id and t.action_items:
        try:
            _save_pending_actions(storage, message_id, t, resolved_people)
        except Exception as e:
            print(f"  WARNING: pending actions write failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")

    from collectors.avoma import fetch_recent_meetings
    from lib.storage import build_storage

    avoma_key = os.environ.get("AVOMA_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

    for name, val in [
        ("AVOMA_API_KEY", avoma_key),
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("TELEGRAM_BOT_TOKEN", bot_token),
        ("TELEGRAM_ALLOWED_CHAT_ID", chat_id),
    ]:
        if not val:
            print(f"ERROR: {name} not set — avoma_per_call cannot run.", file=sys.stderr)
            return

    config_path = _ROOT / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    avoma_cfg = config.get("avoma", {})
    ai_model = config.get("ai_model", "claude-sonnet-4-6")
    storage = build_storage(config)

    print(f"🎙️  Fetching Avoma meetings (last {_LOOKBACK_HOURS}h)...")
    try:
        transcripts = fetch_recent_meetings(
            api_key=avoma_key,
            anthropic_api_key=anthropic_key,
            model=ai_model,
            lookback_hours=_LOOKBACK_HOURS,
            sales_rep_emails=avoma_cfg.get("sales_rep_emails", []),
            filter_internal=avoma_cfg.get("filter_internal", True),
            include_non_os=True,
        )
    except Exception as e:
        print(f"ERROR: Avoma fetch failed: {e}", file=sys.stderr)
        return

    print(f"   Found {len(transcripts)} meeting(s).")

    # UUID dedup against existing observations
    seen_uuids = _load_ingested_uuids(storage)
    new_transcripts = [t for t in transcripts if t.uuid not in seen_uuids]
    print(f"   {len(new_transcripts)} new (not yet ingested).")

    if not new_transcripts:
        return

    # Load registry once; persist at end
    registry = _load_registry()
    people = registry["people"]
    email_index, alias_list = _build_lookup(people)

    for t in new_transcripts:
        try:
            process_transcript(t, storage, config, bot_token, chat_id, people, email_index, alias_list)
        except Exception as e:
            print(f"  ERROR: transcript {t.uuid} failed, skipping: {e}", file=sys.stderr)

    # Persist registry with any new stubs
    registry["people"] = people
    _save_registry(registry)
    print(f"   Registry saved ({len(people)} entries).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: avoma_per_call failed: {exc}", file=sys.stderr)
        sys.exit(0)  # Non-fatal — never fail the Actions run
