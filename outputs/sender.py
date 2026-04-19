import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, FileSystemLoader

from collectors.calendar import CalendarEvent
from collectors.local_data import Project, RecurringTask
from processors.brief import BriefContent
from processors.loops import LoopSummary


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
    html = template.render(
        brief=brief,
        today_events=today_events,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        date_str=now.strftime("%A, %B ") + str(now.day),
        generated_at=now.strftime("%I:%M %p").lstrip("0"),
    )
    footer = (
        '<hr style="margin-top: 40px; border: none; border-top: 1px solid #eee;">'
        '<p style="font-size: 12px; color: #999; margin-top: 16px;">'
        "Reply to this email to give feedback on this brief."
        "</p>"
    )
    return html + footer


def send_brief_email(
    gmail_service,
    to_email: str,
    subject: str,
    html_body: str,
    plain_text: str = "Morning brief — view in an HTML-capable email client.",
    thread_id: str = None,
) -> tuple[str, str]:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = to_email
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body: dict = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    result = gmail_service.users().messages().send(userId="me", body=body).execute()
    return result.get("id", ""), result.get("threadId", "")
