import processors.meeting_prep as mp


def test_demo_line_uses_snapshot(monkeypatch):
    monkeypatch.setattr(mp, "_demo_count_from_engine", lambda: 7, raising=False)
    line = mp._format_demos_line()
    assert "Demos MTD: 7" in line


def test_demo_line_unavailable(monkeypatch):
    monkeypatch.setattr(mp, "_demo_count_from_engine", lambda: None, raising=False)
    assert "unavailable" in mp._format_demos_line().lower()
