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
from collectors.local_data import load_projects, load_due_recurring_tasks
from collectors.notion_inbox import fetch_inbox_items
from processors.state import StateSnapshot, save_snapshot, load_snapshot, diff_snapshots
from processors.loops import build_loop_summary
from processors.brief import generate_brief
from outputs.sender import build_gmail_service_from_config, build_html_email, send_brief_email
from outputs.dashboard import write_dashboard


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def run(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    print("🗓  Fetching calendar...")
    today_events, tomorrow_events = fetch_two_day_events(config["calendar_ids"])

    print("📧  Fetching Gmail...")
    email_threads = fetch_threads_needing_attention(
        user_email=config["email"],
        max_results=config.get("unread_email_max", 15),
    )

    print("📋  Loading projects and recurring tasks...")
    projects = load_projects(config["projects_file"])
    due_tasks = load_due_recurring_tasks(config["recurring_file"])

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
        print("ERROR: ANTHROPIC_API_KEY not set. Add it to your .env file.", file=sys.stderr)
        sys.exit(1)

    print("🤖  Generating brief with Claude...")
    brief = generate_brief(
        api_key=api_key,
        model=config["ai_model"],
        today_events=today_events,
        tomorrow_events=tomorrow_events,
        email_threads=email_threads,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
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
    print(f"   Dashboard: {os.path.abspath(config['dashboard_path'])}")

    if not dry_run and not no_email:
        print("📤  Sending email...")
        gmail = build_gmail_service_from_config(config["credentials_path"], config["token_path"])
        subject = f"{config['brief_subject_prefix']} — {datetime.now().strftime('%A, %B ')+str(datetime.now().day)}"
        html = build_html_email(brief, today_events, projects, due_tasks, loop_summary)
        msg_id = send_brief_email(gmail, config["email"], subject, html)
        print(f"   Sent: {msg_id}")
    else:
        print("   (email skipped — dry-run or --no-email mode)")

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


def main():
    parser = argparse.ArgumentParser(description="AI Chief of Staff Morning Brief")
    parser.add_argument("--dry-run", action="store_true", help="Skip email send (state snapshot still saved)")
    parser.add_argument("--no-email", action="store_true", help="Generate brief but skip email send")
    parser.add_argument("--config", default="config.json", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)
    run(config, dry_run=args.dry_run, no_email=args.no_email)


if __name__ == "__main__":
    main()
