import asyncio
import os
import subprocess
import sys

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def send(self, endpoint: str, method: str = "post", body=None, params=None):
        payload = {} if body is None else body
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, f"{self.url}{endpoint}", json=payload, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    my_env = os.environ.copy()
    # Mocking LiveKit credentials for the server to start
    my_env["AK_LIVEKIT__API_KEY"] = "test_key"
    my_env["AK_LIVEKIT__API_SECRET"] = "test_secret"
    my_env["AK_LIVEKIT__URL"] = "wss://test.livekit.cloud"

    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=my_env,
    )
    await asyncio.sleep(5)
    try:
        yield APITestClient(f"http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_health(http_client):
    response = await http_client.send("/health", method="get")
    assert response == {"status": "ok"}


@pytest.mark.asyncio
async def test_livekit_token(http_client):
    # Test the token generation endpoint
    params = {"room": "test-room", "identity": "test-user"}
    response = await http_client.send("/livekit/token", method="get", params=params)

    assert "token" in response
    assert isinstance(response["token"], str)
