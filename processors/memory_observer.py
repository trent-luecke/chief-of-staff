import json
import re
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

from collectors.avoma import AvomaTranscript
from collectors.gmail import EmailThread
from collectors.pipeline import PipelineLead
from processors.brief import BriefContent
from processors.issues import Issue

_OBS_KEY = "memory/observations.jsonl"
_DECISIONS_FILE = "data/memory/decisions.md"  # human-authored, raw open()
_REGISTRY_FILE = Path("data/people_registry.json")
_INTERNAL_DOMAIN = "teambuildr.com"
_FUZZY_THRESHOLD = 85


def _load_registry() -> tuple[dict, list, set]:
    """Load the people registry and return fast-lookup structures.

    Returns:
        email_index:  lowercase email → person id
        alias_list:   [(canonical_name, [non-email aliases], person_id), ...]
        internal_ids: set of person_ids with type "internal"

    Non-fatal: returns empty structures if registry file is absent.
    """
    email_index: dict[str, str] = {}
    alias_list: list[tuple[str, list[str], str]] = []
    internal_ids: set[str] = set()
    try:
        if not _REGISTRY_FILE.exists():
            return email_index, alias_list, internal_ids
        people = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8")).get("people", [])
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
    except Exception:
        pass
    return email_index, alias_list, internal_ids


def _resolve_name(name: str, alias_list: list) -> str | None:
    """Return person_id for name if fuzzy match meets threshold, else None."""
    best_id, best_score = None, 0
    for _canonical, aliases, pid in alias_list:
        for alias in aliases:
            score = fuzz.token_sort_ratio(name.lower(), alias.lower())
            if score > best_score:
                best_score, best_id = score, pid
    return best_id if best_score >= _FUZZY_THRESHOLD else None


def _resolve_email(email: str, email_index: dict) -> str | None:
    return email_index.get(email.lower().strip())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _load_known_decision_dates(storage) -> set[str]:
    known = set()
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            if obs.get("type") == "decision":
                known.add(obs.get("content", "").strip())
        except json.JSONDecodeError:
            continue
    return known


def _read_decisions(decisions_file: str, known_contents: set[str]) -> list[dict]:
    observations = []
    try:
        with open(decisions_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Format: YYYY-MM-DD: <text>
                if ":" not in line:
                    continue
                date_part, _, text = line.partition(":")
                text = text.strip()
                if text and text not in known_contents:
                    observations.append({
                        "date": date.today().isoformat(),
                        "type": "decision",
                        "entity": "manual",
                        "content": text,
                        "source": "manual",
                    })
    except FileNotFoundError:
        pass
    return observations


def _load_ingested_avoma_uuids(storage) -> set[str]:
    """Return Avoma meeting UUIDs already present in observations."""
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


def _transcript_to_observation(
    t: AvomaTranscript,
    alias_list: list,
    internal_ids: set,
) -> dict:
    today = date.today().isoformat()

    meeting_date = today
    if t.start_at:
        try:
            meeting_date = t.start_at[:10]
        except (ValueError, IndexError):
            pass

    call_label = t.call_type.replace("_", " ").title() if t.call_type else "Meeting"
    header = f"{call_label}: {t.title}"
    if t.participants:
        header += f" ({', '.join(t.participants[:5])})"

    body_parts = [header + "."]
    if t.summary:
        body_parts.append(t.summary.rstrip(".") + ".")
    if t.features_covered:
        body_parts.append(f"Features covered: {'; '.join(t.features_covered[:5])}.")
    if t.gaps:
        body_parts.append(f"Gaps raised: {'; '.join(t.gaps[:4])}.")
    if t.objections:
        body_parts.append(f"Objections: {'; '.join(t.objections[:4])}.")
    if t.buying_signals:
        body_parts.append(f"Buying signals: {'; '.join(t.buying_signals[:4])}.")
    if t.competitors:
        body_parts.append(f"Competitors: {'; '.join(t.competitors)}.")
    if t.onboarding_completed:
        body_parts.append(f"Onboarding completed: {'; '.join(t.onboarding_completed[:4])}.")
    if t.onboarding_next_steps:
        body_parts.append(f"Onboarding next steps: {'; '.join(t.onboarding_next_steps[:4])}.")
    if t.action_items:
        body_parts.append(f"Action items: {'; '.join(t.action_items[:5])}.")

    entity = t.title.lower().replace(" ", "-")[:60]
    participants_str = ", ".join(t.participants[:5])

    # Resolve participants to registry IDs using structured list (not context parsing)
    primary_person_id: str | None = None
    related_person_ids: list[str] = []
    if t.participants and alias_list:
        resolved_external: list[str] = []
        resolved_internal: list[str] = []
        for name in t.participants:
            pid = _resolve_name(name, alias_list)
            if pid is None:
                continue
            if pid in internal_ids:
                resolved_internal.append(pid)
            else:
                resolved_external.append(pid)
        if resolved_external:
            primary_person_id = resolved_external[0]
            related_person_ids = resolved_external[1:] + resolved_internal
        elif resolved_internal:
            primary_person_id = resolved_internal[0]
            related_person_ids = resolved_internal[1:]

    return {
        "date": meeting_date,
        "type": "meeting_transcript",
        "entity": entity,
        "primary_person_id": primary_person_id,
        "related_person_ids": related_person_ids,
        "content": " ".join(body_parts)[:1000],
        "source": "avoma",
        "context": f"avoma_uuid={t.uuid} call_type={t.call_type} participants={participants_str}",
    }


def _kpi_snapshot_exists_today(storage) -> bool:
    """Return True if a kpi_snapshot for today already exists in storage."""
    today = date.today().isoformat()
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
            if obs.get("type") == "kpi_snapshot" and obs.get("date") == today:
                return True
        except json.JSONDecodeError:
            continue
    return False


def _build_kpi_snapshot(
    pipeline_leads,
    sales_data: dict,
    demos_data: dict,
    bugs: list,
    cancellations: dict,
) -> dict:
    """Build a kpi_snapshot observation dict from collected KPI data."""
    today = date.today().isoformat()

    sales_revenue = sales_data.get("revenue", 0.0) if sales_data else 0.0
    sales_count = sales_data.get("count", 0) if sales_data else 0
    demo_count = demos_data.get("count", 0) if demos_data else 0
    cancel_count = cancellations.get("count", 0) if cancellations else 0

    # Pipeline breakdown by status
    pipeline_by_status: dict[str, int] = {}
    for lead in (pipeline_leads or []):
        status = getattr(lead, "status", None) or lead.get("status", "Unknown") if isinstance(lead, dict) else getattr(lead, "status", "Unknown")
        pipeline_by_status[status] = pipeline_by_status.get(status, 0) + 1

    pipeline_str = ", ".join(f"{count} {status}" for status, count in pipeline_by_status.items())
    if not pipeline_str:
        pipeline_str = "0 leads"

    # Bug breakdown by priority
    open_bugs = [b for b in (bugs or []) if (b.get("status") if isinstance(b, dict) else getattr(b, "status", "")) != "Done"]
    bug_count = len(open_bugs)
    def _priority(b):
        return b.get("priority_level") if isinstance(b, dict) else getattr(b, "priority_level", "")
    high = sum(1 for b in open_bugs if _priority(b) == "High")
    moderate = sum(1 for b in open_bugs if _priority(b) == "Moderate")
    low = sum(1 for b in open_bugs if _priority(b) == "Low")

    content = (
        f"KPI snapshot {today}: "
        f"Sales MTD ${sales_revenue:,.0f} ({sales_count} deals). "
        f"Demos MTD: {demo_count}. "
        f"Pipeline: {pipeline_str}. "
        f"Open bugs: {bug_count} ({high} High, {moderate} Moderate, {low} Low). "
        f"Cancellations MTD: {cancel_count}."
    )

    context = (
        f"sales_revenue={int(sales_revenue)} sales_count={sales_count} "
        f"demos={demo_count} open_bugs={bug_count} bugs_high={high} "
        f"cancellations_mtd={cancel_count}"
    )

    return {
        "date": today,
        "type": "kpi_snapshot",
        "entity": "daily",
        "content": content,
        "source": "kpi",
        "context": context,
    }


def observe(
    storage,
    decisions_file: str,
    email_threads: list[EmailThread],
    still_open_ids: dict,
    pipeline_leads: list[PipelineLead],
    brief: BriefContent,
    issues: list[Issue],
    sales_data: dict | None = None,
    demos_data: dict | None = None,
    bugs: list | None = None,
    cancellations: dict | None = None,
    avoma_transcripts: list[AvomaTranscript] | None = None,
) -> None:
    today = date.today().isoformat()
    observations = []

    # Load registry once for person resolution (non-fatal if absent)
    email_index, alias_list, internal_ids = _load_registry()

    # email_loop: threads still open from previous run
    still_open_email = set(still_open_ids.get("email", []))
    thread_map = {t.id: t for t in email_threads}
    for thread_id in still_open_email:
        thread = thread_map.get(thread_id)
        if thread:
            observations.append({
                "date": today,
                "type": "email_loop",
                "entity": f"thread:{thread.subject}",
                "primary_person_id": None,
                "related_person_ids": [],
                "content": "Thread open multiple days, no reply",
                "source": "state",
                "context": thread.snippet[:200] if thread.snippet else "",
            })

    # pipeline_stale
    for lead in pipeline_leads:
        if lead.stale or (lead.days_since_contact and lead.days_since_contact > 7):
            days = lead.days_since_contact or 0
            person_id = _resolve_name(lead.name, alias_list)
            observations.append({
                "date": today,
                "type": "pipeline_stale",
                "entity": lead.name.lower().replace(" ", "-"),
                "primary_person_id": person_id,
                "related_person_ids": [],
                "content": f"{lead.name} stale {days} days, status: {lead.status}",
                "source": "pipeline",
            })

    # top_priority — system-level, not person-keyed
    for priority in (brief.top_3_priorities or []):
        observations.append({
            "date": today,
            "type": "top_priority",
            "entity": "priorities",
            "primary_person_id": None,
            "related_person_ids": [],
            "content": priority,
            "source": "brief",
        })

    # issue_pattern — system-level, not person-keyed
    for issue in issues:
        try:
            age_days = issue.age_days
        except (ValueError, TypeError, AttributeError):
            age_days = 0
        observations.append({
            "date": today,
            "type": "issue_pattern",
            "entity": issue.channel or issue.source,
            "primary_person_id": None,
            "related_person_ids": [],
            "content": f"{issue.title} (age: {age_days}d, status: {issue.status})",
            "source": "issues",
            "context": f"source: {issue.source}#{issue.channel}",
        })

    # decisions from decisions.md (only new ones) — system-level, not person-keyed
    known_decision_contents = _load_known_decision_dates(storage)
    for obs in _read_decisions(decisions_file, known_decision_contents):
        obs["primary_person_id"] = None
        obs["related_person_ids"] = []
        observations.append(obs)

    # kpi_snapshot — written once per day, system-level
    # None means "collector not configured"; [] or {"count":0} means "ran but found nothing" — both trigger snapshot
    has_kpi = any(p is not None for p in [sales_data, demos_data, bugs, cancellations])
    if has_kpi and not _kpi_snapshot_exists_today(storage):
        snap = _build_kpi_snapshot(
            pipeline_leads=pipeline_leads,
            sales_data=sales_data or {},
            demos_data=demos_data or {},
            bugs=bugs or [],
            cancellations=cancellations or {},
        )
        snap["primary_person_id"] = None
        snap["related_person_ids"] = []
        observations.append(snap)

    # meeting_transcript — one observation per Avoma meeting, deduped by UUID
    if avoma_transcripts:
        seen_uuids = _load_ingested_avoma_uuids(storage)
        for transcript in avoma_transcripts:
            if transcript.uuid not in seen_uuids:
                observations.append(
                    _transcript_to_observation(transcript, alias_list, internal_ids)
                )

    if not observations:
        return

    for obs in observations:
        storage.append_line(_OBS_KEY, json.dumps(obs))
