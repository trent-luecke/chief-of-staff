"""Pre-meeting prep: classification, context assembly, Claude call, state I/O."""

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

import anthropic
from collectors.calendar import CalendarEvent
from processors.meeting_memory import load_meeting_index, find_meeting_for_event

def classify_meeting(event: CalendarEvent, config: dict) -> Optional[str]:
    """Return meeting prep type or None if this meeting should be skipped."""
    title = event.summary.lower()
    prep_cfg = config.get("meeting_prep", {})

    for pattern in prep_cfg.get("dept_heads_patterns", []):
        if pattern.lower() in title:
            return "dept_heads"

    for pattern in prep_cfg.get("recurring_internal_patterns", []):
        if pattern.lower() in title:
            return "recurring_internal"

    PERSONAL_KEYWORDS = {
        "haircut", "doctor", "dentist", "gym", "workout", "therapy",
        "appointment", "birthday", "anniversary", "vacation", "lunch",
        "dinner", "blocked", "focus time", "deep work", "no meetings", "ooo",
    }
    if any(kw in title for kw in PERSONAL_KEYWORDS):
        return None

    # External-meeting preps are disabled (Trent preps those deliberately).
    return None


def make_prep_key(event: CalendarEvent) -> str:
    return f"{event.id}_{date.today().isoformat()}"


_PREP_KEY = "meeting_preps.json"


def load_prep_state(storage) -> set:
    data = storage.read_json(_PREP_KEY, default={})
    return set(data.get("sent_keys", []))


def save_prep_state(sent_keys: set, storage) -> None:
    cutoff = date.today() - timedelta(days=7)

    def _key_date(k: str) -> date:
        try:
            return date.fromisoformat(k.rsplit("_", 1)[-1])
        except ValueError:
            return date.min

    recent = {k for k in sent_keys if _key_date(k) >= cutoff}
    storage.write_json(_PREP_KEY, {"sent_keys": sorted(recent)})


def _name_tokens(text: str) -> list[str]:
    if not text or not isinstance(text, str):
        return []
    parts = re.split(r"[-_.\s@:|/]", text.lower())
    return [p for p in parts if len(p) >= 3]


def _demo_count_from_engine():
    """Current-month demo count from the engine snapshot, or None on any failure."""
    try:
        from lib import metrics_client
        from lib.storage import LocalStorage
        base = os.environ.get("METRICS_BASE_URL", "")
        if not base:
            return None
        storage = LocalStorage(base_dir="data")
        snap = metrics_client.fetch_snapshot(base, os.environ.get("METRICS_PASSWORD", ""), storage)
        return (snap or {}).get("demos_data", {}).get("count")
    except Exception:
        return None


def _format_demos_line() -> str:
    n = _demo_count_from_engine()
    return f"• Demos MTD: {n}" if n is not None else "• Demos MTD: (unavailable)"


def _resolve_person_from_registry(
    registry_path: str, email: str
) -> tuple[Optional[str], list[str]]:
    """Return (person_id, all_known_emails) for the given email.

    Falls back to (None, [email]) when the person isn't found or the registry
    is absent. all_known_emails always contains at least the queried email.
    """
    try:
        with open(registry_path, encoding="utf-8") as f:
            data = json.load(f)
        email_lower = email.lower().strip()
        for person in data.get("people", []):
            primary = (person.get("email") or "").lower().strip()
            alias_emails = [
                a.lower().strip()
                for a in person.get("aliases", [])
                if "@" in a
            ]
            all_emails = list({e for e in [primary] + alias_emails if e})
            if email_lower in all_emails:
                return person["id"], all_emails
    except Exception:
        pass
    return None, [email]


def _find_people_file(people_dir: str, tokens: list[str]) -> Optional[str]:
    if not os.path.isdir(people_dir):
        return None
    for fname in sorted(os.listdir(people_dir)):
        if not fname.endswith(".md"):
            continue
        base = fname[:-3].lower()
        if any(re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", base) for t in tokens):
            return os.path.join(people_dir, fname)
    return None


def _find_pipeline_lead(pipeline_path: str, tokens: list[str]) -> Optional[dict]:
    try:
        with open(pipeline_path) as f:
            cache = json.load(f)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return None
    for lead in cache.get("leads", []):
        lead_text = (lead.get("name", "") + " " + lead.get("contact", "") + " " + lead.get("email", "")).lower()
        if any(t in lead_text for t in tokens):
            return lead
    return None


def _find_observations(
    obs_path: str,
    tokens: list[str],
    person_id: Optional[str] = None,
    limit: int = 5,
) -> list[str]:
    """Select relevant observations for a person.

    Observations stamped with primary_person_id are matched by ID only —
    prevents cross-person leakage and surfaces context that doesn't mention
    the person's name verbatim. Observations without a stamped ID (pre-migration)
    fall back to content-token matching.
    """
    lines = []
    try:
        with open(obs_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = obs.get("content", "")
                obs_pid = obs.get("primary_person_id")
                if obs_pid:
                    if person_id and obs_pid == person_id:
                        lines.append(f"{obs.get('date', '?')}: {content}")
                else:
                    if any(t in content.lower() for t in tokens):
                        lines.append(f"{obs.get('date', '?')}: {content}")
    except (FileNotFoundError, PermissionError):
        pass
    return lines[-limit:]


def build_dept_heads_context(config: dict) -> str:
    pipeline_path = config.get("pipeline", {}).get("cache_path", "data/pipeline_cache.json")
    projects_file = config.get("projects_file", "data/projects.md")
    captures_file = config.get("captures_file", "data/captures.md")
    sheets_cfg = config.get("meeting_prep", {}).get("sheets", {})
    sales_sheet_id = sheets_cfg.get("sales_spreadsheet_id", "")
    demos_sheet_id = sheets_cfg.get("demos_spreadsheet_id", "")
    parts = []

    try:
        with open(pipeline_path) as f:
            cache = json.load(f)
        leads = cache.get("leads", [])
        total = len(leads)
        by_status: dict[str, list] = {}
        for lead in leads:
            by_status.setdefault(lead.get("status") or "Unknown", []).append(lead)
        lines = [f"## Pipeline ({total} total)"]
        for status, group in sorted(by_status.items()):
            names = ", ".join(l.get("name", "?") for l in group[:3])
            suffix = "..." if len(group) > 3 else ""
            stale_count = sum(1 for l in group if l.get("stale"))
            line = f"• {status} ({len(group)}): {names}{suffix}"
            if stale_count:
                line += f" [{stale_count} stale]"
            lines.append(line)
        parts.append("\n".join(lines))
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        pass

    if sales_sheet_id or demos_sheet_id:
        from lib.google_auth import build_sheets_service
        from collectors.sheets import month_label, fetch_sales_mtd
        try:
            svc = build_sheets_service()
            cur_label = month_label(0)
            is_first_of_month = date.today().day <= 7

            kpi_lines = [f"## Sales & Demos — {cur_label} MTD"]
            if sales_sheet_id:
                sales = fetch_sales_mtd(svc, sales_sheet_id, cur_label)
                kpi_lines.append(f"• New Sales MTD: {sales['count']} deals, ${sales['revenue']:,.0f}")
                if is_first_of_month:
                    prior = fetch_sales_mtd(svc, sales_sheet_id, month_label(-1))
                    kpi_lines.append(f"• {month_label(-1)} Final: {prior['count']} deals, ${prior['revenue']:,.0f}")
            if demos_sheet_id:
                kpi_lines.append(_format_demos_line())
            parts.append("\n".join(kpi_lines))
        except Exception as e:
            parts.append(f"## Sales & Demos\n(unavailable: {e})")

    if os.path.exists(projects_file):
        try:
            with open(projects_file) as f:
                parts.append("## Active Projects\n" + f.read()[:2000])
        except OSError:
            pass

    if os.path.exists(captures_file):
        try:
            with open(captures_file) as f:
                content = f.read().strip()
            if content:
                parts.append("## Open Items & Flags\n" + content[:1000])
        except OSError:
            pass

    return "\n\n".join(parts)


def build_recurring_internal_context(event: CalendarEvent, config: dict) -> str:
    if not event.summary:
        return ""

    obs_path = config.get("memory", {}).get("observations_file", "data/memory/observations.jsonl")
    projects_file = config.get("projects_file", "data/projects.md")
    captures_file = config.get("captures_file", "data/captures.md")

    parts = []

    meeting_index = load_meeting_index(config.get("meeting_index_file", "data/meeting_index.json"))
    meeting_cfg = find_meeting_for_event(event, meeting_index)

    if meeting_cfg:
        import lib.meetings as meetings_lib
        state = meetings_lib.replay_local(config.get("data_dir", "data"))
        mtg = state.get(meeting_cfg.meeting_id)
        if mtg:
            rendered = meetings_lib.render_for_prep(mtg)
            if rendered.strip():
                parts.append(rendered.strip())

    if not parts:
        tokens = _name_tokens(event.summary)
        obs = _find_observations(obs_path, tokens, limit=10)
        if obs:
            parts.append("## Recent Context\n" + "\n".join(f"• {o}" for o in obs))

    if os.path.exists(projects_file):
        try:
            with open(projects_file) as f:
                parts.append("## Active Projects\n" + f.read()[:2000])
        except OSError:
            pass

    if os.path.exists(captures_file):
        try:
            with open(captures_file) as f:
                content = f.read().strip()
            if content:
                parts.append("## Open Captures\n" + content[:1000])
        except OSError:
            pass

    return "\n\n".join(parts)


_SYSTEM_PROMPTS = {
    "dept_heads": (
        "You are Trent Luecke's AI Chief of Staff preparing him for the Department Heads meeting. "
        "Trent is VP of Sales at TeamBuildr OS. "
        "Generate a structured KPI prep brief with these sections:\n\n"
        "**Pipeline**\n[Total count + breakdown by stage. Call out stale counts.]\n\n"
        "**Sales & Demos**\n[MTD new sales count and revenue. MTD demos count. If prior month totals are provided, include them.]\n\n"
        "**Active Projects**\n[2-3 most important active projects and their next actions]\n\n"
        "**Bottlenecks / Cross-Department Needs**\n[Synthesize from open flags and items — anything blocked waiting on another team. If nothing clear, say 'None flagged'.]\n\n"
        "Plain text only. No preamble."
    ),
    "recurring_internal": (
        "You are Trent Luecke's AI Chief of Staff preparing him for a recurring internal meeting. "
        "Generate a structured prep brief with these sections:\n\n"
        "**Last Time**\n[Key things from the most recent prior context — what was discussed or decided]\n\n"
        "**Open Items**\n[Unresolved threads or action items relevant to this meeting]\n\n"
        "**Projects to Touch**\n[1-3 active projects most relevant to this person with their next actions]\n\n"
        "**Suggested Focus**\n[1-2 sentence recommended agenda for this meeting]\n\n"
        "Plain text only. No preamble."
    ),
}

_EMOJI = {
    "dept_heads": "📊",
    "recurring_internal": "📋",
}


def build_prep_message(
    event: CalendarEvent,
    meeting_type: str,
    config: dict,
    api_key: str,
) -> Optional[str]:
    if meeting_type not in _SYSTEM_PROMPTS:
        raise ValueError(f"Unknown meeting_type: {meeting_type!r}. Must be one of: {list(_SYSTEM_PROMPTS)}")
    if meeting_type == "dept_heads":
        context = build_dept_heads_context(config)
    else:
        context = build_recurring_internal_context(event, config)

    model = config.get("ai_model", "claude-sonnet-4-6")
    user_content = f"Meeting: {event.summary}\n\n{context}" if context else f"Meeting: {event.summary}"

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=600,
        system=_SYSTEM_PROMPTS[meeting_type],
        messages=[{"role": "user", "content": user_content}],
    )
    try:
        from lib.llm_logger import log_usage
        log_usage("meeting_prep", response.usage, model)
    except Exception:
        pass
    if not response.content:
        raise ValueError(f"Claude returned empty content for meeting: {event.summary}")
    body = response.content[0].text.strip()
    emoji = _EMOJI.get(meeting_type, "📋")
    return f"{emoji} {event.summary}\n\n{body}"
