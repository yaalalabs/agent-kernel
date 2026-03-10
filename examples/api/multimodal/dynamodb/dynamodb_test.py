import base64
import os
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")

TEST_IMAGE_PATH = Path(__file__).parent / "test_image.webp"


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt, images=None):
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "general",
        }
        if images:
            payload["images"] = images

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    endpoint = os.getenv("AK_TEST_ENDPOINT")
    yield APITestClient(endpoint)


@pytest.mark.order(1)
async def test_image_description(http_client):
    with open(TEST_IMAGE_PATH, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    response = await http_client.send(
        prompt="What animal is this? Reply with exactly animal name and nothing else.",
        images=[
            {
                "name": "elephant",
                "mime_type": "image/webp",
                "image_data": b64_data,
            }
        ],
    )
    print(f"Agent response: {response}")

    Test.compare(
        actual=response,
        expected=["Elephant", "elephant", "An elephant", "It's an elephant"],
        threshold=80,
    )


@pytest.mark.order(2)
async def test_followup_retrieval_from_dynamodb(http_client):
    response = await http_client.send(
        prompt="Please analyze the image again. Does the animal in the image have tusks? Reply with only 'Yes' or 'No'.",
    )
    print(f"Agent response: {response}")

    Test.compare(
        actual=response,
        expected=["Yes", "yes", "Yes, it does", "Yes, the elephant has tusks"],
        threshold=80,
    )
