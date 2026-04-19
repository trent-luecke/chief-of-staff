import json
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_service_account_credentials(scopes: list[str], subject_email: str):
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON environment variable is not set. "
            "Set it to the contents of your service account key JSON file."
        )
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}"
        ) from e
    creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    return creds.with_subject(subject_email)


def build_gmail_service(user_email: str):
    creds = get_service_account_credentials(GMAIL_SCOPES, user_email)
    return build("gmail", "v1", credentials=creds)


def build_calendar_service(user_email: str):
    creds = get_service_account_credentials(CALENDAR_SCOPES, user_email)
    return build("calendar", "v3", credentials=creds)
