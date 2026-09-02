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

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

TEST_IMAGE_PATH = Path(__file__).parent / "test_image.webp"
ALICE_TOKEN = "alice-token"


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def chat(self, prompt, user_id="alice", images=None):
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "general",
            "user_id": user_id,
        }
        if images:
            payload["images"] = images
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            return resp.json().get("result", "")

    async def get(self, path, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.get(f"{self.url}{path}", headers=headers)


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

    response = await app_client.chat(
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
        threshold=0.8,
    )


@pytest.mark.order(2)
async def test_thread_stores_attachment_reference(app_client):
    resp = await app_client.get(f"/api/v1/threads/{app_client.session_id}", token=ALICE_TOKEN)
    assert resp.status_code == 200
    thread = resp.json()
    assert thread["user_id"] == "alice"

    messages = thread["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    user_message = messages[0]
    assert user_message["content"] == "What animal is this? Reply with exactly animal name and nothing else"

    attachments = user_message["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["attachment_id"]
    assert attachments[0]["mime_type"] == "image/webp"

    # The thread holds only an attachment reference — never the image bytes.
    with open(TEST_IMAGE_PATH, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")
    assert b64_data[:100] not in resp.text


@pytest.mark.order(3)
async def test_followup_retrieval_and_thread_history(app_client):
    response = await app_client.chat(
        prompt="Please analyze the image again. Does the animal in the image have tusks? Reply with only 'Yes' or 'No'.",
    )
    print(f"Agent response: {response}")

    Test.compare(
        actual=response,
        expected=["Yes", "yes", "Yes, it does", "Yes, the elephant has tusks"],
        threshold=0.8,
    )

    resp = await app_client.get(f"/api/v1/threads/{app_client.session_id}", token=ALICE_TOKEN)
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]


@pytest.mark.order(4)
async def test_thread_routes_require_token(app_client):
    resp = await app_client.get(f"/api/v1/threads/{app_client.session_id}")
    assert resp.status_code == 401  # missing Authorization header
