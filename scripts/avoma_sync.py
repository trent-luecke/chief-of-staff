#!/usr/bin/env python3
"""Nightly Avoma sync — routes OS sales calls to pipeline and onboarding update payloads."""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

_SEEN_PATH = _ROOT / "data" / "state" / "avoma_sync_seen.json"


def _load_seen() -> set[str]:
    try:
        return set(json.loads(_SEEN_PATH.read_text()))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    _SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SEEN_PATH.write_text(json.dumps(sorted(seen)))

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


def _infer_pipeline_status(transcript) -> str:
    """Map call type + signals to a pipeline status string."""
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
        if transcript.objections:
            return "On-Hold"
        return "Out of Demo / Need Update"

    return "Post Demo"


def _infer_account_owner(participants: list[str]) -> str:
    """Return the first rep name found in the participants list."""
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


def _extract_lead_name(title: str) -> str:
    """Strip common meeting-title prefixes to get the prospect/customer name."""
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


def _lead_in_pipeline(lead_name: str, pipeline_leads: list[dict]) -> bool:
    """Case-insensitive substring match against pipeline cache lead names."""
    name_lower = lead_name.lower()
    for lead in pipeline_leads:
        cached = (lead.get("name") or "").lower()
        if name_lower and (name_lower in cached or cached in name_lower):
            return True
    return False


def _patch_cache_last_contacted(cache_path: Path, pipeline_updates: list[dict]) -> int:
    """Patch last_contacted, days_since_contact, and stale in the local pipeline cache by name match.

    Only updates a lead if the call date is strictly more recent than what's already stored.
    Returns count of leads patched.
    """
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except Exception:
        return 0

    leads = cache.get("leads", [])
    today = date.today()
    changed = 0

    for u in pipeline_updates:
        name_lower = u["lead_name"].lower()
        call_date = u["call_date"]

        for lead in leads:
            cached_name = (lead.get("name") or "").lower()
            if not (name_lower and (name_lower in cached_name or cached_name in name_lower)):
                continue
            existing = lead.get("last_contacted") or ""
            if existing and existing >= call_date:
                break  # matched but not newer — skip without marking unmatched
            lead["last_contacted"] = call_date
            try:
                days = (today - date.fromisoformat(call_date)).days
            except (ValueError, TypeError):
                days = None
            lead["days_since_contact"] = days
            lead["stale"] = bool(days is not None and days >= 14)
            changed += 1
            break

    if changed:
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2)

    return changed


def build_slack_message(
    pipeline_updates: list[dict],
    onboarding_updates: list[dict],
    today: str,
) -> str:
    if not pipeline_updates and not onboarding_updates:
        return f"📞 Avoma Sync — {today}\n\nNo new OS calls in the last 24 hours."

    parts = [f"📞 Avoma Sync — {today}"]

    if pipeline_updates:
        parts.append("\n*Pipeline Updates*")
        for u in pipeline_updates:
            ct = u["call_type"].replace("_", " ").title()
            line = f"• {u['lead_name']} ({ct})\n  Call date: {u['call_date']}\n  Status → {u['inferred_status']}\n  {u['summary']}"
            if u.get("is_new_lead"):
                line += f"\n  ⚠️ Not in pipeline — create new record (owner: {u['account_owner']})"
            parts.append(line)

    if onboarding_updates:
        parts.append("\n*Onboarding Updates*")
        for u in onboarding_updates:
            completed = ", ".join(u["onboarding_completed"]) if u["onboarding_completed"] else "none noted"
            line = (
                f"• {u['customer_name']}\n"
                f"  Call date: {u['call_date']}\n"
                f"  Completed: {completed}\n"
                f"  {u['summary']}"
            )
            parts.append(line)

    return "\n".join(parts)


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")

    from collectors.avoma import DEMO_REP_ROSTER, fetch_recent_meetings
    from lib.slack_post import open_dm, post_message

    avoma_key = os.environ.get("AVOMA_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")

    for name, val in [
        ("AVOMA_API_KEY", avoma_key),
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("SLACK_BOT_TOKEN", slack_token),
    ]:
        if not val:
            print(f"ERROR: {name} not set — avoma_sync cannot run.", file=sys.stderr)
            return

    config_path = _ROOT / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    avoma_cfg = config.get("avoma", {})
    slack_user_id = avoma_cfg.get("slack_user_id", "")
    if not slack_user_id:
        print("ERROR: avoma.slack_user_id not set in config.json — avoma_sync cannot run.", file=sys.stderr)
        return
    ai_model = config.get("ai_model", "claude-sonnet-4-6")

    # Load pipeline cache for lead matching
    pipeline_leads: list[dict] = []
    try:
        cache_path = _ROOT / config.get("pipeline", {}).get("cache_path", "data/pipeline_cache.json")
        with open(cache_path) as f:
            pipeline_leads = json.load(f).get("leads", [])
        print(f"   Loaded {len(pipeline_leads)} pipeline leads for matching.")
    except Exception as e:
        print(f"WARNING: Could not load pipeline cache: {e}", file=sys.stderr)

    today = date.today().isoformat()

    lookback = config.get("demos", {}).get("lookback_hours", 72)
    print(f"🎙️  Fetching Avoma meetings (last {lookback}h)...")
    transcripts = fetch_recent_meetings(
        api_key=avoma_key,
        anthropic_api_key=anthropic_key,
        model=ai_model,
        lookback_hours=lookback,
        rep_roster=DEMO_REP_ROSTER,
        sales_rep_emails=avoma_cfg.get("sales_rep_emails", []),
        filter_internal=avoma_cfg.get("filter_internal", True),
    )
    print(f"   Found {len(transcripts)} OS-interested meeting(s).")

    # ── Push detected OS demos to the metrics engine (idempotent by UUID) ──
    try:
        from lib.demo_detect import detect_demos
        from lib import metrics_client
        counted = set(config.get("demos", {}).get("counted_reps", []))
        base_url = os.environ.get("METRICS_BASE_URL", "")
        password = os.environ.get("METRICS_PASSWORD", "")
        demo_records = detect_demos(transcripts, counted)
        if demo_records and base_url:
            result = metrics_client.push_demos(base_url, password, demo_records)
            print(f"   Demos pushed: {len(demo_records)} → {result}")
        else:
            print(f"   Demos detected: {len(demo_records)} (push skipped: no base_url)" if not base_url
                  else "   No demos detected this window.")
    except Exception as e:
        print(f"⚠️  Demo detection/push error (non-fatal): {e}", file=sys.stderr)

    # Filter transcripts to only unseen ones for Slack dedup
    seen = _load_seen()
    new_transcripts = [t for t in transcripts if getattr(t, "uuid", None) not in seen]
    print(f"   New (unseen) meetings for Slack: {len(new_transcripts)} of {len(transcripts)}.")

    pipeline_updates: list[dict] = []
    onboarding_updates: list[dict] = []

    for t in new_transcripts:
        call_date = _format_call_date(t.start_at)
        lead_name = _extract_lead_name(t.title)

        if t.call_type in ("demo", "follow_up"):
            is_new = not _lead_in_pipeline(lead_name, pipeline_leads)
            pipeline_updates.append({
                "lead_name": lead_name,
                "call_type": t.call_type,
                "call_date": call_date,
                "inferred_status": _infer_pipeline_status(t),
                "summary": t.summary,
                "is_new_lead": is_new,
                "account_owner": _infer_account_owner(t.participants) if is_new else None,
                "buying_signals": t.buying_signals,
                "objections": t.objections,
            })

        elif t.call_type == "onboarding":
            next_steps = t.onboarding_next_steps
            completed = t.onboarding_completed
            if completed and not next_steps:
                status_update = "Phase complete — advance to next phase"
            elif next_steps:
                status_update = (
                    f"Next: {next_steps[0]}"
                    if len(next_steps) == 1
                    else f"Next: {next_steps[0]} (+{len(next_steps) - 1} more)"
                )
            else:
                status_update = "In progress"

            onboarding_updates.append({
                "customer_name": lead_name,
                "call_date": call_date,
                "onboarding_completed": completed,
                "onboarding_next_steps": next_steps,
                "status_update": status_update,
                "summary": t.summary,
            })

    # Patch pipeline cache last_contacted for matched leads
    if pipeline_updates:
        patched = _patch_cache_last_contacted(cache_path, pipeline_updates)
        if patched:
            print(f"   Pipeline cache patched: {patched} lead(s) updated.")
        else:
            print("   Pipeline cache: no name matches found — no patch applied.")

    # Build and send Slack DM
    slack_text = build_slack_message(pipeline_updates, onboarding_updates, today)
    try:
        slack_channel = open_dm(slack_token, slack_user_id)
        post_message(slack_token, slack_channel, slack_text)
        print("   Slack DM sent.")
        # Save seen UUIDs only after a successful Slack send
        new_uuids = {getattr(t, "uuid", None) for t in new_transcripts if getattr(t, "uuid", None)}
        if new_uuids:
            seen.update(new_uuids)
            _save_seen(seen)
    except Exception as exc:
        print(f"ERROR: Slack send failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: avoma_sync failed: {exc}", file=sys.stderr)
        sys.exit(0)  # Non-fatal — don't fail the GitHub Actions job
