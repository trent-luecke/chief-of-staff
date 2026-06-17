"""pipeline.py — Typed collect → process → generate pipeline for the morning brief."""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from collectors.calendar import fetch_two_day_events
from collectors.gmail import fetch_threads_needing_attention, filter_automated_threads
from collectors.local_data import load_projects, load_due_recurring_tasks, read_inbox
from collectors.notion_inbox import fetch_inbox_items
from collectors.pipeline import fetch_pipeline_leads, load_activity_overrides, PipelineLead
from collectors.gym_scout import fetch_recent_leads, GymScoutLead
from lib.pipeline_activity import (
    load_lead_email_index,
    load_lead_page_index,
    load_pipeline_activity,
    save_pipeline_activity,
    record_lead_contact,
    patch_pipeline_cache_last_contacted,
    update_notion_last_contacted,
    reconcile_activity_to_notion,
    extract_email as _extract_email,
)
from lib.health import RunHealth, StageResult, CollectorResult, timed
from processors.state import StateSnapshot, save_snapshot, load_snapshot, diff_snapshots
from processors.loops import build_loop_summary
from processors.issues import get_open_issues, auto_resolve_issues
from processors.meeting_memory import load_meeting_index, find_meeting_for_event
import lib.meetings as meetings_lib
from processors.brief import generate_brief, BriefContent
from processors.people import enrich_people
from outputs.sender import build_html_email, send_brief_email
from lib.google_auth import build_gmail_service
from outputs.dashboard import write_dashboard
from processors.memory_observer import observe
from processors.memory_synthesizer import synthesize
from processors.memory_retriever import retrieve_memories, get_cold_start_message
from lib.captures import load_recent_captures, load_brief_feedback, load_brief_prefs


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CollectedData:
    """Raw signals from all sources. Every field has a safe default."""

    # Calendar
    today_events: list = field(default_factory=list)
    tomorrow_events: list = field(default_factory=list)
    calendar_failed: bool = False

    # Email
    email_threads: list = field(default_factory=list)

    # Local data
    projects: list = field(default_factory=list)
    due_tasks: list = field(default_factory=list)
    inbox_text: str = ""

    # Notion
    notion_items: list = field(default_factory=list)

    # Issues
    open_issues: list = field(default_factory=list)

    # Pipeline
    trial_leads: list = field(default_factory=list)
    attention_leads: list = field(default_factory=list)
    all_pipeline_leads: list = field(default_factory=list)
    pipeline_cache_age_days: int | None = None

    # Gym scout
    gym_scout_leads: list = field(default_factory=list)

    # Bugs
    bugs: list = field(default_factory=list)

    # Sheets / metrics engine
    sales_data: dict | None = None
    demos_data: dict | None = None
    cancellations: dict = field(default_factory=lambda: {"count": 0, "entries": []})
    metrics_snapshot: dict | None = None

    # Slack
    slack_dms: list = field(default_factory=list)

    # Avoma meeting transcripts
    avoma_transcripts: list = field(default_factory=list)


@dataclass
class ProcessedContext:
    """Enriched context ready for brief generation."""

    # Pass-through from collection (brief generator needs these directly)
    collected: CollectedData

    # Enriched / derived
    people_context: str = ""
    memory_context: str = ""
    memory_cold_start_msg: str | None = None
    meeting_prep: list = field(default_factory=list)
    loop_summary: dict = field(default_factory=dict)
    captures_context: str = ""
    notes_context: str = ""
    brief_feedback_context: str = ""
    brief_prefs_context: str = ""

    # State diffing (needed by post-brief memory observer)
    previous_state: Any = None
    still_open: dict = field(default_factory=lambda: {"email": [], "notion": []})
    today_email_ids: list = field(default_factory=list)
    today_notion_ids: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper functions (moved from main.py)
# ---------------------------------------------------------------------------

def _brief_already_sent_today(storage) -> bool:
    """True if a brief email was already successfully sent today.

    Idempotency guard for dual triggers: the punctual Cloudflare cron fires the
    brief at 7am sharp, and the GitHub `schedule:` backstop fires it later (often
    hours late). Whichever sends first writes state/brief_message_id.json; the
    other run sees today's date here and skips the send — so never two emails.
    """
    prev = storage.read_json("state/brief_message_id.json")
    return bool(prev and prev.get("date") == date.today().isoformat())


def _save_brief_message_id(storage, message_id: str, thread_id: str, subject: str) -> None:
    # Overwrites on same-day re-run; replies to earlier send will be missed.
    storage.write_json("state/brief_message_id.json", {
        "message_id": message_id,
        "thread_id": thread_id,
        "subject": subject,
        "date": date.today().isoformat(),
        "processed_reply_ids": [],
    })


def build_meeting_prep(today_events, meeting_configs, storage) -> list[str]:
    prep = []
    # Meetings live on the git store (origin/main), not R2 — read the local working tree.
    state = meetings_lib.replay_local()
    for event in today_events:
        config = find_meeting_for_event(event, meeting_configs)
        if not config:
            continue
        mtg = state.get(config.meeting_id, {"sessions": []})
        last_summary = meetings_lib.last_session(mtg)
        if last_summary:
            preview = last_summary[:200] + ("..." if len(last_summary) > 200 else "")
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — Last session: {preview}")
        else:
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — No prior session notes")
    return prep


def _scan_outbound_pipeline_contacts(config: dict, storage) -> int:
    """
    Scans the last 24h of sent mail for emails to pipeline leads.
    Updates the activity file, patches the local cache, and writes to Notion.
    Also reconciles any existing activity entries where Notion still has stale dates.
    Returns count of new contacts recorded.
    """
    lead_index = load_lead_email_index(storage)
    if not lead_index:
        return 0

    page_index = load_lead_page_index(storage)
    activity = load_pipeline_activity(storage)
    new_contacts = 0

    try:
        sent_threads = fetch_threads_needing_attention(
            user_email=config["email"],
            max_results=50,
            query="in:sent newer_than:24h",
        )
    except Exception as e:
        print(f"   WARNING: sent mail scan failed: {e}", flush=True)
        sent_threads = []

    for thread in sent_threads:
        recipient_email = _extract_email(thread.last_recipient)
        if recipient_email not in lead_index:
            continue
        lead_name = lead_index[recipient_email]
        updated = record_lead_contact(activity, recipient_email, lead_name, thread, direction="outbound")
        if updated:
            contact_date = thread.last_message_date.date().isoformat()
            print(f"   Outbound contact: {lead_name} — {thread.subject[:60]}")
            patch_pipeline_cache_last_contacted(storage, recipient_email, contact_date)
            page_id = page_index.get(recipient_email)
            if page_id:
                ok = update_notion_last_contacted(page_id, contact_date)
                print(f"   Notion updated for {lead_name}: {ok}")
            else:
                print(f"   WARNING: no page_id for {lead_name} — run pipeline sync")
            new_contacts += 1

    if new_contacts:
        save_pipeline_activity(storage, activity)

    # Reconcile any historical gaps: activity_date > cache.last_contacted
    backfilled = reconcile_activity_to_notion(storage)
    if backfilled:
        print(f"   Notion backfilled for {backfilled} lead(s) with stale dates")

    return new_contacts


# ---------------------------------------------------------------------------
# Stage 1: Collect
# ---------------------------------------------------------------------------

def collect_signals(config: dict, health: RunHealth, storage) -> CollectedData:
    """Pull raw signals from all sources. Returns CollectedData with safe defaults on failure."""
    data = CollectedData()
    stage = StageResult(name="collect")

    with timed() as stage_timer:

        # Calendar
        _err = None
        print("🗓  Fetching calendar...")
        with timed() as t:
            try:
                data.today_events, data.tomorrow_events, data.calendar_failed = fetch_two_day_events(
                    config["calendar_ids"], user_email=config["email"]
                )
                if data.calendar_failed:
                    _err = "API unavailable"
                    print("WARNING: Calendar API unavailable — schedule data missing from brief.", flush=True)
            except Exception as e:
                _err = str(e)[:200]
                data.calendar_failed = True
                print(f"⚠️ Calendar error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="calendar",
            status="error" if _err else "ok",
            error=_err,
            item_count=len(data.today_events) + len(data.tomorrow_events),
            duration_ms=t.elapsed_ms,
        ))

        # Gmail
        _err = None
        print("📧  Fetching Gmail (work)...")
        with timed() as t:
            try:
                data.email_threads = filter_automated_threads(
                    fetch_threads_needing_attention(
                        user_email=config["email"],
                        max_results=config.get("unread_email_max", 15),
                    ),
                    config.get("email_automation_filters", {}),
                )
            except Exception as e:
                _err = str(e)[:200]
                print(f"⚠️ Gmail error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="gmail",
            status="error" if _err else "ok",
            error=_err,
            item_count=len(data.email_threads),
            duration_ms=t.elapsed_ms,
        ))

        # Projects + recurring tasks
        _err = None
        print("📋  Loading projects and recurring tasks...")
        with timed() as t:
            try:
                data.projects = load_projects(config["projects_file"])
                data.due_tasks = load_due_recurring_tasks(config["recurring_file"])
            except Exception as e:
                _err = str(e)[:200]
                print(f"⚠️ Projects/tasks error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="projects",
            status="error" if _err else "ok",
            error=_err,
            item_count=len(data.projects),
            duration_ms=t.elapsed_ms,
        ))

        # Inbox
        _err = None
        print("📝  Reading inbox...")
        with timed() as t:
            try:
                data.inbox_text = read_inbox(config.get("inbox_file", ""))
            except Exception as e:
                _err = str(e)[:200]
                print(f"⚠️ Inbox error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="inbox",
            status="error" if _err else "ok",
            error=_err,
            duration_ms=t.elapsed_ms,
        ))

        # Notion inbox
        notion_token = os.environ.get("NOTION_TOKEN", "")
        if not config.get("notion", {}).get("enabled"):
            stage.collectors.append(CollectorResult(name="notion_inbox", status="skipped"))
        elif not notion_token:
            stage.collectors.append(CollectorResult(name="notion_inbox", status="skipped", error="NOTION_TOKEN not set"))
        else:
            _err = None
            print("🔔  Fetching Notion inbox...")
            with timed() as t:
                try:
                    data.notion_items = fetch_inbox_items(
                        token=notion_token,
                        database_id=config["notion"]["inbox_database_id"],
                        filter_statuses=config["notion"]["inbox_filter_status"],
                    )
                except Exception as e:
                    _err = str(e)[:200]
                    print(f"⚠️ Notion inbox error (non-fatal): {e}", file=sys.stderr)
            stage.collectors.append(CollectorResult(
                name="notion_inbox",
                status="error" if _err else "ok",
                error=_err,
                item_count=len(data.notion_items),
                duration_ms=t.elapsed_ms,
            ))

        # Issues
        _err = None
        print("🔥  Loading open issues...")
        with timed() as t:
            try:
                auto_resolve_issues(storage, resolve_after_days=config.get("issue_auto_resolve_days", 3))
                data.open_issues = get_open_issues(storage)
            except Exception as e:
                _err = str(e)[:200]
                print(f"⚠️ Issues error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="issues",
            status="error" if _err else "ok",
            error=_err,
            item_count=len(data.open_issues),
            duration_ms=t.elapsed_ms,
        ))

        # Pipeline
        if not config.get("pipeline", {}).get("enabled"):
            stage.collectors.append(CollectorResult(name="pipeline", status="skipped"))
        else:
            _err = None
            print("📈  Loading pipeline cache...")
            with timed() as t:
                try:
                    cache_path = config["pipeline"]["cache_path"]
                    activity_path = str(Path(cache_path).parent / "pipeline_email_activity.json")

                    print("📤  Scanning sent mail for outbound pipeline contacts...")
                    _scan_outbound_pipeline_contacts(config, storage)

                    data.trial_leads, data.attention_leads = fetch_pipeline_leads(
                        cache_path=cache_path,
                        trial_followup_after_days=config["pipeline"].get("trial_followup_after_days", 5),
                        stale_after_days=config["pipeline"].get("stale_after_days", 14),
                    )
                    try:
                        _cache = storage.read_json("pipeline_cache.json") or {}
                        synced_at = _cache.get("synced_at") or _cache.get("fetched_at", "")
                        if synced_at:
                            synced_date = date.fromisoformat(synced_at[:10])
                            data.pipeline_cache_age_days = (date.today() - synced_date).days
                        data.all_pipeline_leads = _cache.get("leads", [])
                        # Apply activity overrides so Pinecone gets accurate staleness data,
                        # not the (potentially stale) dates from the last Notion sync.
                        activity_overrides = load_activity_overrides(activity_path)
                        if activity_overrides:
                            today_d = date.today()
                            for lead in data.all_pipeline_leads:
                                email = lead.get("email", "").lower()
                                activity_date = activity_overrides.get(email)
                                cache_date = lead.get("last_contacted") or ""
                                if activity_date and activity_date > cache_date:
                                    lead["last_contacted"] = activity_date
                                    try:
                                        days = (today_d - date.fromisoformat(activity_date[:10])).days
                                    except (ValueError, TypeError):
                                        days = None
                                    lead["days_since_contact"] = days
                                    lead["stale"] = days is not None and days >= 14
                    except (FileNotFoundError, json.JSONDecodeError, ValueError):
                        pass
                    print(f"   {len(data.trial_leads)} trial follow-up(s), {len(data.attention_leads)} stale opp(s)")
                except Exception as e:
                    _err = str(e)[:200]
                    print(f"⚠️ Pipeline error (non-fatal): {e}", file=sys.stderr)
            stage.collectors.append(CollectorResult(
                name="pipeline",
                status="error" if _err else "ok",
                error=_err,
                item_count=len(data.all_pipeline_leads),
                duration_ms=t.elapsed_ms,
            ))

        # Gym scout
        if not config.get("gym_scout", {}).get("enabled"):
            stage.collectors.append(CollectorResult(name="gym_scout", status="skipped"))
        else:
            _err = None
            with timed() as t:
                try:
                    data.gym_scout_leads = fetch_recent_leads(
                        config["gym_scout"]["results_csv"],
                        lookback_days=config["gym_scout"].get("lookback_days", 7),
                    )
                    if data.gym_scout_leads:
                        print(f"🏋️  Gym Scout: {len(data.gym_scout_leads)} new lead(s) this week")
                except Exception as e:
                    _err = str(e)[:200]
                    print(f"⚠️ Gym Scout error (non-fatal): {e}", file=sys.stderr)
            stage.collectors.append(CollectorResult(
                name="gym_scout",
                status="error" if _err else "ok",
                error=_err,
                item_count=len(data.gym_scout_leads),
                duration_ms=t.elapsed_ms,
            ))

        # Bugs
        if not notion_token:
            stage.collectors.append(CollectorResult(name="bugs", status="skipped", error="NOTION_TOKEN not set"))
        else:
            _err = None
            print("🪲  Fetching bug tracker...")
            with timed() as t:
                try:
                    from collectors.notion_bugs import fetch_bugs
                    data.bugs = fetch_bugs(notion_token)
                    if data.bugs:
                        open_bugs = [b for b in data.bugs if b.status != "Done"]
                        print(f"   {len(open_bugs)} open bug(s) ({len(data.bugs)} total)")
                except Exception as e:
                    _err = str(e)[:200]
                    print(f"⚠️  Bug tracker fetch error (non-fatal): {e}", file=sys.stderr)
            stage.collectors.append(CollectorResult(
                name="bugs",
                status="error" if _err else "ok",
                error=_err,
                item_count=len(data.bugs),
                duration_ms=t.elapsed_ms,
            ))

        # Metrics engine: drive the sync, then pull the canonical snapshot.
        _metrics_err = None
        _metrics_skipped = False
        with timed() as t:
            try:
                from lib import metrics_client
                base_url = os.environ.get("METRICS_BASE_URL", "")
                password = os.environ.get("METRICS_PASSWORD", "")
                if base_url:
                    _sync_report = metrics_client.trigger_sync(base_url, password)
                    _failed = metrics_client.sync_failures(_sync_report)
                    if _failed and os.environ.get("GITHUB_ACTIONS"):
                        try:
                            from lib.telegram import send_message
                            send_message(
                                os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                                os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", ""),
                                f"⚠️ Metric sync failed: {', '.join(_failed)}",
                            )
                        except Exception as _te:
                            print(f"⚠️  Telegram sync-failure alert failed (non-fatal): {_te}", file=sys.stderr)
                    data.metrics_snapshot = metrics_client.fetch_snapshot(base_url, password, storage)
                    if data.metrics_snapshot:
                        sales_cnt = data.metrics_snapshot.get('sales_data', {}).get('count', '?')
                        demos_cnt = data.metrics_snapshot.get('demos_data', {}).get('count', '?')
                        stale = data.metrics_snapshot.get('stale')
                        print(f"   Metrics snapshot: sales={sales_cnt} "
                              f"demos={demos_cnt} "
                              f"(stale={stale})")
                else:
                    _metrics_skipped = True
            except Exception as e:
                _metrics_err = str(e)[:200]
                print(f"⚠️  Metrics snapshot error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="metrics_snapshot",
            status="skipped" if _metrics_skipped else ("error" if _metrics_err else "ok"),
            error=_metrics_err,
            duration_ms=t.elapsed_ms,
        ))

        # The snapshot is now the single source for these three consumers
        # (GTM metrics, What-Moved diff, memory/vector pipeline).
        if data.metrics_snapshot:
            data.sales_data = data.metrics_snapshot.get("sales_data")
            data.demos_data = data.metrics_snapshot.get("demos_data")
            data.cancellations = data.metrics_snapshot.get("cancellations") or {"count": 0, "entries": []}

        # Slack DMs
        slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
        if not slack_token:
            stage.collectors.append(CollectorResult(name="slack_dms", status="skipped", error="SLACK_BOT_TOKEN not set"))
        else:
            _err = None
            with timed() as t:
                try:
                    from collectors.slack import fetch_dm_messages
                    data.slack_dms = fetch_dm_messages(token=slack_token, since_hours=24)
                except Exception as e:
                    _err = str(e)[:200]
                    print(f"⚠️ Slack error (non-fatal): {e}", file=sys.stderr)
            stage.collectors.append(CollectorResult(
                name="slack_dms",
                status="error" if _err else "ok",
                error=_err,
                item_count=len(data.slack_dms),
                duration_ms=t.elapsed_ms,
            ))

        # Avoma meeting transcripts
        avoma_key = os.environ.get("AVOMA_API_KEY", "")
        avoma_cfg = config.get("avoma", {})
        if not avoma_cfg.get("enabled") or not avoma_key:
            stage.collectors.append(CollectorResult(
                name="avoma",
                status="skipped",
                error=None if avoma_cfg.get("enabled") else "avoma.enabled=false",
            ))
        else:
            _err = None
            print("🎙️  Fetching Avoma meeting transcripts...")
            with timed() as t:
                try:
                    from collectors.avoma import fetch_recent_meetings
                    data.avoma_transcripts = fetch_recent_meetings(
                        api_key=avoma_key,
                        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                        model=config.get("ai_model", "claude-sonnet-4-6"),
                        lookback_hours=avoma_cfg.get("lookback_hours", 96),
                        sales_rep_emails=avoma_cfg.get("sales_rep_emails", []),
                        filter_internal=avoma_cfg.get("filter_internal", True),
                    )
                    if data.avoma_transcripts:
                        print(f"   {len(data.avoma_transcripts)} OS-interested meeting(s) analyzed")
                except Exception as e:
                    _err = str(e)[:200]
                    print(f"⚠️ Avoma error (non-fatal): {e}", file=sys.stderr)
            stage.collectors.append(CollectorResult(
                name="avoma",
                status="error" if _err else "ok",
                error=_err,
                item_count=len(data.avoma_transcripts),
                duration_ms=t.elapsed_ms,
            ))

    stage.duration_ms = stage_timer.elapsed_ms
    if any(c.status == "error" for c in stage.collectors):
        stage.status = "degraded"
    health.stages.append(stage)

    return data


# ---------------------------------------------------------------------------
# Stage 2: Process
# ---------------------------------------------------------------------------

def process_context(config: dict, collected: CollectedData, health: RunHealth, storage) -> ProcessedContext:
    """Enrich, classify, and prepare context for brief generation."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    ctx = ProcessedContext(collected=collected)
    stage = StageResult(name="process")

    with timed() as stage_timer:

        # Meeting prep (fast, file-based — not tracked as a sub-step)
        print("🗒  Building meeting prep...")
        meeting_configs = load_meeting_index(config.get("meeting_index_file", "data/meeting_index.json"))
        ctx.meeting_prep = build_meeting_prep(collected.today_events, meeting_configs, storage)

        # People enrichment
        _err = None
        print("🧠  Enriching people store...")
        with timed() as t:
            try:
                people_dir = config.get("people_dir", "data/people")
                if os.path.isdir(people_dir):
                    ctx.people_context = enrich_people(
                        calendar_events=collected.today_events,
                        email_threads=collected.email_threads,
                        slack_dms=collected.slack_dms,
                        people_dir=people_dir,
                        api_key=api_key,
                        model=config["ai_model"],
                    )
            except Exception as e:
                _err = str(e)[:200]
                print(f"⚠️ People enrichment error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="people_enrichment",
            status="error" if _err else "ok",
            error=_err,
            duration_ms=t.elapsed_ms,
        ))

        # Memory retrieval
        memory_cfg = config.get("memory", {})
        if not memory_cfg.get("enabled"):
            stage.collectors.append(CollectorResult(name="memory_retrieval", status="skipped"))
        else:
            _err = None
            with timed() as t:
                try:
                    _vector_cfg = config.get("vector", {})
                    _pinecone_key = os.environ.get("PINECONE_API_KEY", "")
                    _voyage_key = os.environ.get("VOYAGE_API_KEY", "")
                    _pinecone_cfg = None
                    if _vector_cfg.get("enabled") and _pinecone_key and _voyage_key:
                        _pinecone_cfg = {
                            "api_key": _pinecone_key,
                            "voyage_api_key": _voyage_key,
                            "index_name": _vector_cfg["index_name"],
                            "embedding_model": _vector_cfg["embedding_model"],
                            "observations_namespace": _vector_cfg.get("observations_namespace", "observations"),
                            "memories_namespace": _vector_cfg.get("memories_namespace", "memories"),
                            "retrieval_mode": _vector_cfg.get("retrieval_mode", "auto"),
                        }
                    ctx.memory_context = retrieve_memories(
                        storage=storage,
                        token_budget=memory_cfg.get("retrieval_token_budget", 1500),
                        pinecone_config=_pinecone_cfg,
                        query_signals={
                            "calendar_events": [e.summary for e in collected.today_events + collected.tomorrow_events],
                            "email_subjects": [t.subject for t in collected.email_threads[:10]],
                            "pipeline_lead_names": [l.name for l in collected.trial_leads + collected.attention_leads],
                            "issue_titles": [i.title for i in collected.open_issues],
                        },
                        trigger="brief",
                        run_date=date.today().isoformat(),
                    )
                    ctx.memory_cold_start_msg = get_cold_start_message(
                        storage=storage,
                        cold_start_days=memory_cfg.get("cold_start_days", 3),
                    )
                    if ctx.memory_cold_start_msg:
                        print(f"   ℹ️  {ctx.memory_cold_start_msg}")
                except Exception as e:
                    _err = str(e)[:200]
                    print(f"⚠️ Memory retrieval error (non-fatal): {e}", file=sys.stderr)
            stage.collectors.append(CollectorResult(
                name="memory_retrieval",
                status="error" if _err else "ok",
                error=_err,
                duration_ms=t.elapsed_ms,
            ))

        # Loop resolution
        print("🔄  Resolving open loops...")
        yesterday = date.today() - timedelta(days=1)
        ctx.previous_state = load_snapshot(yesterday, storage)
        ctx.today_email_ids = [t.id for t in collected.email_threads]
        ctx.today_notion_ids = [n.id for n in collected.notion_items]

        if ctx.previous_state:
            resolved, ctx.still_open = diff_snapshots(ctx.previous_state, ctx.today_email_ids, ctx.today_notion_ids)
        else:
            resolved = {"email": [], "notion": []}
            ctx.still_open = {"email": [], "notion": []}

        ctx.loop_summary = build_loop_summary(collected.email_threads, collected.notion_items, resolved, ctx.still_open)

        # Captures + brief feedback
        ctx.captures_context = load_recent_captures(storage)
        try:
            from lib.notes import load_notes_for_brief
            ctx.notes_context = load_notes_for_brief(storage)
        except Exception as e:
            print(f"⚠️  Notes context error (non-fatal): {e}", file=sys.stderr)
        ctx.brief_feedback_context = load_brief_feedback(storage)
        ctx.brief_prefs_context = load_brief_prefs(config)

    stage.duration_ms = stage_timer.elapsed_ms
    if any(c.status == "error" for c in stage.collectors):
        stage.status = "degraded"
    health.stages.append(stage)

    return ctx


# ---------------------------------------------------------------------------
# Stage 3: Generate & Deliver
# ---------------------------------------------------------------------------

def _format_metric_flags(metric_results: list, dashboard_path: str) -> list[str]:
    """Format MetricResult objects into brief-ready flag strings."""
    breached = [r for r in metric_results if r.breach]
    stale = [r for r in metric_results if r.stale and not r.breach]
    if not breached and not stale:
        return [f"All GTM metrics in range — dashboard: {dashboard_path}"]
    flags = []
    horizon_label = {"next-month": "next month tracking", "this-month": "this month"}
    for r in breached:
        label = horizon_label.get(r.horizon, r.horizon)
        flags.append(f"{r.label}: {r.breach_reason} ({label})")
    for r in stale:
        flags.append(f"{r.label}: {r.stale_reason}")
    return flags


def _format_engine_flags(snapshot: dict) -> list[str]:
    """Staleness banner + per-source sync-failure flags from the engine snapshot."""
    flags = []
    if snapshot.get("stale"):
        flags.append(f"⚠️ Metrics: {snapshot.get('stale_reason', 'using last-good snapshot')}")
    for src, info in (snapshot.get("freshness") or {}).items():
        if not info.get("ok"):
            flags.append(f"⚠️ {src} metrics never synced — check OS-Metric-Sync")
    return flags


def generate_and_deliver(
    config: dict,
    ctx: ProcessedContext,
    dry_run: bool = False,
    no_email: bool = False,
    health: RunHealth = None,
    storage = None,
) -> None:
    """Call Claude, build the brief, send email, write dashboard, persist state, run memory pipeline."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    collected = ctx.collected
    memory_cfg = config.get("memory", {})
    stage = StageResult(name="generate_and_deliver")

    with timed() as stage_timer:

        # GTM metrics evaluation
        _metric_results = []
        _metric_flags = []
        try:
            from lib.metrics_client import metrics_from_snapshot
            from collectors.onboarding import load_onboarding_active
            onboarding_cfg = config.get("onboarding", {})
            active_statuses = onboarding_cfg.get("active_statuses", ["In Progress", "Awaiting Customer", "Ready to Go Live"])
            onboarding_cache_path = onboarding_cfg.get("cache_path", "data/onboarding_cache.json")
            onboarding_active = load_onboarding_active(onboarding_cache_path, active_statuses)
            snapshot = collected.metrics_snapshot
            if snapshot:
                _metric_results = metrics_from_snapshot(snapshot, onboarding_active)
                _metric_flags = _format_engine_flags(snapshot) + _format_metric_flags(
                    _metric_results, config.get("dashboard_path", "output/dashboard.html")
                )
        except Exception as e:
            print(f"⚠️  Metric evaluation error (non-fatal): {e}", file=sys.stderr)

        # What Moved context (snapshot diff)
        _onboarding_all = []
        _pipeline_all = []
        _what_moved_context = ""
        try:
            import json as _json
            from processors.what_moved import build_what_moved_context
            onboarding_cache_path = config.get("onboarding", {}).get("cache_path", "data/onboarding_cache.json")
            try:
                with open(onboarding_cache_path) as _f:
                    _onboarding_all = _json.load(_f).get("records", [])
            except (FileNotFoundError, _json.JSONDecodeError):
                _onboarding_all = []
            _onboarding_prev = storage.read_json("state/onboarding_prev.json") or []
            try:
                with open("data/pipeline_cache.json") as _f:
                    _pipeline_all = _json.load(_f).get("leads", [])
            except (FileNotFoundError, _json.JSONDecodeError):
                _pipeline_all = []
            _pipeline_prev = storage.read_json("state/pipeline_prev.json") or []
            _what_moved_context = build_what_moved_context(
                cancellations=collected.cancellations,
                avoma_transcripts=collected.avoma_transcripts,
                onboarding_current=_onboarding_all,
                onboarding_prev=_onboarding_prev,
                pipeline_current=_pipeline_all,
                pipeline_prev=_pipeline_prev,
            )
            # Snapshot writes on success path — co-located with the data they depend on
            if _onboarding_all:
                storage.write_json("state/onboarding_prev.json", _onboarding_all)
            if _pipeline_all:
                storage.write_json("state/pipeline_prev.json", _pipeline_all)
        except Exception as e:
            print(f"⚠️  What Moved context error (non-fatal): {e}", file=sys.stderr)

        # Brief generation
        _brief_error = None
        print("🤖  Generating brief with Claude...")
        with timed() as t:
            try:
                brief = generate_brief(
                    api_key=api_key,
                    model=config["ai_model"],
                    today_events=collected.today_events,
                    tomorrow_events=collected.tomorrow_events,
                    projects=collected.projects,
                    due_tasks=collected.due_tasks,
                    loop_summary=ctx.loop_summary,
                    open_issues=collected.open_issues,
                    meeting_prep=ctx.meeting_prep,
                    inbox_text=collected.inbox_text,
                    attention_leads=collected.attention_leads,
                    gym_scout_leads=collected.gym_scout_leads,
                    people_context=ctx.people_context,
                    memory_context=ctx.memory_context,
                    captures_context=ctx.captures_context,
                    notes_context=ctx.notes_context,
                    brief_feedback_context=ctx.brief_feedback_context,
                    brief_prefs_context=ctx.brief_prefs_context,
                    storage=storage,
                    metric_flags=_metric_flags,
                    what_moved_context=_what_moved_context,
                )
            except Exception as e:
                _brief_error = str(e)[:200]
                print(f"ERROR: Failed to generate brief: {e}", file=sys.stderr)
                brief = BriefContent(
                    act_today=[
                        "Brief generation failed — check logs.",
                        "Retry: python main.py --no-email",
                    ],
                    metric_flags=[f"Brief error: {str(e)[:150]}"],
                )
        stage.collectors.append(CollectorResult(
            name="brief_generation",
            status="error" if _brief_error else "ok",
            error=_brief_error,
            duration_ms=t.elapsed_ms,
        ))
        if _brief_error:
            stage.status = "failed"

        # Inject watch-outs and mirror them to health warnings
        if ctx.memory_cold_start_msg:
            brief.act_today.insert(0, ctx.memory_cold_start_msg)
            if health is not None:
                health.add_warning(ctx.memory_cold_start_msg)

        if collected.calendar_failed:
            _cal_warn = "⚠️ Calendar API unavailable — schedule data is missing. Enable Google Calendar API at console.cloud.google.com for project 859502323558."
            brief.act_today.insert(0, _cal_warn)
            if health is not None:
                health.add_warning(_cal_warn)

        pipeline_stale_days = config.get("pipeline", {}).get("cache_stale_warn_days", 7)
        if collected.pipeline_cache_age_days is not None and collected.pipeline_cache_age_days >= pipeline_stale_days:
            _stale_warn = f"Pipeline cache is {collected.pipeline_cache_age_days} days old — open Claude Code and ask to re-sync the pipeline cache from Notion."
            brief.act_today.append(_stale_warn)
            if health is not None:
                health.add_warning(_stale_warn)

        # Dashboard
        print("📊  Writing dashboard...")
        write_dashboard(
            brief=brief,
            today_events=collected.today_events,
            projects=collected.projects,
            due_tasks=collected.due_tasks,
            loop_summary=ctx.loop_summary,
            output_path=config["dashboard_path"],
            metric_results=_metric_results,
        )

        # Email send
        _email_error = None
        _email_status = "ok"
        _already_sent_today = False
        with timed() as t:
            if dry_run or no_email:
                _email_status = "skipped"
                print("   (email skipped)")
            else:
                if _brief_already_sent_today(storage):
                    _prev = storage.read_json("state/brief_message_id.json")
                    print(f"   Brief already sent today ({_prev.get('message_id')}) — skipping.")
                    _already_sent_today = True
                    _email_status = "skipped"
                if not _already_sent_today:
                    try:
                        print("📤  Sending brief email...")
                        gmail = build_gmail_service(config["email"])
                        subject = f"☀️ Morning Brief — {datetime.now().strftime('%A, %B %-d')}"
                        html = build_html_email(brief, collected.today_events, collected.projects, collected.due_tasks, ctx.loop_summary)
                        msg_id, thread_id = send_brief_email(gmail, config["email"], subject, html)
                        if not msg_id:
                            print("WARNING: send_brief_email returned empty message_id — state not saved.", file=sys.stderr)
                        else:
                            print(f"   Sent: {msg_id}")
                            _save_brief_message_id(storage, msg_id, thread_id, subject)
                    except Exception as e:
                        _email_error = str(e)[:200]
                        print(f"⚠️ Email send error (non-fatal): {e}", file=sys.stderr)
        stage.collectors.append(CollectorResult(
            name="email_send",
            status=_email_status if not _email_error else "error",
            error=_email_error,
            duration_ms=t.elapsed_ms,
        ))

        # Skip state snapshot + memory pipeline when already sent today
        if _already_sent_today:
            stage.duration_ms = stage_timer.elapsed_ms
            if any(c.status == "error" for c in stage.collectors) and stage.status != "failed":
                stage.status = "degraded"
            if health is not None:
                health.stages.append(stage)
            return

        # State snapshot
        print("💾  Saving state snapshot...")
        snapshot = StateSnapshot(
            date=date.today().isoformat(),
            open_email_thread_ids=ctx.today_email_ids,
            open_notion_item_ids=ctx.today_notion_ids,
        )
        save_snapshot(snapshot, storage)

        # Memory pipeline (observe + synthesize + vector ingest)
        if not memory_cfg.get("enabled"):
            stage.collectors.append(CollectorResult(name="memory_pipeline", status="skipped"))
        else:
            _err = None
            with timed() as t:
                try:
                    observe(
                        storage=storage,
                        decisions_file=memory_cfg.get("decisions_file", "data/memory/decisions.md"),
                        email_threads=collected.email_threads,
                        still_open_ids=ctx.still_open if ctx.previous_state else {"email": [], "notion": []},
                        pipeline_leads=list(collected.trial_leads) + list(collected.attention_leads),
                        brief=brief,
                        issues=collected.open_issues,
                        sales_data=collected.sales_data,
                        demos_data=collected.demos_data,
                        bugs=collected.bugs if collected.bugs else None,
                        cancellations=collected.cancellations if collected.cancellations.get("count", 0) > 0 else None,
                        avoma_transcripts=collected.avoma_transcripts or None,
                    )
                    print("🧠  Observations captured.")
                    print("🔄  Running memory synthesis...")
                    synthesize(
                        storage=storage,
                        api_key=api_key,
                        model=config["ai_model"],
                        lookback_days=memory_cfg.get("observation_lookback_days", 30),
                        default_ttl_days=memory_cfg.get("default_ttl_days", 90),
                        activity_extension_days=memory_cfg.get("activity_extension_days", 30),
                        abandon_threshold_days=memory_cfg.get("abandon_threshold_days", 60),
                        abandon_ttl_days=memory_cfg.get("abandon_ttl_days", 14),
                    )
                    print("✅  Memory synthesis complete.")
                    # Vector ingest — embed new observations and updated memories into Pinecone
                    vector_cfg = config.get("vector", {})
                    pinecone_key = os.environ.get("PINECONE_API_KEY", "")
                    voyage_key = os.environ.get("VOYAGE_API_KEY", "")
                    if vector_cfg.get("enabled") and pinecone_key and voyage_key:
                        try:
                            from processors.vector_ingest import ingest as vector_ingest
                            print("📡  Ingesting vectors into Pinecone...")
                            vector_ingest(
                                storage=storage,
                                pinecone_api_key=pinecone_key,
                                voyage_api_key=voyage_key,
                                index_name=vector_cfg["index_name"],
                                embedding_model=vector_cfg["embedding_model"],
                                obs_namespace=vector_cfg.get("observations_namespace", "observations"),
                                mem_namespace=vector_cfg.get("memories_namespace", "memories"),
                                raw_namespace=vector_cfg.get("raw_data_namespace", "raw_data"),
                                pipeline_leads=collected.all_pipeline_leads,
                                bugs=[dataclasses.asdict(b) for b in collected.bugs] if collected.bugs else [],
                                cancellations=collected.cancellations,
                                sales_entries=collected.sales_data.get("entries", []) if collected.sales_data else [],
                                sidecar_file="data/people_resolution.json",
                            )
                            print("✅  Vector ingest complete.")
                        except Exception as e:
                            print(f"⚠️  Vector ingest error (non-fatal): {e}", file=sys.stderr)
                            raise  # re-raise so the outer except catches it and marks memory_pipeline as error
                except Exception as e:
                    _err = str(e)[:200]
                    print(f"⚠️  Memory pipeline error (non-fatal): {e}", file=sys.stderr)
                    _ops_cfg = config.get("ops_alerts", {})
                    if _ops_cfg.get("enabled"):
                        from lib.alerts import send_ops_alert
                        send_ops_alert(
                            f"⚠️ Memory pipeline failed (cross-day memory not updated): {_err}",
                            _ops_cfg.get("slack_user_id", ""),
                        )
            stage.collectors.append(CollectorResult(
                name="memory_pipeline",
                status="error" if _err else "ok",
                error=_err,
                duration_ms=t.elapsed_ms,
            ))

    stage.duration_ms = stage_timer.elapsed_ms
    if any(c.status == "error" for c in stage.collectors) and stage.status != "failed":
        stage.status = "degraded"
    if health is not None:
        health.stages.append(stage)

    print("\n✅ Brief complete.")
    if brief.metric_flags:
        print("\nMetric Flags:")
        for f in brief.metric_flags:
            print(f"  {f}")
    if brief.act_today:
        print("\nAct Today:")
        for i, p in enumerate(brief.act_today, 1):
            print(f"  {i}. {p}")
    if brief.what_moved:
        print("\nWhat Moved:")
        for w in brief.what_moved:
            print(f"  - {w}")
    if collected.open_issues:
        print(f"\nOpen Issues: {len(collected.open_issues)}")
