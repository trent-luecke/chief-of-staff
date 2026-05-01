#!/usr/bin/env python3
"""One-time OAuth2 authorization flow. Run locally to generate GOOGLE_OAUTH_JSON."""

import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

CREDENTIALS_FILE = "credentials/credentials.json"


def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"ERROR: {CREDENTIALS_FILE} not found.")
        print("Download an OAuth 2.0 Desktop client credentials file from Google Cloud Console")
        print("(APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app)")
        print(f"and save it to {CREDENTIALS_FILE}")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes or SCOPES),
    }

    output_path = "credentials/google_oauth.json"
    with open(output_path, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\nSaved to {output_path}")
    print("\n--- Copy the value below as your GOOGLE_OAUTH_JSON GitHub Secret ---\n")
    print(json.dumps(token_data))
    print("\n-------------------------------------------------------------------")


if __name__ == "__main__":
    main()
