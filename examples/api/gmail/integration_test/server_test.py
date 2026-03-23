import asyncio
import base64
import os
import pickle
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import pytest
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Force use of local `agentkernel` package over installed compiled wheel for the test itself
src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ak-py/src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")


# --- Configuration ---
TEST_ADDRESS = os.environ.get("AK_TEST_GMAIL_ADDRESS", "")  # The Bot's email address
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.pickle")
TEST_QUESTION = "Who won the 1996 cricket world cup?"
EXPECTED_ANSWER = ["Sri Lanka won the 1996 Cricket World Cup."]
BOT_REPLY_WAIT = 30  # Wait time for bot to process and reply
# ---------------------


from google_auth_oauthlib.flow import InstalledAppFlow


def get_gmail_service():
    """Load credentials from token.pickle and return a Google API service."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired credential token...")
            creds.refresh(Request())
        else:
            print("No valid token.pickle found. Starting Google OAuth login flow...")
            client_id = os.environ.get("AK_GMAIL__CLIENT_ID")
            client_secret = os.environ.get("AK_GMAIL__CLIENT_SECRET")
            if not client_id or not client_secret:
                print("Cannot authenticate: Missing AK_GMAIL__CLIENT_ID or AK_GMAIL__CLIENT_SECRET")
                return None

            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": ["http://localhost"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            scopes = [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
            ]
            flow = InstalledAppFlow.from_client_config(client_config, scopes)

            # WSL: Do not try to open a local browser. Run on port 8080 (easier to port forward than port 0)
            try:
                creds = flow.run_local_server(port=8080, open_browser=False)
            except Exception as e:
                print(f"Failed to start local server on 8080, trying random port. Error: {e}")
                creds = flow.run_local_server(port=0, open_browser=False)

        # Save credentials for future use
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)
            print(f"Successfully saved new credentials to {TOKEN_FILE}")

    return build("gmail", "v1", credentials=creds)


def send_test_email(service, to_address, subject, text):
    """Send an email using the Gmail API."""
    message = MIMEText(text)
    message["to"] = to_address
    message["subject"] = subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    send_msg = {"raw": raw_message}
    result = service.users().messages().send(userId="me", body=send_msg).execute()
    return result["id"]


def _decode_body(payload: dict) -> str:
    """Helper to decode Gmail API message body."""
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8")
                    return body
            elif part.get("mimeType", "").startswith("multipart/"):
                nested = _decode_body(part)
                if nested:
                    return nested
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8")
    return body.strip()


async def wait_for_reply(service, thread_id, timeout_sec=60):
    """Poll the thread to see if a new message (reply) has been added."""
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        thread = service.users().threads().get(userId="me", id=thread_id).execute()
        messages = thread.get("messages", [])

        # If there are > 1 messages in the thread, the bot has replied!
        if len(messages) > 1:
            # Get the very last message in the thread
            latest_msg = messages[-1]
            # Make sure the latest message is actually from the bot to us (even though we are the bot)
            # The test assumes any new message in this thread is the reply
            return _decode_body(latest_msg["payload"])

        await asyncio.sleep(5)

    return None


@pytest.mark.asyncio
async def test_gmail_real_integration():
    """
    True E2E Integration Test for Gmail (Single Account Mode).

    1. Use Google API to send an email to ourselves (The Bot).
    2. Start the Agent Kernel Server (polling mode).
    3. Wait for the Agent to poll the email, process it, and send a reply to the same thread.
    4. Use Google API to check the thread for the reply and verify it.
    """
    if not TEST_ADDRESS:
        pytest.skip("Missing AK_TEST_GMAIL_ADDRESS. Cannot run real Gmail E2E test.")

    service = get_gmail_service()
    if not service:
        pytest.skip(f"Valid token.pickle not found at {TOKEN_FILE}. Cannot run real Gmail test.")

    now_str = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%b %d, %Y %H:%M SLST")
    run_id = str(int(time.time()))
    test_subject = f"Agent Kernel E2E Test - {run_id}"

    # 1. Send the fake user email (from ourselves, to ourselves)
    print(f"\nSending test email from {TEST_ADDRESS} to {TEST_ADDRESS}...")
    try:
        sent_msg_id = send_test_email(service, TEST_ADDRESS, test_subject, TEST_QUESTION)
        print(f"Test email sent! (Message ID: {sent_msg_id})")

        # Get the thread ID so we can poll for replies in the exact same thread
        sent_msg_full = service.users().messages().get(userId="me", id=sent_msg_id).execute()
        thread_id = sent_msg_full["threadId"]
    except Exception as e:
        pytest.fail(f"Failed to send setup email: {e}")

    # 2. Start Agent Kernel Server Subprocess
    env = os.environ.copy()
    # Force the bot to accept emails from itself (since we are using 1 account)
    env["AK_GMAIL__SENDER_FILTER"] = TEST_ADDRESS
    env["AK_GMAIL__TOKEN_FILE"] = TOKEN_FILE
    env["PYTHONUNBUFFERED"] = "1"

    # FORCE USE OF LOCAL `agentkernel` PACKAGE
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../ak-py/src"))
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src_dir}:{existing_path}" if existing_path else src_dir

    print("Starting Agent Kernel Server (Gmail Polling)...")
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    test_passed = False
    error_detail = "Unknown error or timeout"

    try:
        # 3. Wait for the reply in the thread
        print(f"Waiting {BOT_REPLY_WAIT}s for agent to poll, process, and reply...")
        reply_text = await wait_for_reply(service, thread_id, timeout_sec=BOT_REPLY_WAIT)

        # Immediately terminate the bot so it does not see its own reply and loop!
        print("Bot replied! Terminating server process before evaluation...")
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

        # 4. Verify Reply
        if not reply_text:
            fail_msg = f"❌ Gmail integration test FAILED - {now_str} - No reply received in thread"
            print(fail_msg)
            error_detail = "No reply received in thread"
            pytest.fail("Bot did not send any reply within the timeout.")

        print(f"Intercepted Bot Reply:\n{'-'*20}\n{reply_text}\n{'-'*20}")

        test_passed = True
        error_detail = ""
        try:
            Test.compare(reply_text, EXPECTED_ANSWER, user_input=TEST_QUESTION, threshold=30)
            print("Test.compare passed -- response is correct!")
        except AssertionError as e:
            test_passed = False
            error_detail = str(e)[:500]
            print(f"Test.compare failed: {error_detail}")

        if not test_passed:
            pytest.fail(f"Gmail integration test failed: {error_detail}")

        print("\nGmail E2E Integration Test PASSED!")

    finally:
        # Cleanup
        proc.terminate()
        proc.wait()

        # Delete the test thread to keep the inbox clean
        try:
            print("Cleaning up test thread from Gmail...")
            service.users().threads().trash(userId="me", id=thread_id).execute()
        except Exception as e:
            print(f"Warning: Failed to trash test thread: {e}")

        # Send result email
        status_text = "PASSED" if test_passed else "FAILED"
        result_subject = f"Gmail Integration Test {status_text} - {now_str}"
        result_body = (
            "The automated integration test completed successfully."
            if test_passed
            else f"The automated integration test failed:\n\n{error_detail}"
        )
        try:
            print(f"Sending final result email: {result_subject}")
            send_test_email(service, TEST_ADDRESS, result_subject, result_body)
        except Exception as e:
            print(f"Warning: Failed to send result email: {e}")


if __name__ == "__main__":
    asyncio.run(test_gmail_real_integration())
