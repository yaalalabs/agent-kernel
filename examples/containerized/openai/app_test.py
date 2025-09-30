import asyncio
import os
import shutil
import subprocess
import sys

import pytest
import pytest_asyncio
from ak.test import Test


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def send(self, prompt):
        pass


@pytest_asyncio.fixture(scope="session")
async def http_client():
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed or not in PATH")

    api_key = os.environ.get("OPENAI_API_KEY")
    test_port = 8000
    image = "yaalalabs/ak-openai-demo:latest"
    if not api_key:
        pytest.skip("OPENAI_API_KEY is not set; skipping integration test")

    cmd = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"OPENAI_API_KEY={api_key}",
        "-p",
        f"{test_port}:8000",
        image,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(15)

    try:
        yield APITestClient(f"http://localhost:{test_port}")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_call_api(http_client):
    response = await http_client.send("Who won the 1996 cricket world cup?")
    Test.compare(response, "Sri Lanka won the 1996 cricket world cup.")

    response = await http_client.send("Which countries hosted the tournament?")
    Test.compare(response, "The 1996 Cricket World Cup was hosted by India, Pakistan, and Sri Lanka.")
