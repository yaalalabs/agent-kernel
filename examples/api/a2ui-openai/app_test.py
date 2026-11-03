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
        self.user_id = "demo-user"
        self.token = "demo-token"  # the thread read routes are behind app.py's DemoAuthoriser

    async def send(self, prompt, session_id=None):
        payload = {
            "prompt": prompt,
            "session_id": session_id or self.session_id,
            "user_id": self.user_id,
            "agent": "expenses",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def thread(self, session_id):
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.url}/api/v1/threads/{session_id}",
                headers={"Authorization": f"Bearer {self.token}"},
            )
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


GREETINGS = ("hi", "thanks", "good morning")


async def an_unlabelled_turn(client):
    """Send greetings until one comes back without a label, and return its (session_id, body).

    The agent chooses between prose and a surface, and a greeting sometimes comes back as a Card
    of Text — the prompt in app.py argues against it but cannot forbid it. Selecting the turn here
    keeps the assertions below exact instead of widening them to accept either shape: what they
    pin is the recording path, not the model's taste.
    """
    for greeting in GREETINGS:
        session_id = str(uuid.uuid4())
        body = await client.send(greeting, session_id=session_id)
        if "media_type" not in body:
            return session_id, body
    pytest.fail(f"every greeting in {GREETINGS} came back as a surface — check the prose rule in app.py's CATALOG")


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
    """Most turns look like this. Prose does not parse as JSON, so an unlabelled reply stays a string."""
    _, body = await an_unlabelled_turn(http_client)

    assert isinstance(body["result"], str)


@pytest.mark.asyncio
async def test_a_ui_turn_replays_from_thread_history(http_client):
    """Reload is the claim worth testing: what rendered as a form must come back as one.

    The recorded message carries the same pair the live reply did — the payload as an object, and
    the label beside it — so the frontend replays history through the renderer it already has
    instead of parsing a string back into a document.
    """
    session_id = str(uuid.uuid4())
    live = await http_client.send("I need to file an expense", session_id=session_id)
    assert live["media_type"] == "application/a2ui+json"

    messages = (await http_client.thread(session_id))["messages"]
    recorded = [m for m in messages if m["role"] == "assistant"][-1]

    assert recorded["media_type"] == "application/a2ui+json"
    assert recorded["content"] == live["result"]


@pytest.mark.asyncio
async def test_a_prose_turn_replays_as_a_plain_string(http_client):
    """The other half: an unlabelled reply is recorded with no label at all, not a null one.

    This is what an application that never turned A2UI on reads back, and it has to be exactly
    what it read back before the feature existed.
    """
    session_id, live = await an_unlabelled_turn(http_client)

    messages = (await http_client.thread(session_id))["messages"]
    recorded = [m for m in messages if m["role"] == "assistant"][-1]

    assert isinstance(recorded["content"], str)
    assert recorded["content"] == live["result"]
    assert "media_type" not in recorded
