import json
import os
from unittest.mock import patch, MagicMock
import pytest
from lib.google_auth import get_service_account_credentials, build_gmail_service, build_calendar_service, GMAIL_SCOPES, CALENDAR_SCOPES

FAKE_SA_JSON = json.dumps({
    "type": "service_account",
    "project_id": "test",
    "private_key_id": "key1",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "chief-of-staff@test.iam.gserviceaccount.com",
    "client_id": "123",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
})


def test_gmail_scopes_defined():
    assert "https://www.googleapis.com/auth/gmail.readonly" in GMAIL_SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" in GMAIL_SCOPES


def test_calendar_scopes_defined():
    assert "https://www.googleapis.com/auth/calendar.readonly" in CALENDAR_SCOPES


def test_get_service_account_credentials_returns_delegated_creds():
    with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SA_JSON}):
        with patch("lib.google_auth.service_account.Credentials.from_service_account_info") as mock_sa:
            mock_creds = MagicMock()
            mock_sa.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_creds
            result = get_service_account_credentials(GMAIL_SCOPES, "trent@teambuildr.com")
            mock_sa.assert_called_once_with(
                json.loads(FAKE_SA_JSON), scopes=GMAIL_SCOPES
            )
            mock_creds.with_subject.assert_called_once_with("trent@teambuildr.com")
            assert result == mock_creds


def test_build_gmail_service_returns_service():
    with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SA_JSON}):
        with patch("lib.google_auth.get_service_account_credentials") as mock_creds:
            with patch("lib.google_auth.build") as mock_build:
                mock_build.return_value = MagicMock()
                result = build_gmail_service("trent@teambuildr.com")
                mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds.return_value)
                assert result == mock_build.return_value


def test_build_calendar_service_returns_service():
    with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SA_JSON}):
        with patch("lib.google_auth.get_service_account_credentials") as mock_creds:
            with patch("lib.google_auth.build") as mock_build:
                mock_build.return_value = MagicMock()
                result = build_calendar_service("trent@teambuildr.com")
                mock_build.assert_called_once_with("calendar", "v3", credentials=mock_creds.return_value)
                assert result == mock_build.return_value


def test_get_service_account_credentials_raises_if_env_missing():
    env = {k: v for k, v in os.environ.items() if k != "GOOGLE_SERVICE_ACCOUNT_JSON"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="GOOGLE_SERVICE_ACCOUNT_JSON"):
            get_service_account_credentials(GMAIL_SCOPES, "trent@teambuildr.com")


def test_get_service_account_credentials_raises_if_json_malformed():
    with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": "not-json"}):
        with pytest.raises(RuntimeError, match="not valid JSON"):
            get_service_account_credentials(GMAIL_SCOPES, "trent@teambuildr.com")
