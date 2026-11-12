"""Tests for the deployed serverless thread example.

Set AK_TEST_ENDPOINT to the module's `agent_invoke_url` output (the chat route). The thread routes
are derived from it, since both live behind the same API Gateway stage. The demo tokens are the
static ones in lambda_auth.py.
"""

import os
import time
import uuid

import httpx
import pytest

ENDPOINT = os.getenv("AK_TEST_ENDPOINT", "").rstrip("/")
ALICE_TOKEN = "alice-token"
BOB_TOKEN = "bob-token"
GUEST_TOKEN = "guest-token"  # may chat, may not read threads (lambda_auth.py)

pytestmark = pytest.mark.skipif(not ENDPOINT, reason="Set AK_TEST_ENDPOINT to the deployment's agent_invoke_url")


def _threads_url() -> str:
    # /api/v1/chat -> /api/v1/threads
    return ENDPOINT.rsplit("/", 1)[0] + "/threads"


def _headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token is not None else {}


def _send(method: str, url: str, token: str | None, **kwargs) -> httpx.Response:
    # Retry a gateway timeout or 5xx: a cold start can exceed API Gateway's limit on the first call.
    response = None
    for _ in range(3):
        try:
            response = httpx.request(method, url, headers=_headers(token), timeout=60.0, **kwargs)
        except httpx.TimeoutException:
            continue
        if response.status_code < 500:
            return response
        time.sleep(5)
    assert response is not None, f"no response from {url}"
    return response


def _chat(prompt: str, session_id: str, user_id: str | None = "alice", token: str = ALICE_TOKEN) -> httpx.Response:
    payload = {"prompt": prompt, "session_id": session_id, "request_id": str(uuid.uuid4()), "agent": "assistant"}
    if user_id is not None:
        payload["user_id"] = user_id
    # One attempt, never retried: a retry re-records the user message in the thread.
    return httpx.request("POST", ENDPOINT, headers=_headers(token), json=payload, timeout=60.0)


def _wait_for_messages(session_id: str, count: int) -> None:
    """Poll the thread until it holds `count` messages: the agent runner records each reply."""
    for _ in range(30):
        thread = _send("GET", f"{_threads_url()}/{session_id}", ALICE_TOKEN)
        if thread.status_code == 200 and len(thread.json()["messages"]) >= count:
            return
        time.sleep(2)
    raise AssertionError(f"thread {session_id} did not reach {count} messages within 60s")


@pytest.fixture(scope="module")
def alice_thread() -> str:
    """Two chat turns by alice; returns the thread's session id once both replies are recorded."""
    session_id = f"thread-smoke-{uuid.uuid4()}"
    for turn, prompt in enumerate(("What is the capital of France?", "And of Italy?"), start=1):
        # The chat response is not checked: a cold start can outlast API Gateway's 29s limit (504)
        # while the run completes behind it. The thread is what this fixture builds.
        _chat(prompt, session_id)
        _wait_for_messages(session_id, 2 * turn)
    return session_id


def test_chat_without_user_id_is_rejected():
    response = _chat("hi", f"thread-smoke-{uuid.uuid4()}", user_id=None)

    assert response.status_code == 400, response.text
    assert "user_id" in response.json()["error"]


def test_the_thread_holds_both_turns_in_order(alice_thread):
    response = _send("GET", f"{_threads_url()}/{alice_thread}", ALICE_TOKEN)

    assert response.status_code == 200, response.text
    thread = response.json()
    assert thread["session_id"] == alice_thread
    assert thread["user_id"] == "alice"
    messages = thread["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "What is the capital of France?"
    assert messages[2]["content"] == "And of Italy?"
    assert "paris" in messages[1]["content"].lower()


def test_the_listing_holds_the_thread(alice_thread):
    response = _send("GET", _threads_url(), ALICE_TOKEN, params={"user_id": "alice"})

    assert response.status_code == 200, response.text
    assert alice_thread in [t["session_id"] for t in response.json()["threads"]]


def test_another_user_cannot_read_the_thread(alice_thread):
    assert _send("GET", f"{_threads_url()}/{alice_thread}", BOB_TOKEN).status_code == 403

    # The listing is forced to the authorized user, whatever user_id asks for.
    listing = _send("GET", _threads_url(), BOB_TOKEN, params={"user_id": "alice"})
    assert listing.status_code == 200, listing.text
    assert alice_thread not in [t["session_id"] for t in listing.json()["threads"]]


def test_the_read_routes_need_a_token():
    assert _send("GET", _threads_url(), None).status_code in (401, 403)


def test_a_guest_may_chat_but_not_read_threads():
    session_id = f"thread-smoke-{uuid.uuid4()}"
    assert _chat("hi", session_id, user_id="guest", token=GUEST_TOKEN).status_code == 200

    # The authorizer's route rule denies before any Lambda runs: API Gateway answers 403.
    assert _send("GET", _threads_url(), GUEST_TOKEN).status_code == 403
    assert _send("GET", f"{_threads_url()}/{session_id}", GUEST_TOKEN).status_code == 403


def test_a_non_integer_limit_is_rejected():
    assert _send("GET", _threads_url(), ALICE_TOKEN, params={"limit": "ten"}).status_code == 400
