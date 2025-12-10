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

    # Test additional_context parameter passed through prehook for RAG
    response = await http_client.send(
        "In which movie my bank agent's name appeared in? Just give me the name of the movie",
        additional_context={"bank_agent": "Ellis Boyd Red Redding"},
    )
    Test.compare(response, " the movie 'The Shawshank Redemption'.", threshold=20)

@pytest.mark.asyncio
async def test_image_support(http_client):
    print("test_image_support")
    body={
        "session_id": http_client.session_id,
        "prompt": "can you describe this image?",
        "images": [{
            "name": "scenary",
            "mime_type": "image/jpeg",
            "image_data": "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"
        }
        ]
        }
    response = await http_client.send("",body=body)
    Test.compare(response, "This image shows a group of illustrated people in grayscale. They are standing together and differ in hairstyle and facial features. It's a stylized representation without distinct identities.")