import json
import os
from unittest.mock import patch, MagicMock
import pytest
from lib.google_auth import (
    _get_credentials,
    build_gmail_service,
    build_calendar_service,
    ALL_SCOPES,
    GMAIL_SCOPES,
    CALENDAR_SCOPES,
)

FAKE_OAUTH_JSON = json.dumps({
    "client_id": "123.apps.googleusercontent.com",
    "client_secret": "fake-secret",
    "refresh_token": "1//fake-refresh-token",
    "token_uri": "https://oauth2.googleapis.com/token",
    "scopes": ALL_SCOPES,
})


def test_gmail_scopes_defined():
    assert "https://www.googleapis.com/auth/gmail.readonly" in GMAIL_SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" in GMAIL_SCOPES


def test_calendar_scopes_defined():
    assert "https://www.googleapis.com/auth/calendar.readonly" in CALENDAR_SCOPES


def test_get_credentials_returns_credentials():
    with patch.dict(os.environ, {"GOOGLE_OAUTH_JSON": FAKE_OAUTH_JSON}):
        creds = _get_credentials()
        assert creds.refresh_token == "1//fake-refresh-token"
        assert creds.client_id == "123.apps.googleusercontent.com"


def test_get_credentials_missing_env_raises():
    env = {k: v for k, v in os.environ.items() if k != "GOOGLE_OAUTH_JSON"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="GOOGLE_OAUTH_JSON"):
            _get_credentials()


def test_get_credentials_malformed_json_raises():
    with patch.dict(os.environ, {"GOOGLE_OAUTH_JSON": "not-json"}):
        with pytest.raises(RuntimeError, match="not valid JSON"):
            _get_credentials()


def test_build_gmail_service_returns_service():
    with patch.dict(os.environ, {"GOOGLE_OAUTH_JSON": FAKE_OAUTH_JSON}):
        with patch("lib.google_auth.build") as mock_build:
            mock_build.return_value = MagicMock()
            build_gmail_service("trent@teambuildr.com")
            mock_build.assert_called_once_with("gmail", "v1", credentials=mock_build.call_args[1]["credentials"])


def test_build_calendar_service_returns_service():
    with patch.dict(os.environ, {"GOOGLE_OAUTH_JSON": FAKE_OAUTH_JSON}):
        with patch("lib.google_auth.build") as mock_build:
            mock_build.return_value = MagicMock()
            build_calendar_service("trent@teambuildr.com")
            mock_build.assert_called_once_with("calendar", "v3", credentials=mock_build.call_args[1]["credentials"])
