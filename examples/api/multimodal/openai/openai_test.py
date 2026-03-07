import asyncio
import base64
import os
import subprocess
import sys
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

    async def send(self, prompt, images=None, files=None):
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "general",
        }
        if images:
            payload["images"] = images
        if files:
            payload["files"] = files

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def app_client():
    env = os.environ.copy()

    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=env,
        cwd=str(Path(__file__).parent),
    )
    await asyncio.sleep(2)
    for _ in range(20):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://localhost:8000/health")
                if resp.status_code == 200:
                    break
        except (httpx.ConnectError, httpx.ConnectTimeout):
            pass
        await asyncio.sleep(0.5)
    else:
        raise RuntimeError("Server did not start within 12 seconds")

    try:
        yield APITestClient("http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.order(1)
async def test_image_description(app_client):
    with open(TEST_IMAGE_PATH, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    response = await app_client.send(
        prompt="What animal is this? Reply with exactly animal name and nothing else",
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
async def test_followup_retrieval(app_client):
    response = await app_client.send(
        prompt="Please analyze the image again. Does the animal in the image have tusks? Reply with only 'Yes' or 'No'.",
    )
    print(f"Agent response: {response}")

    Test.compare(
        actual=response,
        expected=["Yes", "yes", "Yes, it does", "Yes, the elephant has tusks"],
        threshold=80,
    )
