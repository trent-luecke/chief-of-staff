"""Pre-meeting prep: classification, context assembly, Claude call, state I/O."""

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

import anthropic
from collectors.calendar import CalendarEvent

EXTERNAL_KEYWORDS = {"demo", "reconnect", "intro", "pitch", "walkthrough", "onboarding", "call"}


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

    has_external_keyword = any(kw in title for kw in EXTERNAL_KEYWORDS)
    has_external_attendee = any(
        "@teambuildr.com" not in a.lower() for a in event.attendees
    )

    if has_external_keyword or (event.attendees and has_external_attendee):
        return "external"

    return None


def make_prep_key(event: CalendarEvent) -> str:
    return f"{event.id}_{date.today().isoformat()}"


def load_prep_state(path: str) -> set:
    try:
        with open(path) as f:
            data = json.load(f)
        return set(data.get("sent_keys", []))
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return set()


def save_prep_state(sent_keys: set, path: str) -> None:
    cutoff = date.today() - timedelta(days=7)

    def _key_date(k: str) -> date:
        try:
            return date.fromisoformat(k.rsplit("_", 1)[-1])
        except ValueError:
            return date.min  # prune malformed keys immediately

    recent = {k for k in sent_keys if _key_date(k) >= cutoff}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({"sent_keys": sorted(recent)}, f, indent=2)


def _name_tokens(text: str) -> list[str]:
    if not text or not isinstance(text, str):
        return []
    parts = re.split(r"[-_.\s@:|/]", text.lower())
    return [p for p in parts if len(p) >= 3]


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


def _find_observations(obs_path: str, tokens: list[str], limit: int = 5) -> list[str]:
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
                if any(t in content.lower() for t in tokens):
                    lines.append(f"{obs.get('date', '?')}: {content}")
    except (FileNotFoundError, PermissionError):
        pass
    return lines[-limit:]


def build_external_context(event: CalendarEvent, config: dict) -> str:
    people_dir = config.get("people_dir", "data/people")
    pipeline_path = config.get("pipeline", {}).get("cache_path", "data/pipeline_cache.json")
    obs_path = config.get("memory", {}).get("observations_file", "data/memory/observations.jsonl")

    tokens = _name_tokens(event.summary)
    for attendee in event.attendees:
        local = attendee.split("@")[0]
        tokens += _name_tokens(local)
    tokens = list(set(tokens))

    parts = []

    people_path = _find_people_file(people_dir, tokens)
    if people_path:
        try:
            with open(people_path) as f:
                parts.append("## Contact Background\n" + f.read()[:800])
        except OSError:
            pass

    lead = _find_pipeline_lead(pipeline_path, tokens)
    if lead:
        days = f"{lead.get('days_since_contact')}d ago" if lead.get("days_since_contact") is not None else "unknown"
        val = f"${lead['estimated_value']:,.0f}" if lead.get("estimated_value") else ""
        stale = " [STALE]" if lead.get("stale") else ""
        lines = [
            f"Name: {lead.get('name', '?')}",
            f"Status: {lead.get('status', '?')}{stale}",
            f"Last contact: {days}",
        ]
        if val:
            lines.append(f"Est. value: {val}")
        parts.append("## Pipeline Record\n" + "\n".join(lines))

    obs = _find_observations(obs_path, tokens)
    if obs:
        parts.append("## Recent Context\n" + "\n".join(f"• {o}" for o in obs))

    return "\n\n".join(parts)


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
            by_status.setdefault(lead.get("status", "Unknown"), []).append(lead)
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
        try:
            from lib.google_auth import build_sheets_service
            from collectors.sheets import month_label, fetch_sales_mtd, fetch_demos_mtd
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
                demos = fetch_demos_mtd(svc, demos_sheet_id, cur_label)
                kpi_lines.append(f"• Demos MTD: {demos['count']}")
                if is_first_of_month:
                    prior_demos = fetch_demos_mtd(svc, demos_sheet_id, month_label(-1))
                    kpi_lines.append(f"• {month_label(-1)} Final Demos: {prior_demos['count']}")
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
    obs_path = config.get("memory", {}).get("observations_file", "data/memory/observations.jsonl")
    projects_file = config.get("projects_file", "data/projects.md")
    captures_file = config.get("captures_file", "data/captures.md")

    tokens = _name_tokens(event.summary)
    parts = []

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
