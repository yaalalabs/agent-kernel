import asyncio
import subprocess
import sys

import pytest
import pytest_asyncio
from agentkernel.test import Test

from client import A2AHttpClient


@pytest_asyncio.fixture(scope="session")
async def a2a_client():
    proc = subprocess.Popen(
        ["python3", "server.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(15)
    client = A2AHttpClient(base_url="http://127.0.0.1:8000/a2a/history")
    await client.init()
    try:
        yield client
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_call_api(a2a_client):
    response = await a2a_client.send("Who won the 1996 cricket world cup?, answer with only the country name")
    Test.compare(response, ["Sri Lanka"])

    response = await a2a_client.send(
        "Which country hosted the tournament?, answer with only the country names and make sure to mention all the contries that hosted this tournament"
    )
    Test.compare(response, ["Sri Lanka, India and Pakistan"])
