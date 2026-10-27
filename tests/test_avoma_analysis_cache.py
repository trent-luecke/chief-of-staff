"""Per-meeting-UUID cache for Avoma Claude analyses (shared across brief + avoma_sync)."""
from unittest.mock import patch, MagicMock

from lib.storage import LocalStorage


_ANALYSIS = {
    "os_interested": True,
    "call_type": "demo",
    "summary": "Good demo call.",
    "action_items": ["Send pricing deck"],
}


def _list_response(uuids):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "results": [
            {
                "uuid": u,
                "subject": f"OS Demo {u}",
                "start_at": "2026-10-26T14:00:00Z",
                "transcript_ready": True,
                "attendees": [
                    {"name": "John Smith", "email": "john@acme.com"},
                    {"name": "Trent Luecke", "email": "trent@teambuildr.com"},
                ],
            }
            for u in uuids
        ],
        "next": None,
    }
    return resp


def _run(storage, uuids=("m-1",), analysis=_ANALYSIS):
    from collectors.avoma import fetch_recent_meetings

    with patch("collectors.avoma.requests.get", return_value=_list_response(uuids)), \
         patch("collectors.avoma._fetch_transcript",
               return_value=([], [{"speaker_id": "1", "transcript": "Hi there"}])), \
         patch("collectors.avoma._analyze_with_claude", return_value=analysis) as mock_claude:
        out = fetch_recent_meetings(
            "avoma-key", "anthropic-key", "claude-sonnet-4-6",
            sales_rep_emails=["trent@teambuildr.com"],
            storage=storage,
        )
    return out, mock_claude


def test_second_run_reuses_cached_analysis(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))

    first, claude1 = _run(storage)
    second, claude2 = _run(storage)

    assert claude1.call_count == 1
    assert claude2.call_count == 0
    assert second[0].summary == "Good demo call."
    assert second[0].action_items == ["Send pricing deck"]


def test_non_os_results_are_cached_too(tmp_path):
    """Non-OS calls are the bulk of re-analysis; they must not be re-run either."""
    storage = LocalStorage(base_dir=str(tmp_path))
    non_os = {**_ANALYSIS, "os_interested": False}

    first, claude1 = _run(storage, analysis=non_os)
    second, claude2 = _run(storage, analysis=non_os)

    assert first == [] and second == []
    assert claude1.call_count == 1
    assert claude2.call_count == 0


def test_failed_analysis_is_not_cached(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))

    _run(storage, analysis=None)
    _, claude2 = _run(storage)

    assert claude2.call_count == 1


def test_prompt_change_invalidates_cache(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    _run(storage)

    with patch("collectors.avoma._analysis_version", return_value="different"):
        _, claude2 = _run(storage)

    assert claude2.call_count == 1


def test_only_new_meetings_are_analyzed(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    _run(storage, uuids=("m-1",))

    out, claude2 = _run(storage, uuids=("m-1", "m-2"))

    assert claude2.call_count == 1
    assert {t.uuid for t in out} == {"m-1", "m-2"}


def test_old_entries_are_pruned(tmp_path):
    from collectors.avoma import _CACHE_KEY, _analysis_version

    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json(_CACHE_KEY, {
        "stale": {"v": _analysis_version("claude-sonnet-4-6"),
                  "cached_at": "2020-01-01T00:00:00+00:00", "analysis": _ANALYSIS},
    })

    _run(storage)

    cache = storage.read_json(_CACHE_KEY)
    assert "stale" not in cache
    assert "m-1" in cache


def test_no_storage_still_works():
    out, claude = _run(None)
    assert claude.call_count == 1
    assert out[0].uuid == "m-1"


def test_broken_storage_is_non_fatal():
    storage = MagicMock()
    storage.read_json.side_effect = RuntimeError("R2 down")
    storage.write_json.side_effect = RuntimeError("R2 down")

    out, claude = _run(storage)

    assert claude.call_count == 1
    assert out[0].uuid == "m-1"
