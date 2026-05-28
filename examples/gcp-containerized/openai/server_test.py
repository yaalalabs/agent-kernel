import os
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt, endpoint: str = "", additional_context=None, body=None):
        payload = (
            {
                "prompt": prompt,
                "session_id": self.session_id,
                "agent": "triage",
                "additional_context": additional_context,
            }
            if body is None
            else body
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}{endpoint}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    endpoint = os.getenv("AK_TEST_ENDPOINT")
    yield APITestClient(endpoint)


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_history_agent(http_client):
    response = await http_client.send("Who won the 1996 cricket world cup?")
    response = response.lower()

    assert "sri lanka" in response
    assert "1996" in response
    assert "world cup" in response
    assert "won" in response


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_history_agent_followup(http_client):
    response = await http_client.send("Who hosted?")
    response = response.lower()

    assert "sri lanka" in response
    assert "india" in response
    assert "pakistan" in response
    assert "host" in response
