"""Phase 1 Avoma processing — runs ONCE per Slack thread on first qualifying reply.

Finds the Avoma transcript from the thread's root message (UUID extraction or
title-match fallback), writes the observation, posts output to the Slack thread,
and marks the thread as processed in avoma_thread_state.
"""

from __future__ import annotations
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from collectors.avoma import extract_avoma_uuid_from_text, fetch_meeting_by_uuid, fetch_recent_meetings
from lib.slack_post import get_thread_root_text, post_to_thread
from processors.avoma_thread_state import is_processed, set_phase1_complete

_ROOT = Path(__file__).parent.parent
_REGISTRY_FILE = _ROOT / "data" / "people_registry.json"
_OBS_KEY = "memory/observations.jsonl"
_INTERNAL_DOMAIN = "teambuildr.com"
_FUZZY_THRESHOLD = 85
_SALES_REP_MAP = {
    "ryan@teambuildr.com": "Ryan",
    "lmartin@teambuildr.com": "Martin",
    "chris@teambuildr.com": "Chris",
    "jeff@teambuildr.com": "Jeff",
    "quinn@teambuildr.com": "Quinn",
    "trent@teambuildr.com": "Trent",
}
_NO_SHOW_KEYWORDS = ("no-show", "no show", "did not attend", "didn't attend")
_STRONG_SIGNAL_KEYWORDS = ("contract", "pricing", "timeline", "next step", "trial", "ready to start", "implement", "sign")
_READY_PHRASES = frozenset({"ready to process", "ready", "process", "go", "process this", "ready to go"})


# ---------------------------------------------------------------------------
# Registry helpers (copied from scripts/avoma_per_call.py — processors cannot
# import from scripts)
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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _unique_id(base: str, existing_ids: set) -> str:
    new_id, counter = base, 2
    while new_id in existing_ids:
        new_id = f"{base}-{counter}"
        counter += 1
    return new_id


def _is_internal(s: str) -> bool:
    return s.lower().endswith(f"@{_INTERNAL_DOMAIN}")


def _resolve_participants(participants: list[str], people: list, email_index: dict, alias_list: list) -> list[dict]:
    from rapidfuzz import fuzz
    today = date.today().isoformat()
    resolved: list[dict] = []
    existing_ids = {p["id"] for p in people}

    for participant in participants:
        participant = participant.strip()
        if not participant:
            continue
        is_email = "@" in participant

        if is_email:
            pid = email_index.get(participant.lower())
            if pid:
                for p in people:
                    if p["id"] == pid:
                        p["last_seen"] = today
                        resolved.append({"name": participant, "person_id": pid, "is_new": False,
                                         "is_internal": p.get("type") == "internal", "is_stub_only": False})
                        break
                continue
            if _is_internal(participant):
                resolved.append({"name": participant, "person_id": None, "is_new": False,
                                  "is_internal": True, "is_stub_only": False})
                continue
            display = participant.split("@")[0]
            new_id = _unique_id(_slug(display), existing_ids)
            existing_ids.add(new_id)
            stub = {"id": new_id, "canonical_name": display, "aliases": [display, participant],
                    "email": participant, "type": "unknown", "pipeline_record": None, "people_file": None,
                    "created": today, "last_seen": today}
            people.append(stub)
            email_index[participant.lower()] = new_id
            alias_list.append((display, [display], new_id))
            resolved.append({"name": participant, "person_id": new_id, "is_new": True,
                              "is_internal": False, "is_stub_only": True})
            continue

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

        if any(rep.lower() == participant.lower().split()[0] for rep in _SALES_REP_MAP.values()):
            resolved.append({"name": participant, "person_id": None, "is_new": False,
                              "is_internal": True, "is_stub_only": False})
            continue

        new_id = _unique_id(_slug(participant) if participant else "unknown", existing_ids)
        existing_ids.add(new_id)
        stub = {"id": new_id, "canonical_name": participant, "aliases": [participant], "email": "",
                "type": "unknown", "pipeline_record": None, "people_file": None,
                "created": today, "last_seen": today}
        people.append(stub)
        alias_list.append((participant, [participant], new_id))
        resolved.append({"name": participant, "person_id": new_id, "is_new": True,
                          "is_internal": False, "is_stub_only": True})

    return resolved


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def _write_observation(t, resolved_people: list, storage) -> None:
    from processors.memory_observer import _transcript_to_observation, _load_registry as _load_obs_registry
    _email_index, alias_list, internal_ids = _load_obs_registry()
    obs = _transcript_to_observation(t, alias_list, internal_ids)
    storage.append_line(_OBS_KEY, json.dumps(obs))


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

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


def _infer_pipeline_status(t) -> str:
    summary_lower = t.summary.lower()
    if any(kw in summary_lower for kw in _NO_SHOW_KEYWORDS):
        return "No-Show"
    if t.call_type == "demo":
        if t.buying_signals and any(
            any(kw in s.lower() for kw in _STRONG_SIGNAL_KEYWORDS)
            for s in t.buying_signals
        ):
            return "In-Trial / Post Demo"
        return "No Trial / Post Demo"
    if t.call_type == "follow_up":
        return "On-Hold" if t.objections else "Out of Demo / Need Update"
    return "Post Demo"


def _infer_account_owner(participants: list[str]) -> str:
    for p in participants:
        p_lower = p.lower().strip()
        for email, name in _SALES_REP_MAP.items():
            if email.lower() in p_lower:
                return name
    return "Unknown"


def _build_notion_prompt(t, lead_name: str) -> str:
    call_date = _format_call_date(t.start_at)
    call_label = t.call_type.replace("_", " ").title()
    owner = _infer_account_owner(t.participants)
    action_items_str = "; ".join(t.action_items[:6]) if t.action_items else "none"

    if t.call_type == "onboarding":
        completed = "; ".join(t.onboarding_completed) if t.onboarding_completed else "none noted"
        next_steps = "; ".join(t.onboarding_next_steps) if t.onboarding_next_steps else "none noted"
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


def _build_slack_message(t, lead_name: str, resolved_people: list, trigger_text: str) -> tuple[str, str | None]:
    """Return (summary_message, notion_payload | None) as separate strings.

    Notion payload is posted as a second message so it is never truncated.
    """
    call_label = t.call_type.replace("_", " ").title() if t.call_type else "Call"
    external = [r for r in resolved_people if not r["is_internal"]]
    participants_display = ", ".join(r["name"] for r in external) or ", ".join(t.participants[:5])

    lines = [
        f"*{lead_name}* — {call_label}",
        participants_display,
        "",
        "📧 *Follow-Up Email Recap*",
        t.email_recap or t.summary or "(no recap)",
    ]

    if t.action_items:
        lines += ["", "*Action Items*"]
        for i, item in enumerate(t.action_items[:8], 1):
            lines.append(f"{i}. {item}")

    new_stubs = [r for r in resolved_people if r["is_new"] and not r["is_internal"]]
    if new_stubs:
        names = ", ".join(r["name"] for r in new_stubs)
        lines += ["", f"⚠️ New contact(s) — stub only, no file yet: {names}"]

    notion_payload = None
    if t.os_interested and t.call_type in ("demo", "follow_up", "onboarding"):
        notion_payload = _build_notion_prompt(t, lead_name) or None

    return "\n".join(lines), notion_payload


# ---------------------------------------------------------------------------
# Transcript lookup
# ---------------------------------------------------------------------------

def _find_transcript(root_text: str, avoma_api_key: str, anthropic_api_key: str, config: dict, trigger_text: str = ""):
    """Find the Avoma transcript for a thread. UUID extraction first, title-match fallback.

    trigger_text is passed as a context note to Claude if it contains rep-supplied context
    (i.e. anything other than a bare 'ready to process' variant).
    """
    context_note = "" if trigger_text.strip().lower() in _READY_PHRASES else trigger_text.strip()
    uuid = extract_avoma_uuid_from_text(root_text)
    if uuid:
        model = config.get("ai_model", "claude-sonnet-4-6")
        return fetch_meeting_by_uuid(avoma_api_key, anthropic_api_key, model, uuid, context_note=context_note)

    avoma_cfg = config.get("avoma", {})
    model = config.get("ai_model", "claude-sonnet-4-6")
    try:
        transcripts = fetch_recent_meetings(
            api_key=avoma_api_key,
            anthropic_api_key=anthropic_api_key,
            model=model,
            lookback_hours=avoma_cfg.get("slack_trigger_lookback_hours", 168),
            sales_rep_emails=avoma_cfg.get("sales_rep_emails", []),
            filter_internal=avoma_cfg.get("filter_internal", True),
            include_non_os=True,
        )
    except Exception as e:
        print(f"WARNING: fetch_recent_meetings failed: {e}", file=sys.stderr)
        return None

    if not transcripts:
        return None

    root_lower = (root_text or "").lower()
    best, best_score = None, 0
    for t in transcripts:
        title_words = [w for w in t.title.lower().split() if len(w) > 3]
        score = sum(1 for w in title_words if w in root_lower)
        if score > best_score:
            best_score, best = score, t

    return best if best_score > 0 else transcripts[0]  # fall back to most recent


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_phase1(
    thread_ts: str,
    channel_id: str,
    trigger_text: str,
    storage,
    config: dict,
    avoma_api_key: str,
    anthropic_api_key: str,
    slack_bot_token: str,
) -> None:
    """Run Phase 1 processing for a Slack thread. Posts output; sets processed state. Idempotent."""
    if is_processed(storage, thread_ts):
        return

    root_text = get_thread_root_text(slack_bot_token, channel_id, thread_ts)
    transcript = _find_transcript(root_text, avoma_api_key, anthropic_api_key, config, trigger_text=trigger_text)

    if not transcript:
        post_to_thread(slack_bot_token, channel_id, thread_ts,
                       "Could not find an Avoma transcript for this thread. "
                       "Check that the meeting UUID is in the Avoma post, or try again after the transcript is ready.")
        return

    registry = _load_registry()
    people = registry["people"]
    email_index, alias_list = _build_lookup(people)
    resolved_people = _resolve_participants(transcript.participants, people, email_index, alias_list)

    try:
        _write_observation(transcript, resolved_people, storage)
    except Exception as e:
        print(f"WARNING: observation write failed for {transcript.uuid}: {e}", file=sys.stderr)

    lead_name = _extract_lead_name(transcript.title)
    summary_text, notion_payload = _build_slack_message(transcript, lead_name, resolved_people, trigger_text)
    output_ts = post_to_thread(slack_bot_token, channel_id, thread_ts, summary_text)
    if notion_payload:
        post_to_thread(slack_bot_token, channel_id, thread_ts, notion_payload)
    output_text = summary_text + ("\n\n" + notion_payload if notion_payload else "")

    transcript_json = {
        "uuid": transcript.uuid,
        "title": transcript.title,
        "start_at": transcript.start_at,
        "participants": transcript.participants,
        "call_type": transcript.call_type,
        "os_interested": transcript.os_interested,
        "summary": transcript.summary,
        "action_items": transcript.action_items,
        "features_covered": transcript.features_covered,
        "gaps": transcript.gaps,
        "objections": transcript.objections,
        "buying_signals": transcript.buying_signals,
        "competitors": transcript.competitors,
        "onboarding_completed": transcript.onboarding_completed,
        "onboarding_next_steps": transcript.onboarding_next_steps,
    }
    set_phase1_complete(storage, thread_ts, transcript.uuid, output_ts, output_text, transcript_json)

    registry["people"] = people
    _save_registry(registry)
    print(f"Phase 1 complete for thread {thread_ts}: {transcript.title}")
