import asyncio
import logging
import os
import subprocess
import sys

import pytest
import pytest_asyncio
from agentkernel.test import Test

from client import MCPHttpClient

log = logging.getLogger("ak.awscontainerized.mcptest")


@pytest_asyncio.fixture(scope="session")
async def mcp_client():
    proc = subprocess.Popen(
        ["python3", "server.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(10)
    test_endpnt = os.getenv("AK_TEST_ENDPOINT")
    log.info(f"Test endpoint: {test_endpnt}")
    client = MCPHttpClient(server_url=test_endpnt)
    await client.init()
    try:
        yield client
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_call_api(mcp_client: MCPHttpClient):
    response = await mcp_client.send("Who won the 1996 cricket world cup?")
    Test.compare(response, ["Sri Lanka won the 1996 cricket world cup."])

    response = await mcp_client.send("Which countries hosted the tournament?")
    Test.compare(response, ["The 1996 Cricket World Cup was hosted by India, Pakistan, and Sri Lanka."])

    response = await mcp_client.send("What protocols are supported by Agent Kernel?", tool="agent_kernel_knowledge")
    Test.compare(response, ["Agent Kernel supports both MCP and A2A"])
