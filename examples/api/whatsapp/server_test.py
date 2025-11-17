import asyncio
import os
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
    my_env["AK_WHATSAPP__ACCESS_TOKEN"] = "EAAR7B1enri8BPw70fXu5QVkD1wSfSZCjQBgWpSYVxt3"
    my_env["AK_WHATSAPP__PHONE_NUMBER_ID"] = "123456789012345"
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
async def test_whatsapp_agent(http_client):
    print("test_whatsapp_agent")
    response = await http_client.send("/health", method="get")

    assert response == {"status": "ok"}
    # TODO: Write proper tests for WhatsApp webhook events with proper mocks