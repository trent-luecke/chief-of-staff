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
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    return creds.with_subject(subject_email)


def build_gmail_service(user_email: str):
    creds = get_service_account_credentials(GMAIL_SCOPES, user_email)
    return build("gmail", "v1", credentials=creds)


def build_calendar_service(user_email: str):
    creds = get_service_account_credentials(CALENDAR_SCOPES, user_email)
    return build("calendar", "v3", credentials=creds)
