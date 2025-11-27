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

    async def send(self, prompt, endpoint: str = "/run", additional_context=None, body=None):
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
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.url}{endpoint}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


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
    print("test_support_agent")
    response = await http_client.send("I am Andy Dufresne. I did some deposits.")
    Test.compare(
        response,
        " Hello Andy! I noticed that you made a mobile check deposit of $250. "
        "Could you tell me how satisfied you were with the mobile check deposit process?",
        threshold=10,
    )

    response = await http_client.send("I was extremely happy")
    Test.compare(
        response, "That's great to hear! What specifically made the experience enjoyable for you?", threshold=10
    )

    response = await http_client.send(prompt="", endpoint="/custom/deposit", body={"amount": 200})
    Test.compare(response, "Deposited $200 over the counter")

    # Prehook RAG example
    response = await http_client.send(
        "In which movie my bank agent's name appeared in? Just give me the name of the movie",
        additional_context={"bank_agent": "Ellis Boyd Red Redding"},
    )
    Test.compare(response, " the movie 'The Shawshank Redemption'.", threshold=20)
