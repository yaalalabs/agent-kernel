import asyncio
import os
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

# The credential values of the two principals in config.yaml. The static provider resolves them
# through the environment, so app.py is started with these exact values below.
ALICE_TOKEN = "alice-token"
BOB_TOKEN = "bob-token"


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def chat(self, prompt, session_id, token=ALICE_TOKEN, thread_name=None, **extra):
        payload = {"prompt": prompt, "session_id": session_id, "agent": "assistant", **extra}
        if thread_name is not None:
            payload["thread_name"] = thread_name
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(f"{self.url}/api/v1/chat", json=payload, headers=self._headers(token))

    async def get(self, path, token=None):
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.get(f"{self.url}{path}", headers=self._headers(token))

    @staticmethod
    def _headers(token):
        return {"Authorization": f"Bearer {token}"} if token is not None else {}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    proc = subprocess.Popen(
        ["python3", "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
        env={**os.environ, "ALICE_TOKEN": ALICE_TOKEN, "BOB_TOKEN": BOB_TOKEN},
    )
    await asyncio.sleep(5)
    try:
        yield APITestClient(f"http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_chat_requires_a_credential(http_client):
    print("test_chat_requires_a_credential")
    # The thread handler serves authenticated callers only: a thread belongs to someone.
    resp = await http_client.chat("What is the capital of France?", session_id=str(uuid.uuid4()), token=None)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Authentication required"


@pytest.mark.asyncio
async def test_the_acting_user_comes_from_the_credential_not_the_body(http_client):
    print("test_the_acting_user_comes_from_the_credential_not_the_body")
    resp = await http_client.chat("What is the capital of France?", session_id=str(uuid.uuid4()), user_id="alice")
    assert resp.status_code == 400
    assert "user_id" in resp.json()["detail"]["error"]


@pytest.mark.asyncio
async def test_thread_lifecycle(http_client):
    print("test_thread_lifecycle")
    session_id = str(uuid.uuid4())

    resp = await http_client.chat("What is the capital of France?", session_id=session_id, thread_name="Capitals quiz")
    assert resp.status_code == 200
    assert resp.json()["result"]

    resp = await http_client.chat("And of Italy?", session_id=session_id)
    assert resp.status_code == 200

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token=ALICE_TOKEN)
    assert resp.status_code == 200
    thread = resp.json()
    assert thread["session_id"] == session_id
    assert thread["user_id"] == "alice"  # the owner is the principal the token authenticated
    assert thread["name"] == "Capitals quiz"
    messages = thread["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "What is the capital of France?"
    assert messages[2]["content"] == "And of Italy?"


@pytest.mark.asyncio
async def test_thread_listing_is_the_callers_own(http_client):
    print("test_thread_listing_is_the_callers_own")
    alice_session = str(uuid.uuid4())
    bob_session = str(uuid.uuid4())
    assert (await http_client.chat("Hello from Alice", session_id=alice_session)).status_code == 200
    assert (await http_client.chat("Hello from Bob", session_id=bob_session, token=BOB_TOKEN)).status_code == 200

    resp = await http_client.get("/api/v1/threads", token=ALICE_TOKEN)
    assert resp.status_code == 200
    threads = resp.json()["threads"]
    session_ids = [t["session_id"] for t in threads]
    assert alice_session in session_ids
    assert bob_session not in session_ids  # a listing is always the caller's own
    assert all(t["user_id"] == "alice" for t in threads)
    assert all("messages" not in t for t in threads)  # listing returns metadata only


@pytest.mark.asyncio
async def test_thread_route_authentication_and_ownership(http_client):
    print("test_thread_route_authentication_and_ownership")
    session_id = str(uuid.uuid4())
    assert (await http_client.chat("Hello", session_id=session_id)).status_code == 200

    resp = await http_client.get(f"/api/v1/threads/{session_id}")
    assert resp.status_code == 401  # no credential: the thread routes serve authenticated callers only

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token="wrong-token")
    assert resp.status_code == 401  # the identity provider refused the token

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token=BOB_TOKEN)
    assert resp.status_code == 403  # a valid token, but bob does not own alice's thread

    resp = await http_client.chat("Hello again", session_id=session_id, token=BOB_TOKEN)
    assert resp.status_code == 403  # nor can bob continue it


@pytest.mark.asyncio
async def test_thread_auto_naming(http_client):
    print("test_thread_auto_naming")
    session_id = str(uuid.uuid4())
    prompt = "Suggest a name for my cat"
    assert (await http_client.chat(prompt, session_id=session_id)).status_code == 200

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token=ALICE_TOKEN)
    assert resp.status_code == 200
    thread = resp.json()
    # No thread_name given: the default LLM strategy derives a concise title from the first prompt
    assert thread["name"]
    assert len(thread["name"]) <= 81  # max_length (80) + ellipsis
    assert thread["name_locked"] is False


@pytest.mark.asyncio
async def test_thread_auto_naming_gibberish_prompt(http_client):
    print("test_thread_auto_naming_gibberish_prompt")
    session_id = str(uuid.uuid4())
    gibberish = "asdkjfh qwelrkj zxcmvn 12093"
    assert (await http_client.chat(gibberish, session_id=session_id)).status_code == 200

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token=ALICE_TOKEN)
    assert resp.status_code == 200
    thread = resp.json()
    assert thread["name"]
    assert thread["name"] != gibberish  # the raw gibberish never becomes the thread name


@pytest.mark.asyncio
async def test_thread_rename_via_chat(http_client):
    print("test_thread_rename_via_chat")
    session_id = str(uuid.uuid4())
    assert (await http_client.chat("Hello", session_id=session_id)).status_code == 200

    # A later chat request carrying thread_name renames the existing thread
    resp = await http_client.chat("Hello again", session_id=session_id, thread_name="My renamed thread")
    assert resp.status_code == 200

    resp = await http_client.get(f"/api/v1/threads/{session_id}", token=ALICE_TOKEN)
    thread = resp.json()
    assert thread["name"] == "My renamed thread"
    assert thread["name_locked"] is True  # renamed threads opt out of automatic naming
