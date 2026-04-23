#!/usr/bin/env python3
"""AI Chief of Staff — Morning Brief Orchestrator."""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from collectors.calendar import fetch_two_day_events
from collectors.gmail import fetch_threads_needing_attention
from collectors.local_data import load_projects, load_due_recurring_tasks, read_inbox
from collectors.notion_inbox import fetch_inbox_items
from collectors.pipeline import fetch_pipeline_leads, PipelineLead
from collectors.gym_scout import fetch_recent_leads, GymScoutLead
from processors.state import StateSnapshot, save_snapshot, load_snapshot, diff_snapshots
from processors.loops import build_loop_summary
from processors.issues import get_open_issues, auto_resolve_issues
from processors.meeting_memory import load_meeting_index, find_meeting_for_event, load_last_session_summary
from processors.drafts import generate_demo_followup, generate_trial_followup, save_draft, load_todays_drafts
from processors.brief import generate_brief, BriefContent
from processors.people import enrich_people
from outputs.sender import build_html_email, send_brief_email
from lib.google_auth import build_gmail_service
from outputs.dashboard import write_dashboard
from processors.memory_observer import observe
from processors.memory_synthesizer import synthesize
from processors.memory_retriever import retrieve_memories, get_cold_start_message
from lib.captures import load_recent_captures, load_brief_feedback


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _save_brief_message_id(config: dict, message_id: str, thread_id: str, subject: str) -> None:
    state_path = os.path.join(config["state_dir"], "brief_message_id.json")
    os.makedirs(config["state_dir"], exist_ok=True)
    # Overwrites on same-day re-run; replies to earlier send will be missed.
    with open(state_path, "w") as f:
        json.dump({
            "message_id": message_id,
            "thread_id": thread_id,
            "subject": subject,
            "date": date.today().isoformat(),
            "processed_reply_ids": [],
        }, f)


def build_meeting_prep(today_events, meeting_configs) -> list[str]:
    prep = []
    for event in today_events:
        config = find_meeting_for_event(event, meeting_configs)
        if not config:
            continue
        last_summary = load_last_session_summary(config.memory_file)
        if last_summary:
            preview = last_summary[:200] + ("..." if len(last_summary) > 200 else "")
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — Last session: {preview}")
        else:
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — No prior session notes")
    return prep


def generate_pipeline_drafts(config: dict, trial_leads: list[PipelineLead]) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = config["ai_model"]
    drafts_dir = config["drafts_dir"]
    for lead in trial_leads:
        if not lead.email:
            continue
        days = lead.days_since_contact or 0
        name = lead.contact or lead.name
        draft = generate_trial_followup(api_key, model, name, lead.email, days)
        if draft:
            save_draft(draft, drafts_dir)
            print(f"   Draft: trial follow-up for {lead.name} ({days}d since last contact)")


def generate_daily_drafts(config: dict, today_events) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = config["ai_model"]
    drafts_dir = config["drafts_dir"]
    for event in today_events:
        if "demo" in event.summary.lower() and event.attendees:
            draft = generate_demo_followup(api_key, model, event)
            if draft:
                save_draft(draft, drafts_dir)
                print(f"   Draft: demo follow-up for {event.summary}")


def run(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    from lib.llm_logger import flush
    try:
        _run_inner(config, dry_run=dry_run, no_email=no_email)
    finally:
        flush("daily_brief", config.get("logs_file", "data/logs/run_log.jsonl"))


def _run_inner(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    print("🗓  Fetching calendar...")
    today_events, tomorrow_events = fetch_two_day_events(
        config["calendar_ids"], user_email=config["email"]
    )

    print("📧  Fetching Gmail (work)...")
    email_threads = fetch_threads_needing_attention(
        user_email=config["email"],
        max_results=config.get("unread_email_max", 15),
    )

    print("📋  Loading projects and recurring tasks...")
    projects = load_projects(config["projects_file"])
    due_tasks = load_due_recurring_tasks(config["recurring_file"])

    print("📝  Reading inbox...")
    inbox_text = read_inbox(config.get("inbox_file", ""))

    notion_items = []
    if config.get("notion", {}).get("enabled"):
        print("🔔  Fetching Notion inbox...")
        notion_token = os.environ.get("NOTION_TOKEN", "")
        if notion_token:
            notion_items = fetch_inbox_items(
                token=notion_token,
                database_id=config["notion"]["inbox_database_id"],
                filter_statuses=config["notion"]["inbox_filter_status"],
            )

    print("🔥  Loading open issues...")
    auto_resolve_issues(config["issues_file"], resolve_after_days=config.get("issue_auto_resolve_days", 3))
    open_issues = get_open_issues(config["issues_file"])

    print("🗒  Building meeting prep...")
    meeting_configs = load_meeting_index(config.get("meeting_index_file", "data/meeting_index.json"))
    meeting_prep = build_meeting_prep(today_events, meeting_configs)

    print("✍️  Generating demo follow-up drafts...")
    generate_daily_drafts(config, today_events)

    trial_leads: list[PipelineLead] = []
    attention_leads: list[PipelineLead] = []
    pipeline_cache_age_days: int | None = None
    if config.get("pipeline", {}).get("enabled"):
        print("📈  Loading pipeline cache...")
        cache_path = config["pipeline"]["cache_path"]
        trial_leads, attention_leads = fetch_pipeline_leads(
            cache_path=cache_path,
            trial_followup_after_days=config["pipeline"].get("trial_followup_after_days", 5),
            stale_after_days=config["pipeline"].get("stale_after_days", 14),
        )
        try:
            with open(cache_path) as f:
                synced_at = json.load(f).get("synced_at", "")
            if synced_at:
                synced_date = date.fromisoformat(synced_at[:10])
                pipeline_cache_age_days = (date.today() - synced_date).days
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass
        print(f"   {len(trial_leads)} trial follow-up(s), {len(attention_leads)} stale opp(s)")
        if trial_leads:
            print("✍️  Generating trial follow-up drafts...")
            generate_pipeline_drafts(config, trial_leads)

    gym_scout_leads: list[GymScoutLead] = []
    if config.get("gym_scout", {}).get("enabled"):
        gym_scout_leads = fetch_recent_leads(
            config["gym_scout"]["results_csv"],
            lookback_days=config["gym_scout"].get("lookback_days", 7),
        )
        if gym_scout_leads:
            print(f"🏋️  Gym Scout: {len(gym_scout_leads)} new lead(s) this week")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    print("🧠  Enriching people store...")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    slack_dms = []
    if slack_token:
        from collectors.slack import fetch_dm_messages
        slack_dms = fetch_dm_messages(token=slack_token, since_hours=24)

    people_context = ""
    people_dir = config.get("people_dir", "data/people")
    if os.path.isdir(people_dir):
        people_context = enrich_people(
            calendar_events=today_events,
            email_threads=email_threads,
            slack_dms=slack_dms,
            people_dir=people_dir,
            api_key=api_key,
            model=config["ai_model"],
        )

    memory_context = ""
    memory_cold_start_msg = None
    memory_cfg = config.get("memory", {})
    if memory_cfg.get("enabled"):
        memory_context = retrieve_memories(
            memory_dir=memory_cfg["dir"],
            token_budget=memory_cfg.get("retrieval_token_budget", 1500),
        )
        memory_cold_start_msg = get_cold_start_message(
            obs_file=memory_cfg["observations_file"],
            cold_start_days=memory_cfg.get("cold_start_days", 3),
        )
        if memory_cold_start_msg:
            print(f"   ℹ️  {memory_cold_start_msg}")

    todays_drafts = load_todays_drafts(config["drafts_dir"])

    print("🔄  Resolving open loops...")
    yesterday = date.today() - timedelta(days=1)
    previous_state = load_snapshot(yesterday, config["state_dir"])
    today_email_ids = [t.id for t in email_threads]
    today_notion_ids = [n.id for n in notion_items]

    if previous_state:
        resolved, still_open = diff_snapshots(previous_state, today_email_ids, today_notion_ids)
    else:
        resolved = {"email": [], "notion": []}
        still_open = {"email": [], "notion": []}

    loop_summary = build_loop_summary(email_threads, notion_items, resolved, still_open)

    captures_context = load_recent_captures(config.get("captures_file", "data/captures.md"))
    brief_feedback_context = load_brief_feedback(config.get("brief_feedback_file", "data/brief_feedback.md"))

    print("🤖  Generating brief with Claude...")
    try:
        brief = generate_brief(
            api_key=api_key,
            model=config["ai_model"],
            today_events=today_events,
            tomorrow_events=tomorrow_events,
            email_threads=email_threads,
            projects=projects,
            due_tasks=due_tasks,
            loop_summary=loop_summary,
            open_issues=open_issues,
            drafts=todays_drafts,
            meeting_prep=meeting_prep,
            inbox_text=inbox_text,
            attention_leads=attention_leads,
            gym_scout_leads=gym_scout_leads,
            people_context=people_context,
            memory_context=memory_context,
            captures_context=captures_context,
            brief_feedback_context=brief_feedback_context,
        )
    except Exception as e:
        print(f"ERROR: Failed to generate brief: {e}", file=sys.stderr)
        brief = BriefContent(
            executive_summary="Brief generation failed — check logs.",
            top_3_priorities=["Check logs", "Retry: python main.py --no-email"],
            watch_outs=[str(e)[:200]],
        )

    if memory_cold_start_msg:
        brief.watch_outs = [memory_cold_start_msg] + (brief.watch_outs or [])

    pipeline_stale_days = config.get("pipeline", {}).get("cache_stale_warn_days", 7)
    if pipeline_cache_age_days is not None and pipeline_cache_age_days >= pipeline_stale_days:
        brief.watch_outs.append(
            f"Pipeline cache is {pipeline_cache_age_days} days old — open Claude Code and ask to re-sync the pipeline cache from Notion."
        )

    print("📊  Writing dashboard...")
    write_dashboard(
        brief=brief,
        today_events=today_events,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        output_path=config["dashboard_path"],
    )

    if not dry_run and not no_email:
        state_path = os.path.join(config["state_dir"], "brief_message_id.json")
        if os.path.exists(state_path):
            with open(state_path) as f:
                _prev = json.load(f)
            if _prev.get("date") == date.today().isoformat():
                print(f"   Brief already sent today ({_prev.get('message_id')}) — skipping.")
                return
        print("📤  Sending brief email...")
        gmail = build_gmail_service(config["email"])
        subject = f"☀️ Morning Brief — {datetime.now().strftime('%A, %B %-d')}"
        html = build_html_email(brief, today_events, projects, due_tasks, loop_summary)
        msg_id, thread_id = send_brief_email(gmail, config["email"], subject, html)
        if not msg_id:
            print("WARNING: send_brief_email returned empty message_id — state not saved.", file=sys.stderr)
        else:
            print(f"   Sent: {msg_id}")
            _save_brief_message_id(config, msg_id, thread_id, subject)
    else:
        print("   (email skipped)")

    print("💾  Saving state snapshot...")
    snapshot = StateSnapshot(
        date=date.today().isoformat(),
        open_email_thread_ids=today_email_ids,
        open_notion_item_ids=today_notion_ids,
    )
    save_snapshot(snapshot, config["state_dir"])

    if memory_cfg.get("enabled"):
        try:
            observe(
                obs_file=memory_cfg["observations_file"],
                decisions_file=memory_cfg["decisions_file"],
                email_threads=email_threads,
                still_open_ids=still_open if previous_state else {"email": [], "notion": []},
                pipeline_leads=list(trial_leads) + list(attention_leads),
                brief=brief,
                issues=open_issues,
            )
            print("🧠  Observations captured.")
            print("🔄  Running memory synthesis...")
            synthesize(
                obs_file=memory_cfg["observations_file"],
                memory_dir=memory_cfg["dir"],
                archive_dir=memory_cfg["archive_dir"],
                api_key=api_key,
                model=config["ai_model"],
                lookback_days=memory_cfg.get("observation_lookback_days", 30),
                default_ttl_days=memory_cfg.get("default_ttl_days", 90),
                activity_extension_days=memory_cfg.get("activity_extension_days", 30),
                abandon_threshold_days=memory_cfg.get("abandon_threshold_days", 60),
                abandon_ttl_days=memory_cfg.get("abandon_ttl_days", 14),
            )
            print("✅  Memory synthesis complete.")
        except Exception as e:
            print(f"⚠️  Memory pipeline error (non-fatal): {e}", file=sys.stderr)

    print("\n✅ Brief complete.")
    print(f"\nSummary: {brief.executive_summary}")
    print("\nTop Priorities:")
    for i, p in enumerate(brief.top_3_priorities, 1):
        print(f"  {i}. {p}")
    if brief.watch_outs:
        print("\nWatch Outs:")
        for w in brief.watch_outs:
            print(f"  ⚠️  {w}")
    if open_issues:
        print(f"\nOpen Issues: {len(open_issues)}")
    if todays_drafts:
        print(f"\nDrafts Ready: {len(todays_drafts)}")


def main():
    parser = argparse.ArgumentParser(description="AI Chief of Staff Morning Brief")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    config = load_config(args.config)
    run(config, dry_run=args.dry_run, no_email=args.no_email)


if __name__ == "__main__":
    main()
