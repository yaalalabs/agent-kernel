import asyncio
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt, endpoint: str = "/api/v1/chat", additional_context=None, body=None):
        payload = (
            {
                "prompt": prompt,
                "session_id": self.session_id,
                "agent": "support",
                "additional_context": additional_context,
            }
            if body is None
            else body
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            result = ""
            for _ in range(3):
                resp = await client.post(f"{self.url}{endpoint}", json=payload)
                resp.raise_for_status()
                result = resp.json().get("result", "")
                if result:
                    break
            return result


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    proc = subprocess.Popen(
        ["python3", "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(5)
    try:
        yield APITestClient(f"http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_support_agent(http_client):
    response = await http_client.send("Hi, I am Bob.")
    Test.compare(
        response,
        ["Hello Bob! How can I help you today?"],
        threshold=0.1,
    )

    response = await http_client.send("What is my name?")
    Test.compare(response, ["Your name is Bob."], threshold=0.1)

    response = await http_client.send("What is the weather in Paris?")
    Test.compare(response, ["The weather in Paris is 72 degrees and sunny."], threshold=0.1)
