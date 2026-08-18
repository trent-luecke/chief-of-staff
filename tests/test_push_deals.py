from unittest.mock import patch, MagicMock
from lib.metrics_client import push_deals


def test_push_deals_posts_to_ingest_and_returns_json():
    with patch("lib.metrics_client.requests.post") as mp:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"inserted": 2, "updated": 0}
        mp.return_value = resp
        out = push_deals("https://engine.example", "pw", [{"email": "x@acme.com"}])
    assert out == {"inserted": 2, "updated": 0}
    args, kwargs = mp.call_args
    assert args[0] == "https://engine.example/api/deals/ingest"
    assert kwargs["json"] == {"deals": [{"email": "x@acme.com"}]}
    assert kwargs["auth"] == ("", "pw")


def test_push_deals_is_non_fatal_on_error():
    import requests
    with patch("lib.metrics_client.requests.post", side_effect=requests.RequestException("down")):
        out = push_deals("https://engine.example", "pw", [{"email": "x@acme.com"}])
    assert out["status"] == "error"
