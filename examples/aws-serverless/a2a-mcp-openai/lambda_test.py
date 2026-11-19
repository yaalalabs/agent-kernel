"""Tests for the deployed A2A and MCP example. Run them against a real deployment.

Set:
- AK_TEST_ENDPOINT: the stack's `agent_invoke_url` output (the chat route). Every other URL is derived from it.
- AK_TEST_TOKEN: the `demo_auth_token` the stack was deployed with, the credential the static identity provider in
  config.yaml accepts.

Each test prints the real status it got (run with `pytest -s`), so the output can be kept as the record that the
authorizer and FastMCP behave as the design says:

- an A2A message with no token is refused by the API Gateway authorizer (401 or 403);
- the A2A agent card and catalog are public: no token, 200;
- /mcp bypasses the authorizer, so a call with no token gets FastMCP's own 401, and a call with a valid token works;
- two A2A messages and two MCP calls on one session share the agent's memory, so the session holds across Lambda
  invocations.
"""

import asyncio
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from a2a.client import A2ACardResolver, ClientConfig
from a2a.client.base_client import BaseClient
from a2a.client.transports.rest import RestTransport
from a2a.helpers import get_message_text
from a2a.types import Message, Part, Role, SendMessageRequest
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, VERSION_HEADER
from fastmcp import Client

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

AGENT = "assistant"
TOKEN = os.getenv("AK_TEST_TOKEN", "")
# The gateway's own answers to a refused call: the UNAUTHORIZED and ACCESS_DENIED gateway responses the api-gateway
# module defines. FastMCP's 401 carries neither, which is how a test tells the two apart (FastMCP's own text also starts
# "Authentication failed", so only these exact strings identify the gateway).
GATEWAY_REFUSALS = ("Authentication failed: invalid or missing credentials", "Authentication failed: access denied")
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
A2A_HEADERS = {"Content-Type": "application/json", VERSION_HEADER: PROTOCOL_VERSION_CURRENT}


def show(label: str, response: httpx.Response) -> None:
    """Print the real status and the start of the body: the record of what the deployed stack answered."""
    print(f"\n[{label}] -> {response.status_code} {response.text[:200]!r}")


async def request(
    method: str, url: str, token: str | None = None, json: dict | None = None, headers: dict | None = None
) -> httpx.Response:
    """Send one request, with the bearer token unless `token` is None, retrying cold-start timeouts and 5xx."""
    request_headers = dict(headers or {})
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=40.0) as client:
        for attempt in range(3):
            try:
                response = await client.request(method, url, json=json, headers=request_headers)
            except httpx.TimeoutException:
                if attempt == 2:
                    raise
                continue
            # 502/503/504: a cold start can exceed the gateway's 29 s on the very first call.
            if response.status_code not in (502, 503, 504) or attempt == 2:
                return response
            await asyncio.sleep(5)
    return response


async def retrying(call, attempts: int = 3):
    """Run an async client call, retrying a cold start (the call raises when the gateway times out)."""
    for attempt in range(attempts):
        try:
            return await call()
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(5)


async def ask_a2a(base_url: str, prompt: str, context_id: str, token: str = TOKEN) -> str:
    """One A2A message:send as the SDK's client sends it; `context_id` is the session."""
    agent_url = f"{base_url}/a2a/{AGENT}"
    headers = {VERSION_HEADER: PROTOCOL_VERSION_CURRENT, "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=60, headers=headers) as http:
        card = await A2ACardResolver(http, base_url=agent_url).get_agent_card()
        # The explicit url is the one the test derived; the card's own is checked in test_the_agent_card_*.
        client = BaseClient(
            card, ClientConfig(streaming=False), RestTransport(http, card, url=agent_url), interceptors=[]
        )
        message = Message(
            message_id=str(uuid.uuid4()), context_id=context_id, role=Role.ROLE_USER, parts=[Part(text=prompt)]
        )
        async for item in client.send_message(SendMessageRequest(message=message)):
            if item.HasField("message"):
                return get_message_text(item.message)
    return ""


async def ask_mcp(base_url: str, prompt: str, session_id: str, token: str = TOKEN) -> str:
    """One MCP tool call to the agent's tool; `session_id` is the session."""
    async with Client(f"{base_url}/mcp/", timeout=60, auth=token) as client:
        result = await client.call_tool(AGENT, {"prompt": prompt, "session_id": session_id})
    if result.data is not None:  # a structured reply
        return str(result.data)
    return "".join(getattr(block, "text", "") for block in result.content)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def stack():
    """The deployed stack: the chat route's URL, and the base every A2A and MCP URL hangs from."""
    endpoint = os.getenv("AK_TEST_ENDPOINT")
    assert endpoint, "Set AK_TEST_ENDPOINT to the deployment's agent_invoke_url"
    assert TOKEN, "Set AK_TEST_TOKEN to the demo_auth_token the stack was deployed with"
    yield {"chat": endpoint, "base": endpoint.removesuffix("/chat")}


# ---- chat still works beside A2A and MCP ----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_the_chat_route_still_works(stack):
    response = await request(
        "POST",
        stack["chat"],
        TOKEN,
        {"prompt": "Reply with the word ready.", "session_id": str(uuid.uuid4()), "agent": AGENT},
    )
    show("chat with a token", response)

    assert response.status_code == 200
    assert "ready" in response.json().get("result", "").lower()


# ---- the calls that work, and keep the session ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_two_a2a_messages_on_one_session_share_the_agents_memory(stack):
    context_id = f"a2a-{uuid.uuid4()}"

    first = await retrying(
        lambda: ask_a2a(stack["base"], "Remember this code word: teal. Reply with OK only.", context_id)
    )
    second = await retrying(
        lambda: ask_a2a(stack["base"], "What is the code word I told you? Reply with the word only.", context_id)
    )
    print(f"\n[a2a message:send x2, one session] -> {first!r} then {second!r}")

    assert first
    assert "teal" in second.lower()


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_two_mcp_tool_calls_on_one_session_share_the_agents_memory(stack):
    session_id = f"mcp-{uuid.uuid4()}"

    first = await retrying(
        lambda: ask_mcp(stack["base"], "Remember this code word: amber. Reply with OK only.", session_id)
    )
    second = await retrying(
        lambda: ask_mcp(stack["base"], "What is the code word I told you? Reply with the word only.", session_id)
    )
    print(f"\n[mcp tools/call x2, one session] -> {first!r} then {second!r}")

    assert first
    assert "amber" in second.lower()


# ---- A2A: public card and catalog, everything else behind the authorizer --------------------------------------------


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_the_agent_card_needs_no_token_and_advertises_the_public_url(stack):
    response = await request(
        "GET", f"{stack['base']}/a2a/{AGENT}/.well-known/agent-card.json", token=None, headers=A2A_HEADERS
    )
    show("a2a agent card, no token", response)

    assert response.status_code == 200
    card = response.json()
    assert card["name"] == AGENT
    # a2a.url reached the request handler: the card names the API's public URL, stage and base path included.
    assert card["supportedInterfaces"][0]["url"] == f"{stack['base']}/a2a/{AGENT}"


@pytest.mark.asyncio
@pytest.mark.order(5)
async def test_the_catalog_needs_no_token(stack):
    response = await request("GET", f"{stack['base']}/a2a/catalog", token=None, headers=A2A_HEADERS)
    show("a2a catalog, no token", response)

    assert response.status_code == 200
    assert AGENT in response.text


A2A_SEND = {
    "message": {"messageId": "m-1", "contextId": "ctx-refused", "role": "ROLE_USER", "parts": [{"text": "hello"}]}
}


@pytest.mark.asyncio
@pytest.mark.order(6)
async def test_an_a2a_message_with_no_token_is_refused_by_the_authorizer(stack):
    """The app would run it as the anonymous principal: the authorizer is what keeps the caller away from the agent."""
    response = await request(
        "POST", f"{stack['base']}/a2a/{AGENT}/message:send", token=None, json=A2A_SEND, headers=A2A_HEADERS
    )
    show("a2a message:send, no token", response)

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.order(7)
async def test_an_a2a_message_with_a_wrong_token_is_refused_by_the_authorizer(stack):
    response = await request(
        "POST", f"{stack['base']}/a2a/{AGENT}/message:send", token="not-the-token", json=A2A_SEND, headers=A2A_HEADERS
    )
    show("a2a message:send, wrong token", response)

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.order(8)
async def test_an_a2a_task_route_with_no_token_is_refused_by_the_authorizer(stack):
    """Only the card and the catalog are public: every other A2A route needs a token."""
    response = await request("GET", f"{stack['base']}/a2a/{AGENT}/tasks", token=None, headers=A2A_HEADERS)
    show("a2a GET tasks, no token", response)

    assert response.status_code in (401, 403)


# ---- MCP: bypasses the authorizer, FastMCP authenticates ------------------------------------------------------------

MCP_LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


@pytest.mark.asyncio
@pytest.mark.order(9)
async def test_mcp_with_no_token_gets_fastmcps_own_401(stack):
    """/mcp bypasses the authorizer, so this 401 comes from FastMCP in the request handler, not from the gateway."""
    response = await request("POST", f"{stack['base']}/mcp/", token=None, json=MCP_LIST_TOOLS, headers=MCP_HEADERS)
    show("mcp tools/list, no token", response)

    assert response.status_code == 401
    assert not any(refusal in response.text for refusal in GATEWAY_REFUSALS)


@pytest.mark.asyncio
@pytest.mark.order(10)
async def test_mcp_with_a_wrong_token_gets_fastmcps_own_401(stack):
    response = await request(
        "POST", f"{stack['base']}/mcp/", token="not-the-token", json=MCP_LIST_TOOLS, headers=MCP_HEADERS
    )
    show("mcp tools/list, wrong token", response)

    assert response.status_code == 401
    assert not any(refusal in response.text for refusal in GATEWAY_REFUSALS)


@pytest.mark.asyncio
@pytest.mark.order(11)
async def test_mcp_with_a_valid_token_lists_the_agent_as_a_tool(stack):
    response = await request("POST", f"{stack['base']}/mcp/", token=TOKEN, json=MCP_LIST_TOOLS, headers=MCP_HEADERS)
    show("mcp tools/list, valid token", response)

    assert response.status_code == 200
    assert AGENT in response.text


@pytest.mark.asyncio
@pytest.mark.order(12)
async def test_an_mcp_get_for_server_push_is_a_405(stack):
    """Stateless MCP has no server push: the app answers a GET with 405 by itself."""
    response = await request("GET", f"{stack['base']}/mcp/", token=TOKEN, headers={"Accept": "text/event-stream"})
    show("mcp GET, valid token", response)

    assert response.status_code == 405
