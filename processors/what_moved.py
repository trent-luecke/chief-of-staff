from datetime import date, datetime, timedelta

WHAT_MOVED_CAP = 7


def _parse_date_m_d(date_str: str, year: int) -> date | None:
    try:
        parts = date_str.strip().split("/")
        return date(year, int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def _is_yesterday_m_d(date_str: str, today: date) -> bool:
    d = _parse_date_m_d(date_str, today.year)
    return d is not None and (today - d).days == 1


def _is_yesterday_iso(iso_str: str, today: date) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.date() == today - timedelta(days=1)
    except (ValueError, TypeError):
        return False


def build_what_moved_context(
    cancellations: dict,
    avoma_transcripts: list,
    onboarding_current: list[dict],
    onboarding_prev: list[dict],
    pipeline_current: list[dict],
    pipeline_prev: list[dict],
    today: date | None = None,
) -> str:
    """Build What Moved context section for the brief prompt.

    Returns a formatted string for injection into _build_prompt(), or empty
    string if no events found. Capped at WHAT_MOVED_CAP items sorted by
    priority (1=cancellation, 2=demo, 3=onboarding, 4=new lead) then
    oldest-to-newest for overflow ordering.
    """
    _today = today or date.today()
    events: list[dict] = []

    # 1. Cancellations (yesterday's date, M/D format)
    for entry in cancellations.get("entries", []):
        if _is_yesterday_m_d(entry.get("date", ""), _today):
            events.append({
                "priority": 1,
                "sort_key": entry.get("date", ""),
                "text": f"{entry.get('account_name', 'Unknown')} cancelled — {entry.get('reason', 'no reason given')}",
            })

    # 2. Unhosted demos from Avoma (yesterday only, call_type == "demo")
    for t in avoma_transcripts:
        if t.call_type == "demo" and _is_yesterday_iso(t.start_at, _today):
            participant = next((p for p in t.participants if p), "unknown participant")
            events.append({
                "priority": 2,
                "sort_key": t.start_at,
                "text": f"{participant} had a demo — {t.summary}",
            })

    # 3. Onboarding stage/phase changes (snapshot diff)
    prev_map = {r["page_id"]: r for r in onboarding_prev}
    for r in onboarding_current:
        prev = prev_map.get(r.get("page_id", ""))
        if prev is None:
            events.append({
                "priority": 3,
                "sort_key": r.get("start_date") or _today.isoformat(),
                "text": f"{r['customer_name']} entered onboarding ({r.get('status', 'unknown')})",
            })
        elif prev.get("status") != r.get("status") or prev.get("current_phase") != r.get("current_phase"):
            old = prev.get("current_phase") or prev.get("status", "unknown")
            new = r.get("current_phase") or r.get("status", "unknown")
            events.append({
                "priority": 3,
                "sort_key": _today.isoformat(),
                "text": f"{r['customer_name']} advanced: {old} → {new}",
            })

    # 4. New pipeline leads (name not in previous snapshot)
    prev_names = {r.get("name", "").strip().lower() for r in pipeline_prev}
    for r in pipeline_current:
        name = r.get("name", "").strip()
        if name and name.lower() not in prev_names:
            events.append({
                "priority": 4,
                "sort_key": r.get("last_contacted") or _today.isoformat(),
                "text": f"{name} entered pipeline ({r.get('status', 'unknown')})",
            })

    # Sort: priority first, then chronological (oldest first for cap overflow)
    events.sort(key=lambda e: (e["priority"], e["sort_key"] or ""))
    capped = events[:WHAT_MOVED_CAP]

    if not capped:
        return ""

    lines = [
        "## What Moved Yesterday (read-only — restate these as-is, do not add items)",
        *[f"  {e['text']}" for e in capped],
    ]
    return "\n".join(lines)
