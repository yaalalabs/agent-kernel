import asyncio
import os
import shutil
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt):
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "support",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


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
    await asyncio.sleep(10)

    try:
        yield APITestClient(f"http://localhost:{test_port}")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_support_agent(http_client):
    response = await http_client.send("I am Andy Dufresne. I did some deposits.")
    Test.compare(
        response,
        [
            " Hello Andy! I noticed that you made a mobile check deposit of $250. Could you tell me how satisfied you were with the mobile check deposit process?"
        ],
        threshold=10,
    )

    response = await http_client.send("I was extremely happy")
    Test.compare(
        response, ["That's great to hear! What did you like most about the mobile check deposit process?"], threshold=10
    )
