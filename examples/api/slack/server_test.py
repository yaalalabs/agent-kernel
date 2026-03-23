"""
Slack Integration Test

End-to-end test that:
1. Starts the Agent Kernel server with Slack integration
2. Sends a realistic HMAC-signed Slack webhook payload
3. Waits for the bot to reply in a real Slack test channel
4. Verifies the reply content using Test.compare()
5. Overwrites the bot's messages with a pass/fail result summary

Required environment variables:
    SLACK_SIGNING_SECRET     - For signing the webhook payload
    SLACK_BOT_TOKEN          - For the server + reading/updating channel messages
    OPENAI_API_KEY           - For the AI agent
    AK_TEST_SLACK_CHANNEL_ID - Dedicated Slack test channel ID

Usage:
    cd examples/api/slack && ./build.sh local
    uv run pytest server_integration_test.py -s --junitxml=pytest-report.xml
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
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

SERVER_URL = "http://localhost:8000"

SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("AK_TEST_SLACK_CHANNEL_ID", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

SKIP_REASON = "Missing required env vars for Slack integration test"
SHOULD_SKIP = not all([SIGNING_SECRET, BOT_TOKEN, CHANNEL_ID, OPENAI_KEY])

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

# Time to wait for the bot to process the question and post a reply in Slack
BOT_REPLY_WAIT = 20


def _compute_slack_signature(body: str, timestamp: str) -> str:
    """Compute a valid Slack request signature using HMAC-SHA256."""
    sig_basestring = f"v0:{timestamp}:{body}"
    signature = hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"v0={signature}"


def _build_slack_event_payload(channel: str, text: str) -> dict:
    """Build a realistic Slack 'message' event payload."""
    ts = f"{time.time():.6f}"
    return {
        "token": "test-verification-token",
        "team_id": "T_INTEGRATION_TEST",
        "api_app_id": "A_INTEGRATION_TEST",
        "event": {
            "type": "message",
            "channel": channel,
            "user": "U_TEST_USER",
            "text": text,
            "ts": ts,
            "event_ts": ts,
            "channel_type": "channel",
        },
        "type": "event_callback",
        "event_id": f"Ev{uuid.uuid4().hex[:10].upper()}",
        "event_time": int(time.time()),
    }


async def _read_channel_messages() -> list[dict]:
    """Read the most recent message from the dedicated test channel."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://slack.com/api/conversations.history",
            params={
                "channel": CHANNEL_ID,
                "limit": 1,
            },
            headers={"Authorization": f"Bearer {BOT_TOKEN}"},
        )
        resp.raise_for_status()
        data = resp.json()

        print(
            f"conversations.history response: ok={data.get('ok')}, "
            f"messages={len(data.get('messages', []))}, "
            f"error={data.get('error', 'none')}"
        )

        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")

        return data.get("messages", [])


async def _read_thread_replies(parent_ts: str) -> list[dict]:
    """Read thread replies under a parent message using conversations.replies."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://slack.com/api/conversations.replies",
            params={
                "channel": CHANNEL_ID,
                "ts": parent_ts,
            },
            headers={"Authorization": f"Bearer {BOT_TOKEN}"},
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("ok"):
            raise RuntimeError(f"Slack API error (replies): {data.get('error', 'unknown')}")

        # First message is the parent itself, skip it and return only replies
        messages = data.get("messages", [])
        return messages[1:] if len(messages) > 1 else []


async def _update_message(channel: str, ts: str, text: str):
    """Update an existing Slack message using chat.update."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://slack.com/api/chat.update",
            json={"channel": channel, "ts": ts, "text": text},
            headers={"Authorization": f"Bearer {BOT_TOKEN}"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            print(f"chat.update failed: {data.get('error', 'unknown')}")


async def _delete_message(channel: str, ts: str):
    """Delete a Slack message using chat.delete."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://slack.com/api/chat.delete",
            json={"channel": channel, "ts": ts},
            headers={"Authorization": f"Bearer {BOT_TOKEN}"},
        )
        resp.raise_for_status()


async def _post_result(text: str):
    """Post a standalone result message to the test channel."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": CHANNEL_ID, "text": text},
            headers={"Authorization": f"Bearer {BOT_TOKEN}"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"chat.postMessage failed: {data.get('error', 'unknown')}")


# Tests
@pytest.mark.asyncio
async def test_health(http_client):
    """Smoke test: verify the server starts and /health returns ok."""
    response = await http_client.send("/health", method="get")
    assert response == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.skipif(SHOULD_SKIP, reason=SKIP_REASON)
async def test_slack_integration(server_process):
    """
    End-to-end Slack integration test.

    Sends a real webhook, waits for bot reply, verifies content,
    then overwrites the acknowledgment with pass/fail and deletes the thread reply.
    """
    now_str = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")

    # Build and send the signed webhook
    payload = _build_slack_event_payload(CHANNEL_ID, TEST_QUESTION)
    body_str = json.dumps(payload)
    timestamp = str(int(time.time()))
    signature = _compute_slack_signature(body_str, timestamp)

    print(f"\nSending Slack webhook with question: '{TEST_QUESTION}'")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{SERVER_URL}/slack/events",
            content=body_str,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
        )

    print(f"Server responded with status: {resp.status_code}")
    assert resp.status_code == 200, f"Webhook failed with status {resp.status_code}"

    # Wait for the bot to reply
    print(f"Waiting {BOT_REPLY_WAIT}s for bot to process and reply...")
    await asyncio.sleep(BOT_REPLY_WAIT)

    # Find the acknowledgment (parent message) in the channel
    channel_messages = await _read_channel_messages()

    if not channel_messages:
        fail_msg = f"Slack integration test FAILED - {now_str} - No bot message found"
        print(fail_msg)
        await _post_result(fail_msg)
        pytest.fail("Bot did not post any message in the test channel")

    # The acknowledgment is the parent message (top-level in the channel)
    parent_msg = channel_messages[0]
    parent_ts = parent_msg.get("ts", "")
    print(f"Found parent message (acknowledgment) ts={parent_ts}")

    # Read the reply from the thread
    thread_replies = await _read_thread_replies(parent_ts)

    reply_text = ""
    reply_timestamps = []

    for reply in thread_replies:
        reply_timestamps.append(reply.get("ts", ""))
        blocks = reply.get("blocks", [])
        if blocks:
            for block in blocks:
                text_obj = block.get("text", {})
                if isinstance(text_obj, dict):
                    reply_text += text_obj.get("text", "")
                elif isinstance(text_obj, str):
                    reply_text += text_obj
            break
        # Fallback to plain text
        elif reply.get("text") and reply.get("text") != "Agent response":
            reply_text = reply["text"]
            break

    if not reply_text:
        fail_msg = f"Slack integration test FAILED - {now_str} - No AI reply in thread"
        print(fail_msg)
        await _update_message(CHANNEL_ID, parent_ts, fail_msg)
        pytest.fail("Bot did not reply in the thread within the timeout")

    print(f"Bot reply: '{reply_text}'")

    # Verify the reply using Test.compare
    test_passed = True
    error_detail = ""
    try:
        Test.compare(reply_text, [EXPECTED_ANSWER], threshold=70)
        print("Test.compare passed -- response is correct!")
    except AssertionError as e:
        test_passed = False
        error_detail = str(e)[:200]
        print(f"Test.compare failed: {error_detail}")

    # Overwrite acknowledgment with result, delete thread replies
    if test_passed:
        result_text = f"Slack integration test PASSED - {now_str}"
    else:
        result_text = f"Slack integration test FAILED - {now_str} - {error_detail}"

    # Overwrite the acknowledgment (parent) with the result
    await _update_message(CHANNEL_ID, parent_ts, result_text)
    print(f"Updated acknowledgment {parent_ts} -> '{result_text}'")

    # Delete all thread replies
    for reply_ts in reply_timestamps:
        try:
            await _delete_message(CHANNEL_ID, reply_ts)
            print(f"Deleted thread reply {reply_ts}")
        except Exception:
            pass

    if not test_passed:
        pytest.fail(f"Slack integration test failed: {error_detail}")

    print(f"\nIntegration test complete: {result_text}")
