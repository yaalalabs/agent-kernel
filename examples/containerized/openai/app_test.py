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
        ["Hello Andy! I see you made a deposit of $250."],
        threshold=0.1,
        criteria=(
            "The reply must greet Andy and mention the $250 deposit. "
            "Any wording of the deposit or follow-up question about it is acceptable and must not be penalized."
        ),
    )

    response = await http_client.send("I was extremely happy")
    Test.compare(
        response,
        ["That's great to hear!"],
        threshold=0.1,
        criteria=(
            "The reply must warmly acknowledge that the customer was happy. "
            "Any follow-up question about their experience is acceptable and must not be penalized."
        ),
    )
