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
SERVER_PORT = 8002
PROXY_PORT = 9002  # Using 9002 to avoid conflict with Telegram proxy
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"
REAL_WHATSAPP_URL = "https://graph.facebook.com"

TEST_ACCESS_TOKEN = os.environ.get("AK_WHATSAPP__ACCESS_TOKEN", "")
TEST_PHONE_NUMBER_ID = os.environ.get("AK_WHATSAPP__PHONE_NUMBER_ID", "")
TEST_VERIFY_TOKEN = os.environ.get("AK_WHATSAPP__VERIFY_TOKEN", "test_verify_token")
TEST_TO_NUMBER = os.environ.get("AK_TEST_WHATSAPP_TO_NUMBER", "")

TEST_QUESTION = "Who won the 1996 cricket world cup?"
EXPECTED_ANSWER = ["Sri Lanka won the 1996 Cricket World Cup."]
BOT_REPLY_WAIT = 15

# Global state
captured_messages = []
captured_real_responses = []


async def proxy_whatsapp_handler(request):
    """
    Transparent Proxy Handler.
    1. Intercepts /<version>/<phone_number_id>/messages
    2. Captures content for verification.
    3. Forwards to Real WhatsApp API.
    4. Returns Real Response.
    """
    path = request.path
    data = await request.json()
    print(f"\n[Proxy] Intercepted Request to {path}")

    # Store for test verification
    if "messages" in path and data.get("type") == "text":
        captured_messages.append(data)

    # Forward to Real WhatsApp
    # Construct real URL: https://graph.facebook.com/vX.Y/PHONE_ID/messages
    real_url = f"{REAL_WHATSAPP_URL}{path}"

    # Forwarding the exact same headers (like Auth)
    auth_header = request.headers.get("Authorization")
    headers = {"Content-Type": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header

    async with httpx.AsyncClient() as client:
        try:
            print(f"[Proxy] Forwarding to {real_url}...")
            resp = await client.post(real_url, json=data, headers=headers, timeout=30.0)

            if resp.status_code == 200:
                try:
                    real_data = resp.json()
                    captured_real_responses.append(real_data)
                except Exception:
                    pass

            # Return Real Response to Agent Kernel
            raw_content_type = resp.headers.get("Content-Type", "application/json")
            safe_content_type = raw_content_type.split(";")[0].strip() if raw_content_type else "application/json"

            return web.Response(
                body=resp.content,
                status=resp.status_code,
                content_type=safe_content_type,
            )
        except Exception as e:
            print(f"[Proxy] Forwarding Failed: {e}")
            return web.json_response({"error": {"message": str(e)}}, status=500)


async def start_proxy_server():
    """Starts the Proxy server."""
    app = web.Application()
    # Catch-all for API path: /{version}/{phone_number_id}/messages
    # aiohttp router is strict. We need to match the specific version prefix.
    app.router.add_post("/{version}/{phone_id}/messages", proxy_whatsapp_handler)
    # also add a catch-all in case the version is missing or structured differently
    app.router.add_post("/{phone_id}/messages", proxy_whatsapp_handler)

    # We can also add a catch-all route to print any other requests that might be hitting the proxy
    async def catch_all(request):
        print(f"[Proxy] WARNING: Unmatched request intercepted: {request.method} {request.path}")
        return web.Response(status=404)

    app.router.add_route("*", "/{tail:.*}", catch_all)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PROXY_PORT)
    await site.start()
    return runner


@pytest.mark.asyncio
async def test_whatsapp_real_integration():
    """
    Real Proxy Integration Test for WhatsApp.

    1. Start Proxy & Agent.
    2. Simulate User Webhook.
    3. Verify Bot Reply locally.
    """
    if "OPENAI_API_KEY" not in os.environ:
        print("WARNING: OPENAI_API_KEY not found. Agent may fail.")

    missing_vars = []
    if not TEST_ACCESS_TOKEN:
        missing_vars.append("AK_WHATSAPP__ACCESS_TOKEN")
    if not TEST_PHONE_NUMBER_ID:
        missing_vars.append("AK_WHATSAPP__PHONE_NUMBER_ID")
    if not TEST_TO_NUMBER:
        missing_vars.append("AK_TEST_WHATSAPP_TO_NUMBER")

    if missing_vars:
        pytest.skip(f"Missing required env vars: {', '.join(missing_vars)}. Cannot run real integration test.")

    now_str = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%b %d, %Y %H:%M SLST")

    # 1. Start Proxy
    print(f"Starting Transparent Proxy on {PROXY_URL}...")
    proxy_runner = await start_proxy_server()

    # 2. Start Agent Kernel Server
    env = os.environ.copy()
    env["AK_WHATSAPP__API_BASE_URL"] = PROXY_URL  # Point to Proxy
    env["AK_API__PORT"] = str(SERVER_PORT)
    env["AK_WHATSAPP__ACCESS_TOKEN"] = TEST_ACCESS_TOKEN
    env["AK_WHATSAPP__PHONE_NUMBER_ID"] = TEST_PHONE_NUMBER_ID
    env["AK_WHATSAPP__VERIFY_TOKEN"] = TEST_VERIFY_TOKEN
    env["PYTHONUNBUFFERED"] = "1"

    # FORCE USE OF LOCAL `agentkernel` PACKAGE OVER INSTALLED COMPILED WHEEL
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ak-py/src"))
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src_dir}:{existing_path}" if existing_path else src_dir

    print(f"Starting Agent Kernel Server on {SERVER_URL}...")
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    try:
        # Wait for startup
        await asyncio.sleep(4)
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{SERVER_URL}/health")
                assert resp.status_code == 200
            except Exception:
                pytest.fail("Server failed to start")

        # 3. Send Webhook (Simulate user message)
        timestamp = str(int(time.time()))
        message_id = f"wamid.HBgL{int(time.time())}"
        webhook_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": TEST_PHONE_NUMBER_ID,
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "1234567890",
                                    "phone_number_id": TEST_PHONE_NUMBER_ID,
                                },
                                "contacts": [{"profile": {"name": "Test User"}, "wa_id": TEST_TO_NUMBER}],
                                "messages": [
                                    {
                                        "from": TEST_TO_NUMBER,
                                        "id": message_id,
                                        "timestamp": timestamp,
                                        "text": {"body": TEST_QUESTION},
                                        "type": "text",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

        print(f"\nTriggering Agent via Webhook simulating message from {TEST_TO_NUMBER}...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{SERVER_URL}/whatsapp/webhook",
                json=webhook_payload,
            )
            assert resp.status_code == 200, f"Webhook rejected with {resp.status_code}"

        # 4. Wait for Proxy Interception
        print(f"Waiting {BOT_REPLY_WAIT}s for agent response...")
        await asyncio.sleep(BOT_REPLY_WAIT)

        # 5. Verify Intercepted Message
        if not captured_messages:
            fail_msg = f"❌ WhatsApp integration test FAILED - {now_str} - No reply intercepted"
            print(fail_msg)
            pytest.fail("Bot did not send any message via Proxy")

        reply_msg = captured_messages[-1]
        reply_text = reply_msg.get("text", {}).get("body", "")
        print(f"Intercepted Bot Reply: '{reply_text}'")

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

        if not test_passed:
            pytest.fail(f"WhatsApp integration test failed: {error_detail}")

        print("\nWhatsApp Integration Test PASSED!")

    finally:
        proc.terminate()
        proc.wait()
        await proxy_runner.cleanup()
