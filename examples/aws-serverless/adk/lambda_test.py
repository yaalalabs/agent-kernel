import os
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


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
    response = await http_client.send("when did the battle of Waterloo happen?")
    Test.compare(
        response,
        ["The Battle of Waterloo happened on June 18, 1815."],
        threshold=10,
    )


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_history_agent_followup(http_client):
    response = await http_client.send("who won?")
    Test.compare(
        response,
        ["The Duke of Wellington and the Prussian forces led by Gebhard Leberecht von Blücher won"],
        threshold=10,
    )
