import os
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
from collectors.calendar import CalendarEvent
from collectors.local_data import Project, RecurringTask
from processors.brief import BriefContent
from processors.loops import LoopSummary


def write_dashboard(
    brief: BriefContent,
    today_events: list[CalendarEvent],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    output_path: str = "output/dashboard.html",
    template_dir: str = "templates",
    metric_results: list = None,
) -> None:
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("dashboard.html")
    now = datetime.now()
    html = template.render(
        brief=brief,
        today_events=today_events,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        metric_results=metric_results or [],
        date_str=now.strftime("%A, %B ") + str(now.day),
        generated_at=now.strftime("%I:%M %p").lstrip("0"),
    )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
