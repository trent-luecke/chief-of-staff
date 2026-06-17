import os
import pytest
from outputs.dashboard import write_dashboard
from processors.brief import BriefContent
from processors.loops import LoopSummary


def test_write_dashboard_creates_file(tmp_path):
    brief = BriefContent(
        act_today=["P1", "P2", "P3"],
        what_moved=["Risk 1"],
    )
    out_path = str(tmp_path / "dashboard.html")
    write_dashboard(
        brief=brief,
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        output_path=out_path,
        template_dir="templates",
    )
    assert os.path.exists(out_path)
    with open(out_path) as f:
        content = f.read()
    assert "P1" in content


def test_write_dashboard_creates_parent_dirs(tmp_path):
    brief = BriefContent(
        act_today=["A", "B", "C"],
    )
    nested_path = str(tmp_path / "nested" / "deep" / "dashboard.html")
    write_dashboard(
        brief=brief,
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        output_path=nested_path,
        template_dir="templates",
    )
    assert os.path.exists(nested_path)


def test_write_dashboard_overwrites_existing(tmp_path):
    out_path = str(tmp_path / "dashboard.html")
    # Write initial content
    with open(out_path, "w") as f:
        f.write("<html>old content</html>")

    brief = BriefContent(
        act_today=["New summary", "X", "Y"],
    )
    write_dashboard(
        brief=brief,
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        output_path=out_path,
        template_dir="templates",
    )
    with open(out_path) as f:
        content = f.read()
    assert "New summary" in content
    assert "old content" not in content
