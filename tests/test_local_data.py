from datetime import date
import pytest
from collectors.local_data import load_projects, load_due_recurring_tasks, Project, RecurringTask


FIXTURES = "tests/fixtures"


def test_load_projects_parses_markdown():
    projects = load_projects(f"{FIXTURES}/projects.md")
    assert len(projects) == 2
    assert projects[0].name == "CRM Automation"
    assert projects[0].status == "In Progress"
    assert projects[0].next_step == "Deploy to staging"


def test_load_projects_missing_file_returns_empty():
    projects = load_projects("nonexistent/projects.md")
    assert projects == []


def test_due_recurring_tasks_daily_always_due():
    tasks = load_due_recurring_tasks(f"{FIXTURES}/recurring.json", target_date=date(2026, 4, 17))
    names = [t.name for t in tasks]
    assert "Check trials" in names


def test_due_recurring_tasks_weekly_on_correct_day():
    monday = date(2026, 4, 20)  # known Monday
    tasks = load_due_recurring_tasks(f"{FIXTURES}/recurring.json", target_date=monday)
    names = [t.name for t in tasks]
    assert "Review pipeline" in names


def test_due_recurring_tasks_weekly_not_on_wrong_day():
    tuesday = date(2026, 4, 21)
    tasks = load_due_recurring_tasks(f"{FIXTURES}/recurring.json", target_date=tuesday)
    names = [t.name for t in tasks]
    assert "Review pipeline" not in names


def test_due_recurring_tasks_monthly_on_first():
    first = date(2026, 5, 1)
    tasks = load_due_recurring_tasks(f"{FIXTURES}/recurring.json", target_date=first)
    names = [t.name for t in tasks]
    assert "Monthly metrics" in names


def test_due_recurring_tasks_monthly_not_on_other_days():
    second = date(2026, 5, 2)
    tasks = load_due_recurring_tasks(f"{FIXTURES}/recurring.json", target_date=second)
    names = [t.name for t in tasks]
    assert "Monthly metrics" not in names
