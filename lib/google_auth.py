import json
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ALL_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets",  # read + write (interview tracker)
]

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _get_credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_OAUTH_JSON")
    if not raw:
        raise RuntimeError(
            "GOOGLE_OAUTH_JSON environment variable is not set. "
            "Run scripts/authorize.py to generate it."
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GOOGLE_OAUTH_JSON is not valid JSON: {e}") from e
    return Credentials(
        token=None,
        refresh_token=data["refresh_token"],
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data.get("scopes", ALL_SCOPES),
    )


def build_gmail_service(user_email: str = ""):
    return build("gmail", "v1", credentials=_get_credentials())


def build_calendar_service(user_email: str = ""):
    return build("calendar", "v3", credentials=_get_credentials())


def build_sheets_service(user_email: str = ""):
    return build("sheets", "v4", credentials=_get_credentials())
