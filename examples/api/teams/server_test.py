"""
Teams Integration Test

End-to-end test that:
1. Starts the Agent Kernel server with Teams integration
2. Acquires a Bot Framework emulator-style auth token using real Azure credentials
3. Starts a local proxy to capture the bot's outgoing replies (via serviceUrl intercept)
4. Sends the test question to the real Teams conversation (so the user sees it)
5. Posts a signed Bot Framework activity to the server to trigger processing
6. Waits for the bot to reply and validates the response
7. Sends the test result (pass/fail) to the Teams conversation

How Teams auth works here:
  The Bot Framework Channel Service sends incoming activities signed with a JWT from the
  "botframework.com" Azure AD tenant (d6d49420-f39b-4df7-a1dc-d59a935871db).
  We replicate this by acquiring a token from that tenant using the bot's own credentials
  (client_credentials flow), which produces a token with iss=sts.windows.net/{BF_TENANT}
  and aud={APP_ID} — exactly what botbuilder's EmulatorValidation accepts.

How the reply is captured:
  The Bot Framework adapter sends the bot's reply to the serviceUrl in the incoming activity.
  We set serviceUrl to our local proxy, which captures the POST and records the reply text.

Required environment variables:
    AK_TEAMS__APP_ID              - Azure Bot App ID
    AK_TEAMS__APP_PASSWORD        - Azure Bot App Password / Client Secret
    AK_TEAMS__TENANT_ID           - Azure Tenant ID
    OPENAI_API_KEY                - For the AI agent

Optional (for real Teams delivery — like the WhatsApp transparent proxy test):
    AK_TEST_TEAMS_SERVICE_URL     - Real Teams serviceUrl from a real bot interaction log
                                    e.g. https://smba.trafficmanager.net/apac/<tenant-id>/
                                    (check bot logs for the exact URL including region)
    AK_TEST_TEAMS_CONVERSATION_ID - Real conversation ID from bot logs (preferred, simplest)
                                    e.g. a:1qHb7DyM_5z6O3gXpg-_Z...
    AK_TEST_TEAMS_USER_AAD_ID     - Azure AD Object ID of the Teams user (alternative;
                                    used to auto-create a conversation if CONVERSATION_ID
                                    is not provided)

    When SERVICE_URL + CONVERSATION_ID are set, the proxy forwards the bot reply directly.
    When SERVICE_URL + USER_AAD_ID are set, it tries to create a conversation first.
    The message will appear in the user's Teams chat with the bot.

Usage:
    cd examples/api/teams && ./build.sh local
    uv run pytest server_test.py -s --junitxml=pytest-report.xml
"""

import asyncio
import os
import subprocess
import sys
import time

import httpx
import msal
import pytest
import pytest_asyncio
from agentkernel.test import Test
from aiohttp import web

SERVER_PORT = 8000
PROXY_PORT = 9003
SERVER_URL = f"http://localhost:{SERVER_PORT}"
PROXY_URL = f"http://localhost:{PROXY_PORT}"

# Bot Framework's special Azure AD tenant used for emulator-style channel auth tokens
BF_TENANT_ID = "d6d49420-f39b-4df7-a1dc-d59a935871db"

APP_ID = os.environ.get("AK_TEAMS__APP_ID", "")
APP_PASSWORD = os.environ.get("AK_TEAMS__APP_PASSWORD", "")
TENANT_ID = os.environ.get("AK_TEAMS__TENANT_ID", "common")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

# Optional: when set, the proxy forwards the bot reply to the real Teams service
REAL_TEAMS_SERVICE_URL = os.environ.get("AK_TEST_TEAMS_SERVICE_URL", "").rstrip("/")
REAL_TEAMS_CONVERSATION_ID = os.environ.get("AK_TEST_TEAMS_CONVERSATION_ID", "")
REAL_TEAMS_USER_AAD_ID = os.environ.get("AK_TEST_TEAMS_USER_AAD_ID", "")

# Will be populated at runtime when a real conversation is created
_real_conversation_id: str = ""

SKIP_REASON = "Missing required env vars for Teams integration test"
SHOULD_SKIP = not all([APP_ID, APP_PASSWORD, TENANT_ID, OPENAI_KEY])

pytestmark = pytest.mark.asyncio(loop_scope="session")

TEST_QUESTION = "Who won the 1996 cricket world cup?"
EXPECTED_ANSWER = ["Sri Lanka won the 1996 Cricket World Cup."]
BOT_REPLY_WAIT = 20
CONVERSATION_ID = "teams-test-conversation-001"

# Captures bot reply payloads posted to our proxy
captured_replies: list[dict] = []
captured_real_responses: list[dict] = []


async def _get_incoming_auth_token() -> str:
    """
    Acquire a Bot Framework emulator-style JWT using the bot's own Azure credentials.

    Uses the BF tenant ID (d6d49420-...) as the authority and the bot app_id as the
    resource. This replicates exactly what the Bot Framework Channel Service sends
    when delivering activities to a bot endpoint, so botbuilder accepts it as valid.
    """
    msal_app = msal.ConfidentialClientApplication(
        APP_ID,
        authority=f"https://login.microsoftonline.com/{BF_TENANT_ID}",
        client_credential=APP_PASSWORD,
    )
    result = msal_app.acquire_token_for_client(scopes=[f"{APP_ID}/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Failed to acquire BF auth token: {result.get('error_description', result)}")
    return result["access_token"]


async def _get_connector_token() -> str:
    """
    Acquire a Bot Framework connector token for calling the real Teams service.
    Uses the bot's own tenant (not the BF tenant) with scope api.botframework.com.
    """
    msal_app = msal.ConfidentialClientApplication(
        APP_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=APP_PASSWORD,
    )
    result = msal_app.acquire_token_for_client(scopes=["https://api.botframework.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Failed to acquire connector token: {result.get('error_description', result)}")
    return result["access_token"]


async def _create_teams_conversation(connector_token: str) -> str:
    """
    Create a proactive 1:1 conversation with a Teams user via Bot Framework REST API.
    Returns the real conversation ID that can be used to deliver messages.
    """
    create_url = f"{REAL_TEAMS_SERVICE_URL}/v3/conversations"
    payload = {
        "bot": {"id": APP_ID, "name": "TestBot"},
        "members": [{"id": f"29:{REAL_TEAMS_USER_AAD_ID}"}],
        "channelData": {"tenant": {"id": TENANT_ID}},
        "isGroup": False,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            create_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {connector_token}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create Teams conversation: {resp.status_code} - {resp.text}")
        data = resp.json()
        return data.get("id", "")


async def _send_message_to_teams(text: str) -> bool:
    """
    Send a message to the real Teams conversation via Bot Framework REST API.
    Returns True if message was sent successfully, False otherwise.
    Only works when SERVICE_URL and _real_conversation_id are available.
    """
    if not REAL_TEAMS_SERVICE_URL or not _real_conversation_id:
        return False

    url = f"{REAL_TEAMS_SERVICE_URL}/v3/conversations/{_real_conversation_id}/activities"
    activity = {
        "type": "message",
        "text": text,
        "from": {"id": APP_ID, "name": "TestBot"},
        "conversation": {"id": _real_conversation_id},
    }
    try:
        connector_token = await _get_connector_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json=activity,
                headers={
                    "Authorization": f"Bearer {connector_token}",
                    "Content-Type": "application/json",
                },
            )
            return resp.status_code in (200, 201)
    except Exception:
        return False


async def _proxy_handler(request):
    """
    Transparent proxy for outgoing Bot Framework replies (bot -> Teams service URL).
    The Bot Framework adapter POSTs the bot's reply to:
      {serviceUrl}/v3/conversations/{conversationId}/activities[/{replyToId}]

    When AK_TEST_TEAMS_SERVICE_URL is set:
      - Captures the reply text for validation
      - Forwards the request to the real Teams service (same headers + body)
      - Returns the real Teams response → message actually delivered in Teams

    When AK_TEST_TEAMS_SERVICE_URL is not set:
      - Captures only, returns a fake 200 response (no real delivery)
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    if data.get("type") == "message" and data.get("text"):
        captured_replies.append(data)

    # Always return 200 to the Bot Framework adapter first (so the server never crashes).
    # Then forward to the real Teams service asynchronously if configured.
    if REAL_TEAMS_SERVICE_URL and _real_conversation_id and data.get("type") == "message":
        # Rewrite the conversation ID and forward to the real Teams service
        fwd_data = dict(data)
        if "conversation" in fwd_data:
            fwd_data["conversation"] = dict(fwd_data["conversation"])
            fwd_data["conversation"]["id"] = _real_conversation_id

        # Build the real URL using the real conversation ID
        real_path = f"/v3/conversations/{_real_conversation_id}/activities"
        real_url = f"{REAL_TEAMS_SERVICE_URL}{real_path}"

        try:
            connector_token = await _get_connector_token()
            fwd_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {connector_token}",
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(real_url, json=fwd_data, headers=fwd_headers, timeout=30.0)
                if resp.status_code in (200, 201):
                    try:
                        captured_real_responses.append(resp.json())
                    except Exception:
                        pass
        except Exception:
            pass

    return web.json_response({"id": "proxy-reply-001"}, status=200)


async def _start_proxy_server():
    """Start local HTTP server to intercept bot's outgoing replies."""
    app = web.Application()
    app.router.add_post("/v3/conversations/{conv_id}/activities", _proxy_handler)
    app.router.add_post("/v3/conversations/{conv_id}/activities/{reply_id}", _proxy_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", PROXY_PORT)
    await site.start()
    return runner


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def send(self, endpoint: str, method: str = "post", body=None):
        payload = {} if body is None else body
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, f"{self.url}{endpoint}", json=payload)
            resp.raise_for_status()
            return resp.json()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def server_process():
    """Start the Agent Kernel server as a subprocess and wait until healthy."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    max_wait = 30
    start = time.time()
    server_ready = False
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.time() - start < max_wait:
            if proc.poll() is not None:
                pytest.fail(f"Server process exited with code {proc.returncode} " "before becoming ready.")
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

    try:
        yield proc
    finally:
        proc.terminate()
        proc.wait()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client(server_process):
    yield APITestClient(SERVER_URL)


@pytest.mark.asyncio
@pytest.mark.skipif(SHOULD_SKIP, reason=SKIP_REASON)
async def test_health(http_client):
    """Smoke test: verify the server starts and /health returns ok."""
    response = await http_client.send("/health", method="get")
    assert response == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.skipif(SHOULD_SKIP, reason=SKIP_REASON)
async def test_teams_integration(server_process):
    """
    End-to-end Teams integration test (like Messenger test).

    1. Acquires a Bot Framework emulator-style auth token from Azure AD (BF tenant)
    2. Starts a local proxy to intercept the bot's outgoing reply (via serviceUrl)
    3. Sends the test question to the real Teams conversation (so the user sees it)
    4. Posts a Bot Framework activity to the server to trigger processing
    5. Waits for the bot to process and reply via the proxy
    6. Validates the captured reply with Test.compare()
    7. Sends the test result (pass/fail) to the Teams conversation
    """
    # 1. Acquire Bot Framework auth token
    try:
        token = await _get_incoming_auth_token()
    except Exception as e:
        pytest.skip(f"Could not acquire BF auth token: {e}")
        return

    # 2. Start local proxy to capture bot's outgoing reply
    proxy_runner = await _start_proxy_server()

    try:
        # 3. If real delivery is configured, resolve the real conversation ID
        global _real_conversation_id
        if REAL_TEAMS_SERVICE_URL and REAL_TEAMS_CONVERSATION_ID:
            _real_conversation_id = REAL_TEAMS_CONVERSATION_ID
        elif REAL_TEAMS_SERVICE_URL and REAL_TEAMS_USER_AAD_ID:
            try:
                connector_token = await _get_connector_token()
                _real_conversation_id = await _create_teams_conversation(connector_token)
            except Exception:
                _real_conversation_id = ""

        # 4. Send the question to Teams first (so the user sees it in their chat)
        sent = await _send_message_to_teams(f"Integration Test Question:\n{TEST_QUESTION}")
        if sent:
            await asyncio.sleep(2)

        # 5. Build a Bot Framework activity payload
        activity_payload = {
            "type": "message",
            "id": f"activity-{int(time.time())}",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "serviceUrl": PROXY_URL,  # Bot replies will be sent here (proxy intercepts)
            "channelId": "msteams",
            "from": {
                "id": "test-user-001",
                "name": "Test User",
                "aadObjectId": "00000000-0000-0000-0000-000000000001",
            },
            "conversation": {
                "id": CONVERSATION_ID,
                "isGroup": False,
                "conversationType": "personal",
                "tenantId": TENANT_ID,
            },
            "recipient": {
                "id": APP_ID,
                "name": "TestBot",
            },
            "text": TEST_QUESTION,
            "locale": "en-US",
            "entities": [],
            "channelData": {
                "tenant": {"id": TENANT_ID},
            },
        }

        # 6. POST the activity to the server with the Bot Framework auth header
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{SERVER_URL}/teams/messages",
                json=activity_payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

        if resp.status_code not in (200, 202):
            pytest.fail(f"Server rejected Teams activity: {resp.status_code} - {resp.text}")

        # 7. Wait for bot to process and send the reply
        await asyncio.sleep(BOT_REPLY_WAIT)

        # 8. Validate the captured reply
        text_replies = [r for r in captured_replies if r.get("text")]
        if not text_replies:
            pytest.fail("Bot did not send any reply to the proxy serviceUrl")

        reply_text = text_replies[-1]["text"]

        # 9. Validate with Test.compare()
        test_passed = False
        error_detail = ""

        try:
            Test.compare(reply_text, EXPECTED_ANSWER, user_input=TEST_QUESTION, threshold=70)
            test_passed = True
        except AssertionError as e:
            error_detail = str(e)[:200]
            test_passed = False

        # 10. Send the test result to Teams
        if test_passed:
            result_msg = (
                f"INTEGRATION TEST PASSED\n\n"
                f"Question: {TEST_QUESTION}\n"
                f"Bot replied: {reply_text}\n\n"
                f"Response validated successfully!"
            )
        else:
            result_msg = (
                f"INTEGRATION TEST FAILED\n\n"
                f"Question: {TEST_QUESTION}\n"
                f"Bot replied: {reply_text}\n"
                f"Expected: {EXPECTED_ANSWER}\n\n"
                f"Error: {error_detail}"
            )

        await _send_message_to_teams(result_msg)

        if not test_passed:
            pytest.fail(f"Bot response validation failed: {error_detail}")

    finally:
        await proxy_runner.cleanup()
