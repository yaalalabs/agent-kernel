"""Minimal A2A and MCP client for the README's walkthrough and the chart's kind smoke.

Sends one A2A message:send and one MCP tool call to the triage agent through the io handler and
prints both replies. Each one is enqueued like a REST chat request, run on the agent runner, and
read back from the response store. Exits non-zero when either reply is empty or an error.

    uv run python protocol_client.py [http://localhost:8000]
"""

import asyncio
import sys
import uuid

import httpx
from a2a.client import A2ACardResolver, ClientConfig
from a2a.client.base_client import BaseClient
from a2a.client.transports.rest import RestTransport
from a2a.helpers import get_message_text
from a2a.types import Message, Part, Role, SendMessageRequest
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, VERSION_HEADER
from fastmcp import Client

AGENT = "triage"
PROMPT = "What is 17 * 23? Answer with the number only."


async def ask_a2a(base_url: str) -> str:
    agent_url = f"{base_url}/a2a/{AGENT}"
    # A 1.x server reads a request without the A2A-Version header as 0.3 and refuses it. The SDK's
    # ClientFactory sets the header; this hand-built client sets it itself.
    async with httpx.AsyncClient(timeout=120, headers={VERSION_HEADER: PROTOCOL_VERSION_CURRENT}) as http:
        card = await A2ACardResolver(http, base_url=agent_url).get_agent_card()
        # The explicit url overrides the card's (a2a.url), so a port-forward on any port works.
        transport = RestTransport(http, card, url=agent_url)
        client = BaseClient(card, ClientConfig(streaming=False), transport, interceptors=[])
        message = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text=PROMPT)])
        async for item in client.send_message(SendMessageRequest(message=message)):
            if item.HasField("message"):
                return get_message_text(item.message)
    return ""


async def ask_mcp(base_url: str) -> str:
    async with Client(f"{base_url}/mcp/", timeout=120) as client:
        result = await client.call_tool(AGENT, {"prompt": PROMPT, "session_id": f"mcp-{uuid.uuid4()}"})
    if result.data is not None:  # a structured reply
        return str(result.data)
    return "".join(getattr(block, "text", "") for block in result.content)


async def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
    failed = False
    for name, ask in (("A2A", ask_a2a), ("MCP", ask_mcp)):
        try:
            reply = await ask(base_url)
        except Exception as e:
            reply = f"Error: {type(e).__name__}: {e}"
        print(f"{name}: {reply}")
        # A model failure comes back as a normal reply starting with "Error".
        failed = failed or not reply or reply.startswith("Error")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
