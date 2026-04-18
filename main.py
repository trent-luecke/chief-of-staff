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
from collectors.gmail_personal import fetch_personal_emails
from collectors.local_data import load_projects, load_due_recurring_tasks, read_inbox
from collectors.notion_inbox import fetch_inbox_items
from processors.state import StateSnapshot, save_snapshot, load_snapshot, diff_snapshots
from processors.loops import build_loop_summary
from processors.issues import get_open_issues, auto_resolve_issues
from processors.meeting_memory import load_meeting_index, find_meeting_for_event, load_last_session_summary
from processors.drafts import generate_demo_followup, save_draft, load_todays_drafts
from processors.brief import generate_brief, BriefContent
from outputs.sender import build_gmail_service_from_config, build_html_email, send_brief_email
from outputs.dashboard import write_dashboard


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_personal_allowlist(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"allowed_senders": [], "allowed_domains": []}


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
    print("🗓  Fetching calendar...")
    today_events, tomorrow_events = fetch_two_day_events(
        config["calendar_ids"], profile=config.get("gmail_profile")
    )

    print("📧  Fetching Gmail (work)...")
    email_threads = fetch_threads_needing_attention(
        user_email=config["email"],
        max_results=config.get("unread_email_max", 15),
        profile=config.get("gmail_profile"),
    )

    print("📱  Fetching Gmail (personal)...")
    allowlist = load_personal_allowlist(config.get("personal_allowlist_file", "data/personal_allowlist.json"))
    personal_emails = fetch_personal_emails(
        profile=config.get("personal_gmail_profile", "personal"),
        allowed_senders=allowlist.get("allowed_senders", []),
        allowed_domains=allowlist.get("allowed_domains", []),
        max_results=20,
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

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

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
            personal_emails=personal_emails,
            drafts=todays_drafts,
            meeting_prep=meeting_prep,
            inbox_text=inbox_text,
        )
    except Exception as e:
        print(f"ERROR: Failed to generate brief: {e}", file=sys.stderr)
        brief = BriefContent(
            executive_summary="Brief generation failed — check logs.",
            top_3_priorities=["Check logs", "Retry: python main.py --no-email"],
            watch_outs=[str(e)[:200]],
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
        print("📤  Sending brief email...")
        gmail = build_gmail_service_from_config(config["credentials_path"], config["token_path"])
        subject = f"☀️ Morning Brief — {datetime.now().strftime('%A, %B %-d')}"
        html = build_html_email(brief, today_events, projects, due_tasks, loop_summary)
        msg_id = send_brief_email(gmail, config["email"], subject, html)
        print(f"   Sent: {msg_id}")
    else:
        print("   (email skipped)")

    print("💾  Saving state snapshot...")
    snapshot = StateSnapshot(
        date=date.today().isoformat(),
        open_email_thread_ids=today_email_ids,
        open_notion_item_ids=today_notion_ids,
    )
    save_snapshot(snapshot, config["state_dir"])

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
