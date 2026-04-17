import os
from collectors.calendar import CalendarEvent
from collectors.local_data import Project, RecurringTask
from processors.brief import BriefContent
from processors.loops import LoopSummary
from outputs.sender import build_html_email


def write_dashboard(
    brief: BriefContent,
    today_events: list[CalendarEvent],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    output_path: str = "output/dashboard.html",
    template_dir: str = "templates",
) -> None:
    html = build_html_email(brief, today_events, projects, due_tasks, loop_summary, template_dir)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
