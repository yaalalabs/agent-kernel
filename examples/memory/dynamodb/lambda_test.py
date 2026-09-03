import asyncio
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
            # Retry 5xx and timeouts: serverless cold starts can exceed the gateway timeout
            for attempt in range(3):
                try:
                    resp = await client.post(f"{self.url}{endpoint}", json=payload)
                except httpx.TimeoutException:
                    if attempt == 2:
                        raise
                    continue
                if resp.status_code < 500 or attempt == 2:
                    break
                await asyncio.sleep(5)
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
    response = await http_client.send("Who won the 1996 cricket world cup?, answer with only the country name")
    Test.compare(response, ["Sri Lanka"])


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_history_agent_followup(http_client):
    response = await http_client.send("Which country hosted the tournament?, answer with only the country names and make sure to mention all the contries that hosted this tournament")
    Test.compare(response, ["Sri Lanka, India and Pakistan"])
