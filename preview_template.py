#!/usr/bin/env python3
"""Render morning_brief.html with dummy data and open in browser."""

import os
import tempfile
import webbrowser
from datetime import datetime, date
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

class FakeEvent:
    def __init__(self, time_str, summary):
        self.start = datetime.strptime(time_str, "%H:%M")
        self.summary = summary

dummy = {
    "date_str": date.today().strftime("%A, %B %-d"),
    "generated_at": datetime.now().strftime("%-I:%M %p"),
    "brief": type("Brief", (), {
        "executive_summary": "Today is a high-leverage day. You have two key sales calls and a pipeline review. Focus on the Midwest deal — it's ready to close.",
        "top_3_priorities": [
            "Close the Midwest deal — follow up on the contract sent Monday",
            "Prep talking points for the 2pm pipeline review with the team",
            "Review and respond to the three unread Notion action items",
        ],
        "watch_outs": [
            "The Q2 forecast numbers don't account for the two deals that slipped to June — you may want to reset expectations before the team call.",
        ],
        "schedule_notes": "Back-to-back meetings 10am–12pm — block time after lunch for deep work.",
    })(),
    "today_events": [
        FakeEvent("09:00", "1:1 with Caty — weekly sync"),
        FakeEvent("10:00", "Sales call: Midwest Gym Group (30 min)"),
        FakeEvent("10:30", "Sales call: Pacific Strength (30 min)"),
        FakeEvent("14:00", "Pipeline review — full team"),
        FakeEvent("16:00", "Wrap-up / async block"),
    ],
    "loop_summary": type("LoopSummary", (), {
        "resolved_email_ids": ["abc123"],
        "resolved_notion_ids": [],
        "new_email_loops": [
            {"subject": "Re: Contract for Q2 onboarding", "from": "coach@midwestgym.com", "snippet": "Looks good — just one question about the cancellation clause..."},
        ],
        "new_notion_loops": [
            {"name": "Follow up: Pacific Strength demo", "urgency": "high"},
        ],
        "still_open_email_ids": ["old_thread_1", "old_thread_2"],
    })(),
    "projects": [
        type("Project", (), {"name": "Q2 Pipeline Push", "status": "On Track", "next_step": "Close 3 deals by May 15"})(),
        type("Project", (), {"name": "Gym Scout Automation", "status": "In Progress", "next_step": "Review scoring model output from last night's run"})(),
        type("Project", (), {"name": "Chief of Staff P4", "status": "Planning", "next_step": "Finalize two-way interface spec"})(),
    ],
    "due_tasks": [
        type("Task", (), {"schedule": "Daily", "name": "Check pipeline activity in Notion"})(),
        type("Task", (), {"schedule": "Weekly", "name": "Send team wins recap to Slack"})(),
    ],
}

env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
template = env.get_template("morning_brief.html")
html = template.render(**dummy)

with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
    f.write(html)
    path = f.name

print(f"Opening preview: {path}")
webbrowser.open(f"file://{path}")
