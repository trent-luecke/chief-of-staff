import base64
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, FileSystemLoader

from collectors.calendar import CalendarEvent
from collectors.local_data import Project, RecurringTask
from processors.brief import BriefContent
from processors.loops import LoopSummary

from lib.google_auth import get_credentials, build_gmail_service as _build_gmail_service


def build_gmail_service_from_config(credentials_path: str, token_path: str):
    creds = get_credentials(credentials_path, token_path)
    return _build_gmail_service(creds)


def build_html_email(
    brief: BriefContent,
    today_events: list[CalendarEvent],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    template_dir: str = "templates",
) -> str:
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("morning_brief.html")
    now = datetime.now()
    return template.render(
        brief=brief,
        today_events=today_events,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        date_str=now.strftime("%A, %B ") + str(now.day),
        generated_at=now.strftime("%I:%M %p").lstrip("0"),
    )


def send_brief_email(
    gmail_service,
    to_email: str,
    subject: str,
    html_body: str,
) -> str:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = to_email
    msg.attach(MIMEText("Morning brief — view in an HTML-capable email client.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return result.get("id", "")
