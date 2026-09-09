"""End-to-end test for the Gmail integration.

Sends a real email from the tester Gmail account to the bot account, then polls the
tester's copy of the thread for the deployed agent's reply. Two distinct accounts are
required: the deployed handler replies to the sender, so send-to-self would make the bot
answer its own replies in a loop.

Required environment variables:
- E2E_GMAIL_TESTER_TOKEN_B64: base64 token.pickle of the TESTER account
  (generate with scripts/gmail_login.py while logged into the tester account).
- E2E_GMAIL_BOT_ADDRESS: email address of the bot account the deployment polls.
"""

import base64
import pickle
import time
import uuid
from email.mime.text import MIMEText

from conftest import POLL_INTERVAL_SECONDS, require_env

GMAIL_REPLY_TIMEOUT_SECONDS = 300


def _gmail_service(token_b64: str):
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = pickle.loads(base64.b64decode(token_b64))
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def _header(message: dict, name: str) -> str:
    for header in message["payload"]["headers"]:
        if header["name"].lower() == name.lower():
            return header["value"]
    return ""


def test_gmail_round_trip():
    env = require_env("E2E_GMAIL_TESTER_TOKEN_B64", "E2E_GMAIL_BOT_ADDRESS")
    bot_address = env["E2E_GMAIL_BOT_ADDRESS"].lower()
    service = _gmail_service(env["E2E_GMAIL_TESTER_TOKEN_B64"])

    nonce = uuid.uuid4().hex[:8]
    message = MIMEText("What is 2 + 2? Reply with a short answer.")
    message["to"] = bot_address
    message["subject"] = f"AK E2E test {nonce}"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    thread_id = sent["threadId"]

    reply = None
    deadline = time.monotonic() + GMAIL_REPLY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        for m in thread.get("messages", []):
            if m["id"] != sent["id"] and bot_address in _header(m, "From").lower():
                reply = m
                break
        if reply:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    assert reply is not None, f"No reply from {bot_address} in thread {thread_id} within {GMAIL_REPLY_TIMEOUT_SECONDS}s"
    assert reply.get("snippet", "").strip(), f"Bot reply has no visible content: {reply.get('id')}"
