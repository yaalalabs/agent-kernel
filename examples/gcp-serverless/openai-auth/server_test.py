import os
import subprocess
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")

# AK_TEST_ENDPOINT  - full API Gateway endpoint, e.g. https://<gateway>/api/v1/chat
# AK_TEST_AUDIENCE  - Cloud Run service URL used as the JWT audience (from terraform output: service_url)
ENDPOINT = os.getenv("AK_TEST_ENDPOINT")
AUDIENCE = os.getenv("AK_TEST_AUDIENCE")


def get_google_identity_token(audience: str = None):
    """
    Get identity token.
    - In CI (WIF): reads pre-generated IDENTITY_TOKEN env var
    - Locally (key file): calls gcloud auth print-identity-token
    """
    # CI path: token pre-generated in workflow
    token = os.environ.get("IDENTITY_TOKEN")
    if token:
        return token

    # Local path: use gcloud directly
    cmd = ['gcloud', 'auth', 'print-identity-token']
    if audience:
        cmd += ['--audiences', audience]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


class APITestClient:
    def __init__(self, url: str):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt: str, endpoint: str = "", body=None) -> str:
        """Send request with a Google Identity Token."""
        token = get_google_identity_token()
        payload = body or {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "triage",
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.url}{endpoint}", json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json().get("result", "")

    async def send_unauthenticated(self, prompt: str, endpoint: str = "") -> httpx.Response:
        """Send request without a token — should be rejected by the API Gateway."""
        payload = {"prompt": prompt, "session_id": self.session_id, "agent": "triage"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(f"{self.url}{endpoint}", json=payload)

    async def send_invalid_token(self, prompt: str, endpoint: str = "") -> httpx.Response:
        """Send request with a tampered/invalid token — should be rejected."""
        payload = {"prompt": prompt, "session_id": self.session_id, "agent": "triage"}
        headers = {"Authorization": "Bearer invalid.token.here", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(f"{self.url}{endpoint}", json=payload, headers=headers)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    yield APITestClient(ENDPOINT)


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_history_agent_with_valid_token(http_client):
    """Test agent with a valid Google Identity Token — API Gateway allows the request."""
    response = await http_client.send("Who won the 1996 cricket world cup?")
    Test.compare(response, ["Sri Lanka won the 1996 cricket world cup."])


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_history_agent_followup_with_valid_token(http_client):
    response = await http_client.send("Who hosted?")

    assert "India" in response
    assert "Pakistan" in response

@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_unauthenticated_request(http_client):
    """Test that requests without a token are rejected by the API Gateway (401)."""
    resp = await http_client.send_unauthenticated("What is 2 + 2?")
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_invalid_token_request(http_client):
    """Test that requests with an invalid/tampered token are rejected by the API Gateway (401)."""
    resp = await http_client.send_invalid_token("What is 2 + 2?")
    assert resp.status_code == 401
