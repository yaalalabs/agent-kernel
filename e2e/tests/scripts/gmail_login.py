"""One-time interactive OAuth login for a Gmail account, printed as base64.

Run twice — once logged into the BOT Gmail account (value goes to the deployment's
GMAIL_TOKEN_B64 / TF_VAR_gmail_token_b64) and once logged into the TESTER account
(value goes to E2E_GMAIL_TESTER_TOKEN_B64 for the tests). Run from e2e/tests:

    E2E_GMAIL_CLIENT_ID=... E2E_GMAIL_CLIENT_SECRET=... uv run python scripts/gmail_login.py

Opens a browser; pick the right Google account there. Requires an OAuth client of type
"Desktop app" with the Gmail API enabled, and both accounts added as test users (or the
consent screen published) in the Google Cloud console.
"""

import base64
import os
import pickle

from google_auth_oauthlib.flow import InstalledAppFlow

# Same scopes as agentkernel's Gmail handler
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main():
    client_id = os.environ.get("E2E_GMAIL_CLIENT_ID") or input("OAuth client ID: ")
    client_secret = os.environ.get("E2E_GMAIL_CLIENT_SECRET") or input("OAuth client secret: ")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    token_b64 = base64.b64encode(pickle.dumps(creds)).decode("utf-8")
    print("\nBase64-encoded token (keep it secret — it grants full mailbox access):\n")
    print(token_b64)


if __name__ == "__main__":
    main()
