import asyncio
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
    proc = subprocess.Popen(
        ["python3", "server.py"],
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
async def test_slack_agent(http_client):
    print("test_slack_agent")
    response = await http_client.send("/health", method="get")

    assert response == {"status": "ok"}
    # response = await http_client.send("/api/v1/agents", method="get")
    # assert response == {'agents': ['general']}

    # This will raise HTTPStatusError because the token is invalid & Slack bolts lib is handling the request
    # TODO: Write a proper test for Slack events with proper mocks
    with pytest.raises(httpx.HTTPStatusError):
        challenge_body = {
            "token": "AGRZJwRtHea5ilthqQfP2xbC",
            "challenge": "A3iJatJqh40dIMltX7VbAYVooc4M8vCEUJH5BGpKPSQUwl3WhYnX",
            "type": "url_verification",
        }
        response = await http_client.send("/slack/events", method="post", body=challenge_body)
        print("response:", response)
