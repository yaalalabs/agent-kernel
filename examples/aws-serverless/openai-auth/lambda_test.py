import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    def generate_jwt_token(self, email="test@test.com"):
        """Generate a JWT token for testing authentication."""
        payload = {
            "email": email,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
        }
        # Using a dummy secret since the validator doesn't verify signature
        token = jwt.encode(payload, "dummy-secret", algorithm="HS256")
        return token

    async def send(self, prompt, endpoint: str = "", additional_context=None, body=None, email="test@test.com"):
        """Send request with JWT authentication."""
        token = self.generate_jwt_token(email)

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

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}{endpoint}", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")

    async def send_unauthenticated(self, prompt, endpoint: str = "", additional_context=None, body=None):
        """Send request without authentication for testing auth failure."""
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
            return resp


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    endpoint = os.getenv("AK_TEST_ENDPOINT")
    yield APITestClient(endpoint)


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_history_agent_with_valid_auth(http_client):
    """Test history agent with valid JWT token."""
    response = await http_client.send("Who won the 1996 cricket world cup?")
    Test.compare(response, ["Sri Lanka won the 1996 cricket world cup."])


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_history_agent_followup_with_valid_auth(http_client):
    response = await http_client.send("Who hosted?")
    Test.compare(response, ["Sri Lanka, India and Pakistan"])


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_unauthenticated_request(http_client):
    """Test that unauthenticated requests are rejected."""
    resp = await http_client.send_unauthenticated("What is 2 + 2?")
    assert resp.status_code == 401 or resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_invalid_email_auth(http_client):
    """Test that requests with invalid email are rejected."""
    try:
        response = await http_client.send("What is 2 + 2?", email="wrong@email.com")
        # If we get here, authentication didn't fail as expected
        assert False, "Request with invalid email should have been rejected"
    except httpx.HTTPStatusError as e:
        # Expect 401 or 403 for invalid authentication
        assert e.response.status_code == 401 or e.response.status_code == 403
