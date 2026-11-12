"""Tests for the deployed authenticated example.

Set:
- AK_TEST_ENDPOINT: the module's `agent_invoke_url` output (the chat route).
- AK_TEST_TOKEN: a credential the identity provider in config.yaml accepts. With the static
  provider that is the `demo_auth_token` the stack was deployed with. With the Auth0 block from the
  README it is an access token for the API, for example from the client-credentials flow:

      curl -s --request POST https://<tenant>.<region>.auth0.com/oauth/token \\
        -H 'content-type: application/json' \\
        -d '{"client_id": "...", "client_secret": "...", "audience": "<API identifier>", "grant_type": "client_credentials"}'

  and `AK_TEST_TOKEN` is the `access_token` of the reply.
"""

import asyncio
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

TOKEN = os.getenv("AK_TEST_TOKEN", "")


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def post(self, payload, token=TOKEN, endpoint: str = ""):
        """Send a request, with the bearer token unless `token` is None, retrying cold-start failures."""
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Retry 5xx and timeouts: serverless cold starts can exceed the gateway timeout
            for attempt in range(3):
                try:
                    resp = await client.post(f"{self.url}{endpoint}", json=payload, headers=headers)
                except httpx.TimeoutException:
                    if attempt == 2:
                        raise
                    continue
                if resp.status_code < 500 or attempt == 2:
                    return resp
                await asyncio.sleep(5)
            return resp

    async def send(self, prompt, additional_context=None):
        """Send an authenticated chat request and return the agent's reply."""
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "triage",
            "additional_context": additional_context,
        }
        resp = await self.post(payload)
        resp.raise_for_status()
        return resp.json().get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    endpoint = os.getenv("AK_TEST_ENDPOINT")
    assert endpoint, "Set AK_TEST_ENDPOINT to the deployment's agent_invoke_url"
    assert TOKEN, "Set AK_TEST_TOKEN to a credential the identity provider accepts"
    yield APITestClient(endpoint)


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_history_agent_with_valid_auth(http_client):
    """Test history agent with a valid token."""
    response = await http_client.send("Who won the 1996 cricket world cup?, answer with only the country name")
    Test.compare(response, ["Sri Lanka"])


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_history_agent_followup_with_valid_auth(http_client):
    response = await http_client.send(
        "Which country hosted the tournament?, answer with only the country names and make sure to mention all the contries that hosted this tournament"
    )
    Test.compare(response, ["Sri Lanka, India and Pakistan"])


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_a_request_without_a_token_is_rejected(http_client):
    """The authorizer denies a request that carries no credential."""
    resp = await http_client.post(
        {"prompt": "What is 2 + 2?", "session_id": http_client.session_id, "agent": "triage"}, token=None
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_a_refused_token_is_rejected(http_client):
    """A credential the identity provider does not accept is denied, with no hint as to why."""
    resp = await http_client.post(
        {"prompt": "What is 2 + 2?", "session_id": http_client.session_id, "agent": "triage"}, token="not-the-token"
    )
    assert resp.status_code in (401, 403)
