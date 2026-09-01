"""
Tests for the Microsoft Teams example server.

These run without any Azure resources: the bot credentials below are placeholders, so the
Bot Framework adapter rejects every unsigned activity. That is enough to prove the server
boots with a `teams:` configuration block and that the webhook route is mounted and
authenticated.
"""

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
            return await client.request(method, f"{self.url}{endpoint}", json=payload)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    my_env = os.environ.copy()
    my_env["AK_TEAMS__APP_ID"] = "00000000-0000-0000-0000-000000000000"
    my_env["AK_TEAMS__APP_PASSWORD"] = "test-app-password"
    proc = subprocess.Popen(
        ["python3", "server.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=my_env,
    )
    await asyncio.sleep(5)
    try:
        yield APITestClient("http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


async def test_teams_health(http_client):
    """The server starts up with a teams configuration block."""
    print("test_teams_health")
    response = await http_client.send("/health", method="get")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_teams_messages_rejects_an_unsigned_activity(http_client):
    """An activity without a valid Bot Framework JWT must be 401, never 500 (Azure retries 5xx)."""
    print("test_teams_messages_rejects_an_unsigned_activity")
    activity = {
        "type": "message",
        "id": "test-activity-id",
        "text": "Hello, what is the capital of France?",
        "from": {"id": "user-123", "name": "Test User"},
        "conversation": {"id": "test-conversation-123"},
        "recipient": {"id": "28:00000000-0000-0000-0000-000000000000", "name": "Agent Bot"},
        "channelId": "msteams",
        "serviceUrl": "https://smba.trafficmanager.net/emea/",
    }
    response = await http_client.send("/teams/messages", method="post", body=activity)
    assert response.status_code == 401
