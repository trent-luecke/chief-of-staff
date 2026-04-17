"""Google OAuth2 authentication — reuses sales-prep-tool credentials."""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def get_credentials(credentials_path: str, token_path: str) -> Credentials:
    """Get valid Google OAuth2 credentials, prompting login if needed."""
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Google API credentials not found at {credentials_path}. "
                    "Download your OAuth client JSON from Google Cloud Console "
                    "and save it there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        os.chmod(token_path, 0o600)  # Restrict to owner read/write only

    return creds


def build_calendar_service(creds: Credentials):
    """Build Google Calendar API service client."""
    return build("calendar", "v3", credentials=creds)


def build_gmail_service(creds: Credentials):
    """Build Gmail API service client."""
    return build("gmail", "v1", credentials=creds)


def build_sheets_service(creds: Credentials):
    """Build Google Sheets API service client."""
    return build("sheets", "v4", credentials=creds)


def build_docs_service(creds: Credentials):
    """Build Google Docs API service client."""
    return build("docs", "v1", credentials=creds)


def build_drive_service(creds: Credentials):
    """Build Google Drive API service client."""
    return build("drive", "v3", credentials=creds)
