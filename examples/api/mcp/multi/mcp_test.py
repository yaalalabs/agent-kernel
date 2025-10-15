import asyncio
import subprocess
import sys

import pytest
import pytest_asyncio
from agentkernel.test import Test

from client import MCPHttpClient


@pytest_asyncio.fixture(scope="session")
async def mcp_client():
    proc = subprocess.Popen(
        ["python3", "server.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(10)
    client = MCPHttpClient(server_url="http://127.0.0.1:8000/mcp")
    await client.init()
    try:
        yield client
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_call_api(mcp_client: MCPHttpClient):
    response = await mcp_client.send("Who won the 1996 cricket world cup?")
    Test.compare(response, "Sri Lanka won the 1996 cricket world cup.")

    response = await mcp_client.send("Which countries hosted the tournament?")
    Test.compare(response, "The 1996 Cricket World Cup was hosted by India, Pakistan, and Sri Lanka.")

    response = await mcp_client.send("What protocols are supported by Agent Kernel?", tool="agent_kernel_knowledge")
    Test.compare(response, "Agent Kernel supports both MCP and A2A")
