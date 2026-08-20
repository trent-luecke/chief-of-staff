import importlib
import subprocess
import sys
from pathlib import Path

from lib.storage import LocalStorage
from lib.deal_events import load_events

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill_deals.py"


def _storage(tmp_path):
    (tmp_path / "pipeline_cache.json").write_text(
        '{"leads": ['
        '{"page_id":"p1","name":"Acme","email":"jane@acme.com","status":"In-Trial / Post Demo","last_contacted":"2026-06-24","estimated_value":2000},'
        '{"page_id":"p2","name":"Baxter","email":null,"status":"Lost","last_contacted":"2026-05-21"}'
        ']}')
    return LocalStorage(base_dir=str(tmp_path))


def test_dry_run_appends_nothing_but_reports(tmp_path):
    mod = importlib.import_module("scripts.backfill_deals")
    st = _storage(tmp_path)
    summary = mod.run_backfill(st, "2026-08-19T12:00:00Z", dry_run=True)
    assert summary["leads"] == 2 and summary["events"] == 2
    assert summary["appended"] == 0                       # dry run
    assert summary["email_keyed"] == 1 and summary["notion_keyed"] == 1
    assert load_events(st) == []                          # nothing written


def test_real_run_appends_and_is_idempotent(tmp_path):
    mod = importlib.import_module("scripts.backfill_deals")
    st = _storage(tmp_path)
    first = mod.run_backfill(st, "2026-08-19T12:00:00Z", dry_run=False)
    assert first["appended"] == 2
    assert len(load_events(st)) == 2
    second = mod.run_backfill(st, "2026-08-19T12:00:00Z", dry_run=False)
    assert second["appended"] == 0                        # idempotent
    assert len(load_events(st)) == 2


def test_cli_dry_run_invocation_succeeds(tmp_path):
    """Invoke the script as a real subprocess (not via importlib) to catch
    sys.path / import errors that pytest's own path setup would mask."""
    (tmp_path / "config.json").write_text('{"data_dir": "data"}')
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "pipeline_cache.json").write_text(
        '{"leads": ['
        '{"page_id":"p1","name":"Acme","email":"jane@acme.com","status":"In-Trial / Post Demo","last_contacted":"2026-06-24","estimated_value":2000},'
        '{"page_id":"p2","name":"Baxter","email":null,"status":"Lost","last_contacted":"2026-05-21"}'
        ']}')

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--dry-run"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "leads" in result.stdout
    assert not (data_dir / "deal_events.jsonl").exists()
