"""End-to-end tests for the sandbox identity demo.

Each request carries an auth token; the app authenticates it, runs sandboxed code under the
caller's identity, and the demo provider exposes that identity as SANDBOX_PRINCIPAL. The
tests assert that the same code observably runs as different users, and that an
unauthenticated request is rejected — the whole application path, not any internals.
"""

import asyncio
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

PRINT_PRINCIPAL = (
    "Run Python code that prints the value of the SANDBOX_PRINCIPAL environment variable, then tell me only that value."
)


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def send(self, prompt, auth_token=None, session_id=None):
        payload = {
            "prompt": prompt,
            "session_id": session_id or str(uuid.uuid4()),
            "agent": "coder",
        }
        if auth_token is not None:
            payload["auth_token"] = auth_token  # extra field -> AgentRequestAny the pre-hook reads
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            return resp.json().get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    proc = subprocess.Popen(["python3", "app.py"], stdout=sys.stdout, stderr=sys.stderr)
    await asyncio.sleep(5)  # wait for the server to start
    try:
        yield APITestClient("http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.order(1)
async def test_code_runs_under_authenticated_user(http_client):
    response = await http_client.send(PRINT_PRINCIPAL, auth_token="token-alice")
    assert "alice@example.com" in response, f"Expected code to run as alice, got: {response}"


@pytest.mark.order(2)
async def test_different_user_runs_under_their_own_identity(http_client):
    response = await http_client.send(PRINT_PRINCIPAL, auth_token="token-bob")
    assert "bob@example.com" in response, f"Expected code to run as bob, got: {response}"


@pytest.mark.order(3)
async def test_missing_token_is_rejected(http_client):
    response = await http_client.send(PRINT_PRINCIPAL, auth_token=None)
    assert "unauthorized" in response.lower(), f"Expected an unauthorized rejection, got: {response}"


@pytest.mark.order(4)
async def test_invalid_token_is_rejected(http_client):
    response = await http_client.send(PRINT_PRINCIPAL, auth_token="token-nope")
    assert "unauthorized" in response.lower(), f"Expected an unauthorized rejection, got: {response}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
