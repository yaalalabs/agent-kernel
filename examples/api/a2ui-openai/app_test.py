import asyncio
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
            "agent": "expenses",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            return resp.json()


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
async def test_a_ui_turn_arrives_as_an_object(http_client):
    """`result` is the A2UI document itself — no second json.loads, and the label says what it is."""
    body = await http_client.send("I need to file an expense")

    assert body["media_type"] == "application/a2ui+json"
    assert isinstance(body["result"], dict)

    surface = body["result"]["createSurface"]
    assert any(component["id"] == "root" for component in surface["components"])


@pytest.mark.asyncio
async def test_a_prose_turn_is_untouched(http_client):
    """Most turns look like this. Prose does not parse as JSON, so it is never labelled."""
    body = await http_client.send("hi")

    assert "media_type" not in body
    assert isinstance(body["result"], str)
