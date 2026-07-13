import asyncio
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

ALICE_TOKEN = "alice-token"
BOB_TOKEN = "bob-token"


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def chat(self, prompt, session_id, user_id=None, thread_name=None):
        payload = {"prompt": prompt, "session_id": session_id, "agent": "assistant"}
        if user_id is not None:
            payload["user_id"] = user_id
        if thread_name is not None:
            payload["thread_name"] = thread_name
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(f"{self.url}/api/v1/chat", json=payload)

    async def get(self, path, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.get(f"{self.url}{path}", headers=headers)


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
async def test_user_id_required(http_client):
    print("test_user_id_required")
    resp = await http_client.chat("What is the capital of France?", session_id=str(uuid.uuid4()))
    assert resp.status_code == 400
    assert "user_id" in resp.json()["detail"]["error"]


@pytest.mark.asyncio
async def test_thread_lifecycle(http_client):
    print("test_thread_lifecycle")
    session_id = str(uuid.uuid4())

    resp = await http_client.chat(
        "What is the capital of France?", session_id=session_id, user_id="alice", thread_name="Capitals quiz"
    )
    assert resp.status_code == 200
    assert resp.json()["result"]

    resp = await http_client.chat("And of Italy?", session_id=session_id, user_id="alice")
    assert resp.status_code == 200

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token=ALICE_TOKEN)
    assert resp.status_code == 200
    thread = resp.json()
    assert thread["session_id"] == session_id
    assert thread["user_id"] == "alice"
    assert thread["name"] == "Capitals quiz"
    messages = thread["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "What is the capital of France?"
    assert messages[2]["content"] == "And of Italy?"


@pytest.mark.asyncio
async def test_thread_listing_scoped_to_authorised_user(http_client):
    print("test_thread_listing_scoped_to_authorised_user")
    alice_session = str(uuid.uuid4())
    bob_session = str(uuid.uuid4())
    assert (await http_client.chat("Hello from Alice", session_id=alice_session, user_id="alice")).status_code == 200
    assert (await http_client.chat("Hello from Bob", session_id=bob_session, user_id="bob")).status_code == 200

    resp = await http_client.get("/api/v1/threads", token=ALICE_TOKEN)
    assert resp.status_code == 200
    threads = resp.json()["threads"]
    session_ids = [t["session_id"] for t in threads]
    assert alice_session in session_ids
    assert bob_session not in session_ids  # listing is forced to the authorised user
    assert all(t["user_id"] == "alice" for t in threads)
    assert all("messages" not in t for t in threads)  # listing returns metadata only


@pytest.mark.asyncio
async def test_thread_route_authorisation(http_client):
    print("test_thread_route_authorisation")
    session_id = str(uuid.uuid4())
    assert (await http_client.chat("Hello", session_id=session_id, user_id="alice")).status_code == 200

    resp = await http_client.get(f"/api/v1/threads/{session_id}")
    assert resp.status_code == 401  # missing Authorization header

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token="wrong-token")
    assert resp.status_code == 401  # token rejected by the Authoriser

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token=BOB_TOKEN)
    assert resp.status_code == 403  # valid token, but bob does not own alice's thread


@pytest.mark.asyncio
async def test_thread_auto_naming(http_client):
    print("test_thread_auto_naming")
    session_id = str(uuid.uuid4())
    prompt = "Suggest a name for my cat"
    assert (await http_client.chat(prompt, session_id=session_id, user_id="alice")).status_code == 200

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token=ALICE_TOKEN)
    assert resp.status_code == 200
    assert resp.json()["name"] == prompt  # no thread_name given — derived from the first prompt
