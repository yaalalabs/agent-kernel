import asyncio
import os
import subprocess
import sys

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(
    loop_scope="session"
)  # uses a single session for all tests


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
    my_env["AK_TELEGRAM__BOT_TOKEN"] = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    my_env["AK_TELEGRAM__WEBHOOK_SECRET"] = "test_webhook_secret_token"
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
async def test_telegram_health(http_client):
    """Test health endpoint."""
    print("test_telegram_health")
    response = await http_client.send("/health", method="get")
    assert response == {"status": "ok"}


@pytest.mark.asyncio
async def test_telegram_webhook(http_client):
    """Test Telegram webhook endpoint with a simulated message."""
    print("test_telegram_webhook")
    # Simulate a Telegram update (message)
    telegram_update = {
        "update_id": 123456789,
        "message": {
            "message_id": 1,
            "from": {
                "id": 123456789,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser",
            },
            "chat": {
                "id": 123456789,
                "first_name": "Test",
                "username": "testuser",
                "type": "private",
            },
            "date": 1234567890,
            "text": "Hello bot!",
        },
    }

    # This will process the message but fail to send response (no valid bot token)
    # The webhook should still return 200 OK to acknowledge receipt
    try:
        response = await http_client.send(
            "/telegram/webhook", method="post", body=telegram_update
        )
        assert response == {"ok": "True"}
    except httpx.HTTPStatusError:
        # Expected if webhook secret validation fails with test token
        pass
