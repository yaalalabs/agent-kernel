"""
Test suite for auxiliary memory.

This test validates that the RAG pre-hook correctly injects context into non-volatile memory and its used be a search tool later
"""

import asyncio
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")


class APITestClient:
    """HTTP client for testing the API server."""

    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt, agent="junior_assistant"):
        """Send a prompt to the agent and return the response."""
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": agent,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.url}/run", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    """Start the API server and provide a test client."""
    proc = subprocess.Popen(
        ["python3", "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    # Wait for server to start
    await asyncio.sleep(5)
    try:
        yield APITestClient("http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_junior_agent_on_acme(http_client):

    # Try to send a request with a blocked keyword
    response = await http_client.send("What is AcmeXXLabs?", agent="junior_assistant")
    print(f"Junior agent response: {response}")
    assert "i don't know" in response.lower() or "no relevant information" in response.lower(), f"Expected 'I don't know' response, got: {response}"
    print(f"✓ Junior agent correctly responded to query: {response}")
    
@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_senior_agent_on_acme(http_client):

    # Try to send a request with a blocked keyword
    response = await http_client.send("What is AcmeXXLabs?", agent="senior_assistant")
    print(f"Senior agent response: {response}")
    assert "cutting-edge green technology" in response.lower() and "san francisco" in response.lower(), f"Expected 'cutting edge green technology' response, got: {response}"
    print(f"✓ Senior agent correctly responded to query: {response}")
    
@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_junior_agent_on_softlabs(http_client):

    # Try to send a request with a blocked keyword
    response = await http_client.send("What is SoftYYLabs?", agent="junior_assistant")
    print(f"Junior agent response: {response}")
    assert "i don't know" in response.lower() or "no relevant information" in response.lower(), f"Expected 'I don't know' response, got: {response}"
    print(f"✓ Junior agent correctly responded to query: {response}")
    
@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_senior_agent_on_softlabs(http_client):

    # Try to send a request with a blocked keyword
    response = await http_client.send("What is SoftYYLabs?", agent="senior_assistant")
    print(f"Senior agent response: {response}")
    assert "thorium" in response.lower() and "research" in response.lower() and "shandong" in response.lower(), f"Expected 'thorium based research' response, got: {response}"
    print(f"✓ Senior agent correctly responded to query: {response}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])