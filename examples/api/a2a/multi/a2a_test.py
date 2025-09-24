# test_app.py
import asyncio
import subprocess
import sys

import pytest
import pytest_asyncio
from ak.test import Test

from client import A2AHttpClient


@pytest_asyncio.fixture(scope="session")
async def a2a_client():
    """Start the FastAPI server as a subprocess and stop it after tests."""
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
    test = Test("server.py")

    response = await a2a_client.send("Who won the 1996 cricket world cup?")
    test.compare(response, "Sri Lanka won the 1996 cricket world cup.")

    response = await a2a_client.send("Which countries hosted the tournament?")
    test.compare(response, "The 1996 Cricket World Cup was hosted by India, Pakistan, and Sri Lanka.")
