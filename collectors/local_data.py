import json
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Project:
    name: str
    status: str
    next_step: str
    notes: str = ""


@dataclass
class RecurringTask:
    name: str
    schedule: str
    description: str = ""


def load_projects(path: str) -> list[Project]:
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        return []

    projects = []
    # Split on "## Project:" headings (handles both start-of-file and mid-file)
    blocks = re.split(r"(?:^|\n)## Project: ", content)
    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        name = lines[0].strip()
        status = ""
        next_step = ""
        notes = ""
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("**Status:**"):
                status = line.replace("**Status:**", "").strip()
            elif line.startswith("**Next:**"):
                next_step = line.replace("**Next:**", "").strip()
            elif line.startswith("**Notes:**"):
                notes = line.replace("**Notes:**", "").strip()
        if name:
            projects.append(Project(name=name, status=status, next_step=next_step, notes=notes))
    return projects


def read_inbox(path: str) -> str:
    try:
        with open(os.path.expanduser(path)) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def load_due_recurring_tasks(path: str, target_date: Optional[date] = None) -> list[RecurringTask]:
    if target_date is None:
        target_date = date.today()

    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    day_name = target_date.strftime("%A")  # e.g. "Monday"
    due = []
    for task in data.get("tasks", []):
        schedule = task.get("schedule", "")
        name = task.get("name", "")
        description = task.get("description", "")
        if not name:
            continue

        if schedule == "daily":
            due.append(RecurringTask(name=name, schedule=schedule, description=description))
        elif schedule == "weekly":
            task_day = task.get("day", "")
            if task_day.lower() == day_name.lower():
                due.append(RecurringTask(name=name, schedule=schedule, description=description))
        elif schedule == "monthly":
            task_day = str(task.get("day", ""))
            if task_day == str(target_date.day):
                due.append(RecurringTask(name=name, schedule=schedule, description=description))
    return due
