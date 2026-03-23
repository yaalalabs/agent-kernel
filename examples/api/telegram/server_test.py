import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from agentkernel.test import Test
from aiohttp import web

# Configuration
SERVER_PORT = 8000
PROXY_PORT = 9000
SERVER_URL = f"http://localhost:{SERVER_PORT}"
PROXY_URL = f"http://localhost:{PROXY_PORT}"
REAL_TELEGRAM_URL = "https://api.telegram.org"

TEST_BOT_TOKEN = os.environ.get("AK_TELEGRAM__BOT_TOKEN", "")
TEST_WEBHOOK_SECRET = os.environ.get("AK_TELEGRAM__WEBHOOK_SECRET", "test_secret")

TEST_QUESTION = "Who won the 1996 cricket world cup?"
EXPECTED_ANSWER = ["Sri Lanka won the 1996 Cricket World Cup."]
BOT_REPLY_WAIT = 15

# Global state
captured_messages = []
captured_real_responses = []


async def proxy_telegram_handler(request):
    """
    Transparent Proxy Handler.
    1. Intercepts /bot<token>/sendMessage
    2. Captures content for verification.
    3. Forwards to Real Telegram API.
    4. Returns Real Response.
    """
    # Capture request
    path = request.path
    data = await request.json()
    print(f"\n[Proxy] Intercepted Request to {path}: {data}")

    # Store for test verification (only sendMessage)
    if "sendMessage" in path:
        captured_messages.append(data)

    # Forward to Real Telegram
    # Construct real URL: https://api.telegram.org/bot<token>/method
    real_url = f"{REAL_TELEGRAM_URL}{path}"

    async with httpx.AsyncClient() as client:
        try:
            print(f"[Proxy] Forwarding to {real_url}...")
            # We strip local headers and just send the JSON payload
            resp = await client.post(real_url, json=data, timeout=30.0)

            # Store the real response (which contains message_id) if successful
            if resp.status_code == 200 and "sendMessage" in path:
                try:
                    real_data = resp.json()
                    captured_real_responses.append(real_data)
                except Exception:
                    pass

            print(f"[Proxy] Real Telegram Response ({resp.status_code}): {resp.text}")

            # Return Real Response to Agent Kernel
            return web.Response(
                body=resp.content,
                status=resp.status_code,
                content_type=resp.headers.get("Content-Type", "application/json"),
            )
        except Exception as e:
            print(f"[Proxy] Forwarding Failed: {e}")
            return web.json_response({"ok": False, "description": str(e)}, status=500)


async def start_proxy_server():
    """Starts the Proxy server."""
    app = web.Application()
    # Catch-all for any bot method
    app.router.add_post(f"/bot{TEST_BOT_TOKEN}/{{method}}", proxy_telegram_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", PROXY_PORT)
    await site.start()
    return runner


async def _update_message(chat_id: int, message_id: int, text: str):
    """Update an existing Telegram message using editMessageText."""
    url = f"{REAL_TELEGRAM_URL}/bot{TEST_BOT_TOKEN}/editMessageText"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={"chat_id": chat_id, "message_id": message_id, "text": text})
        if resp.status_code != 200:
            print(f"Failed to update message: {resp.text}")


async def _delete_message(chat_id: int, message_id: int):
    """Delete a Telegram message."""
    url = f"{REAL_TELEGRAM_URL}/bot{TEST_BOT_TOKEN}/deleteMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "message_id": message_id})


@pytest.mark.asyncio
async def test_telegram_real_integration():
    """
    Real Proxy Integration Test (Slack-Like Flow).

    1. Post "Status" message to Group ("⏳ Testing...").
    2. Start Proxy & Agent.
    3. Simulate User Webhook.
    4. Verify Bot Reply locally.
    5. Delete Bot Reply from Group.
    6. Update "Status" message to "✅ PASSED".
    """
    if "OPENAI_API_KEY" not in os.environ:
        print("WARNING: OPENAI_API_KEY not found. Agent may fail.")
    if not TEST_BOT_TOKEN:
        pytest.skip("AK_TELEGRAM__BOT_TOKEN not set. Cannot run real integration test.")

    chat_id_str = os.environ.get("AK_TEST_TELEGRAM_CHAT_ID", "999999")
    chat_id = int(chat_id_str)
    if chat_id == 999999:
        print("WARNING: Using mock chat_id. Real messages won't appear.")

    now_str = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%b %d, %Y %H:%M SLST")

    # 0. Send Initial "Status" Message
    # matches: "grp showng Test integration Start- whi is the 1996 win"
    start_msg_text = f"⏳ Telegram Integration Test Started: {TEST_QUESTION}"
    print(f"Sending Start Message: '{start_msg_text}'")
    status_msg_id = None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{REAL_TELEGRAM_URL}/bot{TEST_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": start_msg_text},
        )
        if resp.status_code == 200:
            status_msg_id = resp.json()["result"]["message_id"]
            print(f"Status Message sent (ID: {status_msg_id})")
        else:
            print(f"Failed to send start message: {resp.text}")

    # 1. Start Proxy
    print(f"Starting Transparent Proxy on {PROXY_URL}...")
    proxy_runner = await start_proxy_server()

    # 2. Start Agent Kernel Server
    env = os.environ.copy()
    env["AK_TELEGRAM__API_BASE_URL"] = PROXY_URL  # Point to Proxy
    env["AK_API__PORT"] = str(SERVER_PORT)
    env["AK_TELEGRAM__BOT_TOKEN"] = TEST_BOT_TOKEN

    print(f"Starting Agent Kernel Server on {SERVER_URL}...")
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    try:
        # Wait for startup
        await asyncio.sleep(3)
        async with httpx.AsyncClient() as client:
            try:
                await client.get(f"{SERVER_URL}/health")
            except Exception:
                pytest.fail("Server failed to start")

        # 3. Send Webhook (Simulate user message)
        # This will trigger the agent to reply "Sri Lanka..."
        timestamp = int(time.time())
        webhook_payload = {
            "update_id": timestamp,
            "message": {
                "message_id": 1,
                "from": {"id": chat_id, "is_bot": False, "first_name": "TestUser"},
                "chat": {"id": chat_id, "type": "private"},
                "date": timestamp,
                "text": TEST_QUESTION,
            },
        }

        print(f"\nTriggering Agent via Webhook...")
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{SERVER_URL}/telegram/webhook",
                json=webhook_payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": TEST_WEBHOOK_SECRET},
            )

        # 4. Wait for Proxy Interception
        print(f"Waiting {BOT_REPLY_WAIT}s for agent response...")
        await asyncio.sleep(BOT_REPLY_WAIT)

        # 5. Verify Intercepted Message
        bot_messages = [m for m in captured_messages if "text" in m]
        if not bot_messages:
            fail_msg = f"❌ Telegram integration test FAILED - {now_str} - No reply"
            if status_msg_id:
                await _update_message(chat_id, status_msg_id, fail_msg)
            pytest.fail("Bot did not send any message via Proxy")

        reply_msg = bot_messages[-1]
        reply_text = reply_msg["text"]
        print(f"Intercepted Bot Reply: '{reply_text}'")

        # Get Real Message ID of the Reply (to delete it later)
        reply_real_id = None
        if captured_real_responses:
            last_resp = captured_real_responses[-1]
            if last_resp.get("ok"):
                reply_real_id = last_resp["result"]["message_id"]

        # 6. Compare Content
        test_passed = True
        error_detail = ""
        try:
            Test.compare(reply_text, EXPECTED_ANSWER, user_input=TEST_QUESTION, threshold=70)
            print("Test.compare passed -- response is correct!")
        except AssertionError as e:
            test_passed = False
            error_detail = str(e)[:200]
            print(f"Test.compare failed: {error_detail}")

        # 7. Cleanup & Update (Exact "Slack-like" behavior)

        # A. Delete the "Sri Lanka" reply (keep chat clean)
        if reply_real_id:
            print(f"Deleting Verification Reply (ID: {reply_real_id})...")
            await _delete_message(chat_id, reply_real_id)

        # B. Update the "Status" message to PASS/FAIL
        if status_msg_id:
            if test_passed:
                result_text = f"Telegram integration test PASSED - {now_str}"
            else:
                result_text = f"Telegram integration test FAILED - {now_str}\n{error_detail}"

            print(f"Updating Status Message {status_msg_id} -> '{result_text}'")
            await _update_message(chat_id, status_msg_id, result_text)

        if not test_passed:
            pytest.fail(f"Telegram integration test failed: {error_detail}")

    finally:
        proc.terminate()
        proc.wait()
        await proxy_runner.cleanup()
