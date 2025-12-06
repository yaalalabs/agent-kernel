import asyncio
import os
import subprocess
import sys

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def send(self, endpoint: str, method: str = "post", body=None):
        payload = {} if body is None else body
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, f"{self.url}{endpoint}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    my_env = os.environ.copy()
    my_env["AK_GMAIL__CREDENTIALS_FILE"] = "credentials.json"
    my_env["AK_GMAIL__TOKEN_FILE"] = "token.pickle"
    my_env["AK_GMAIL__POLL_INTERVAL"] = "60"
    proc = subprocess.Popen(
        ["python3", "server.py"],
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
async def test_gmail_health(http_client):
    """Test health endpoint."""
    print("test_gmail_health")
    response = await http_client.send("/health", method="get")
    assert response == {"status": "ok"}
