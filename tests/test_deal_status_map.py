import pytest
from lib.deal_status_map import map_notion_status


@pytest.mark.parametrize("status,expected", [
    ("Demo Scheduled", ("demoed", "open")),
    ("No-Show", ("demoed", "open")),
    ("Out of Demo / Need Upate", ("demoed", "open")),  # Notion's spelling
    ("No Trial / Post Demo", ("demoed", "open")),
    ("On-Hold", ("demoed", "open")),
    ("In-Trial / Post Demo", ("in_trial", "open")),
    ("Closed", ("won", "won")),
    ("Lost", ("lost", "lost")),
])
def test_known_statuses(status, expected):
    assert map_notion_status(status) == expected


def test_unknown_and_blank_default_to_demoed_open():
    assert map_notion_status("Something New") == ("demoed", "open")
    assert map_notion_status("") == ("demoed", "open")
    assert map_notion_status(None) == ("demoed", "open")


def test_surrounding_whitespace_tolerated():
    assert map_notion_status("  Closed  ") == ("won", "won")
