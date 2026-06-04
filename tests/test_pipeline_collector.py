# tests/test_pipeline_collector.py
import pytest
from collectors.pipeline import count_late_stage, PipelineLead


def _lead(status: str) -> PipelineLead:
    return PipelineLead(
        name="Test", contact="", email="",
        status=status, priority="",
        last_contacted=None, days_since_contact=None,
        estimated_value=None, source="", stale=False,
    )


LATE_STAGE = ["In-Trial / Post Demo", "No Trial / Post Demo"]


def test_count_late_stage_counts_matching_statuses():
    leads = [
        _lead("In-Trial / Post Demo"),
        _lead("In-Trial / Post Demo"),
        _lead("No Trial / Post Demo"),
        _lead("Demo Scheduled"),
        _lead("On-Hold"),
    ]
    assert count_late_stage(leads, LATE_STAGE) == 3


def test_count_late_stage_returns_zero_when_none_match():
    leads = [_lead("Demo Scheduled"), _lead("On-Hold")]
    assert count_late_stage(leads, LATE_STAGE) == 0


def test_count_late_stage_handles_empty_leads():
    assert count_late_stage([], LATE_STAGE) == 0


def test_count_late_stage_handles_empty_statuses():
    leads = [_lead("In-Trial / Post Demo")]
    assert count_late_stage(leads, []) == 0
