"""
Instagram Integration Test

End-to-end test that:
1. Starts the Agent Kernel server with Instagram integration
2. Sends a realistic HMAC-signed Instagram webhook payload
3. Verifies the webhook is processed successfully
4. Checks that the agent generates the correct response

Required environment variables:
    AK_INSTAGRAM__ACCESS_TOKEN - Instagram user access token
    AK_INSTAGRAM__VERIFY_TOKEN - For webhook verification
    AK_INSTAGRAM__APP_SECRET   - For signing webhook requests (optional but recommended)
    AK_INSTAGRAM__PAGE_ID      - Instagram Business Account ID
    AK_TEST_INSTAGRAM_USER_ID  - Test user's Instagram-Scoped ID (IGSID)
    OPENAI_API_KEY             - For the AI agent

Usage:
    cd examples/api/instagram && ./build.sh local
    uv run pytest server_test.py -s --junitxml=pytest-report.xml
"""

import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

SERVER_URL = "http://localhost:8000"

ACCESS_TOKEN = os.environ.get("AK_INSTAGRAM__ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("AK_INSTAGRAM__VERIFY_TOKEN", "")
APP_SECRET = os.environ.get("AK_INSTAGRAM__APP_SECRET", "")
TEST_USER_ID = os.environ.get("AK_TEST_INSTAGRAM_USER_ID", "")
PAGE_ID = os.environ.get("AK_INSTAGRAM__PAGE_ID", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
API_VERSION = "v24.0"

SKIP_REASON = "Missing required env vars for Instagram integration test"
SHOULD_SKIP = not all([ACCESS_TOKEN, VERIFY_TOKEN, TEST_USER_ID, PAGE_ID, OPENAI_KEY])

pytestmark = pytest.mark.asyncio(loop_scope="session")


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def send(self, endpoint: str, method: str = "post", body=None):
        payload = {} if body is None else body
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, f"{self.url}{endpoint}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def server_process():
    """Start the Agent Kernel server as a subprocess and wait until healthy."""
    proc = subprocess.Popen(
        ["python3", "server.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    # Poll /health until the server is ready (up to 30s)
    max_wait = 30
    start = time.time()
    server_ready = False
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.time() - start < max_wait:
            if proc.poll() is not None:
                pytest.fail(
                    f"Server process exited with code {proc.returncode} "
                    "before becoming ready. Check the server logs above."
                )
            try:
                resp = await client.get(f"{SERVER_URL}/health")
                if resp.status_code == 200:
                    server_ready = True
                    break
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            await asyncio.sleep(1)

    if not server_ready:
        proc.terminate()
        pytest.fail(f"Server did not become healthy within {max_wait}s")

    print(f"Server ready in {time.time() - start:.1f}s")
    try:
        yield proc
    finally:
        proc.terminate()
        proc.wait()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client(server_process):
    """Provide an API test client that depends on the shared server."""
    yield APITestClient(SERVER_URL)


TEST_QUESTION = "Who won the 1996 cricket world cup?"
EXPECTED_ANSWER = "Sri Lanka won the 1996 cricket world cup."

# Time to wait for the bot to process the question
BOT_REPLY_WAIT = 20


async def _get_conversation_id() -> str:
    """Get the conversation ID for the test user."""
    url = f"https://graph.instagram.com/{API_VERSION}/me/conversations"
    params = {"user_id": TEST_USER_ID, "access_token": ACCESS_TOKEN}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("data"):
            raise ValueError(f"No conversation found for user {TEST_USER_ID}")
        return data["data"][0]["id"]


async def _get_latest_message_from_conversation(conversation_id: str) -> dict:
    """Get the most recent message from a conversation."""
    # Get message IDs
    url = f"https://graph.instagram.com/{API_VERSION}/{conversation_id}"
    params = {"fields": "messages", "access_token": ACCESS_TOKEN}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        messages = data.get("messages", {}).get("data", [])
        if not messages:
            raise ValueError(f"No messages found in conversation {conversation_id}")

        # Get the content of the most recent message
        latest_msg_id = messages[0]["id"]
        url = f"https://graph.instagram.com/{API_VERSION}/{latest_msg_id}"
        params = {"fields": "id,created_time,from,to,message", "access_token": ACCESS_TOKEN}
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def _send_message_to_user(user_id: str, text: str) -> str:
    """Send a message directly to a user via Send API. Returns message ID."""
    url = f"https://graph.instagram.com/{API_VERSION}/me/messages"
    payload = {
        "recipient": {"id": user_id},
        "message": {"text": text},
    }
    params = {"access_token": ACCESS_TOKEN}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message_id", "")


def _compute_instagram_signature(body: str) -> str:
    """Compute a valid Instagram request signature using HMAC-SHA256."""
    if not APP_SECRET:
        return ""
    signature = hmac.new(
        APP_SECRET.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"


def _build_instagram_event_payload(sender_id: str, text: str) -> dict:
    """Build a realistic Instagram 'message' event payload."""
    ts = int(time.time() * 1000)
    return {
        "object": "instagram",
        "entry": [
            {
                "id": PAGE_ID,
                "time": ts,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": PAGE_ID},
                        "timestamp": ts,
                        "message": {
                            "mid": f"m_{uuid.uuid4().hex}",
                            "text": text,
                        },
                    }
                ],
            }
        ],
    }


# Tests
@pytest.mark.asyncio
@pytest.mark.skipif(SHOULD_SKIP, reason=SKIP_REASON)
async def test_health(http_client):
    """Smoke test: verify the server starts and /health returns ok."""
    response = await http_client.send("/health", method="get")
    assert response == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.skipif(SHOULD_SKIP, reason=SKIP_REASON)
async def test_instagram_integration(server_process):
    """
    End-to-end Instagram integration test.

    Sends a webhook, waits for the bot to reply, reads the response back using
    the Conversations API, and validates it matches the expected answer.
    """
    # Send the question to the user in Instagram first (so they see it in their app)
    print(f"\n Sending question to Instagram: '{TEST_QUESTION}'")
    try:
        await _send_message_to_user(TEST_USER_ID, f"Integration Test Question:\n{TEST_QUESTION}")
        print("Question sent to Instagram")
    except Exception as e:
        print(f"Could not send question to Instagram: {e}")

    # Wait a moment for the message to be delivered
    await asyncio.sleep(2)

    # Build and send the signed webhook (to trigger bot processing)
    payload = _build_instagram_event_payload(TEST_USER_ID, TEST_QUESTION)
    body_str = json.dumps(payload)
    signature = _compute_instagram_signature(body_str)

    print(f"\n Sending webhook to trigger bot processing...")

    headers = {"Content-Type": "application/json"}
    if signature:
        headers["x-hub-signature-256"] = signature

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SERVER_URL}/instagram/webhook",
            content=body_str,
            headers=headers,
        )

    print(f"Server responded with status: {resp.status_code}")
    assert resp.status_code == 200, f"Webhook failed with status {resp.status_code}"

    # Give the server time to process and send the reply
    print(f"Waiting {BOT_REPLY_WAIT}s for bot to process and reply...")
    await asyncio.sleep(BOT_REPLY_WAIT)

    # Read the bot's reply using Conversations API
    print("\n Reading bot's response from Instagram...")
    conversation_id = await _get_conversation_id()
    print(f"Found conversation ID: {conversation_id}")

    latest_message = await _get_latest_message_from_conversation(conversation_id)

    # Extract message details
    message_text = latest_message.get("message", "")
    from_id = latest_message.get("from", {}).get("id", "")

    print(f"Latest message from: {from_id}")
    print(f"Bot's reply: '{message_text}'")

    # Verify the message is from the Page (bot) not the user
    if from_id != PAGE_ID:
        pytest.fail(f"Latest message is not from the bot (Page ID {PAGE_ID}), but from {from_id}")

    # Validate the response using Test.compare
    print("\n Validating bot response with Test.compare()...")
    test_passed = False
    error_detail = ""

    try:
        Test.compare(message_text, [EXPECTED_ANSWER], threshold=70)
        print("Test.compare passed - response is correct!")
        test_passed = True
    except AssertionError as e:
        error_detail = str(e)[:200]
        print(f"Test.compare failed: {error_detail}")
        test_passed = False

    # Send the result to Instagram
    print("\n Sending test result to Instagram...")
    if test_passed:
        result_msg = f"INTEGRATION TEST PASSED\n\nQuestion: {TEST_QUESTION}\nBot replied: {message_text}\n\nResponse validated successfully!"
    else:
        result_msg = f"INTEGRATION TEST FAILED\n\nQuestion: {TEST_QUESTION}\nBot replied: {message_text}\nExpected: {EXPECTED_ANSWER}\n\nError: {error_detail}"

    try:
        await _send_message_to_user(TEST_USER_ID, result_msg)
        print("Result sent to Instagram")
    except Exception as e:
        print(f"Could not send result to Instagram: {e}")

    # Fail the test if validation failed
    if not test_passed:
        pytest.fail(f"Bot response validation failed: {error_detail}")
