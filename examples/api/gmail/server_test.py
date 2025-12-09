
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
    my_env["AK_GMAIL__CREDENTIALS_FILE"] = "test_credentials.json"
    my_env["AK_GMAIL__TOKEN_FILE"] = "test_token.pickle"
    my_env["AK_GMAIL__AGENT"] = "test_gmail_agent"
    my_env["AK_TEST_MODE"] = "1"
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
    print("test_gmail_health")
    response = await http_client.send("/health", method="get")
    assert response == {"status": "ok"}


@pytest.mark.asyncio
async def test_gmail_webhook(http_client):
    print("test_gmail_webhook")
    # Simulate a Gmail webhook event (structure may vary based on your implementation)
    gmail_event = {
        "email_id": "test_email_id_123",
        "from": "testuser@gmail.com",
        "subject": "Test Subject",
        "body": "Hello from Gmail!",
    }
    try:
        response = await http_client.send("/gmail/webhook", method="post", body=gmail_event)
        assert response == {"status": "ok"}
    except httpx.HTTPStatusError:
        pass
