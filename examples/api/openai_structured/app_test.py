import asyncio
import json
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt):
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "contact",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
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
        yield APITestClient("http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_structured_reply(http_client):
    result = await http_client.send("John Doe can be reached at John.Doe@example.com or on 077-1234567")
    data = json.loads(result)
    assert data["name"] == "John Doe"
    # The post-hook normalizes the email in the structured reply content
    assert data["email"] == "john.doe@example.com"
    assert data["phone"] == "077-1234567"


@pytest.mark.asyncio
async def test_missing_fields_are_null(http_client):
    result = await http_client.send("You can write to Jane Smith at JANE@example.com")
    data = json.loads(result)
    assert data["name"] == "Jane Smith"
    assert data["email"] == "jane@example.com"
    assert data["phone"] is None
