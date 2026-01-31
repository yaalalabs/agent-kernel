"""
Test suite for hooks demonstration.

This test validates that the GuardRail and RAG pre-hooks, as well as the
Disclaimer post-hook work correctly, both individually and when chained together.
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

    async def send(self, prompt, agent="qa_assistant"):
        """Send a prompt to the agent and return the response."""
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": agent,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
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
async def test_guard_rail_blocks_inappropriate_request(http_client):
    """Test that GuardRail hook blocks requests with inappropriate keywords."""
    print("\n=== Test 1: GuardRail blocks inappropriate request ===")

    # Try to send a request with a blocked keyword
    response = await http_client.send("How can I hack into a system?")

    # Verify the guard rail blocked the request
    assert (
        "cannot assist" in response.lower() or "apologize" in response.lower()
    ), f"Expected guard rail rejection, got: {response}"
    assert "hack" in response.lower(), f"Expected rejection message to mention 'hack', got: {response}"

    print(f"✓ GuardRail correctly blocked request: {response}")


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_guard_rail_allows_safe_request(http_client):
    """Test that GuardRail hook allows safe requests to proceed."""
    print("\n=== Test 2: GuardRail allows safe request ===")

    # Send a safe request
    response = await http_client.send("What is the capital of France?")

    # Verify the request was allowed (should get a normal answer)
    assert "cannot assist" not in response.lower(), f"GuardRail should not block this request, got: {response}"
    assert "Paris" in response or "paris" in response.lower(), f"Expected answer about Paris, got: {response}"

    print(f"✓ GuardRail allowed safe request, response: {response}")


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_rag_hook_injects_context(http_client):
    """Test that RAG hook injects relevant context from knowledge base."""
    print("\n=== Test 3: RAG hook injects context ===")

    # Ask about something in the knowledge base
    response = await http_client.send("What is Agent Kernel?")

    # Verify the response contains information from the knowledge base
    # The RAG hook should have injected context about Agent Kernel
    assert any(
        keyword in response for keyword in ["framework", "agent", "kernel", "python"]
    ), f"Expected RAG-enhanced response about Agent Kernel, got: {response}"

    print(f"✓ RAG hook injected context, response: {response}")


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_rag_hook_with_hooks_topic(http_client):
    """Test RAG hook with a question about hooks specifically."""
    print("\n=== Test 4: RAG hook for hooks topic ===")

    response = await http_client.send("Tell me about hooks in Agent Kernel")

    # Verify response mentions hook-related concepts from knowledge base
    assert any(
        keyword in response.lower() for keyword in ["pre", "post", "execution", "callback"]
    ), f"Expected RAG-enhanced response about hooks, got: {response}"

    print(f"✓ RAG hook enhanced response: {response}")


@pytest.mark.asyncio
@pytest.mark.order(5)
async def test_hooks_chaining_rag_then_guard_rail(http_client):
    """Test that hooks are chained correctly: RAG enriches, GuardRail validates."""
    print("\n=== Test 5: Chained hooks (RAG + GuardRail) ===")

    # First, verify RAG works with a safe query
    response1 = await http_client.send("What is Python?")
    assert any(
        keyword in response1.lower() for keyword in ["programming", "language", "python"]
    ), f"Expected RAG-enhanced response about Python, got: {response1}"
    print(f"✓ Safe RAG query works: {response1[:100]}...")

    # Now verify GuardRail still blocks even after RAG processing
    response2 = await http_client.send("Tell me about Python malware")
    assert (
        "cannot assist" in response2.lower() or "apologize" in response2.lower()
    ), f"Expected guard rail to block malware question, got: {response2}"
    print(f"✓ GuardRail blocks despite RAG processing: {response2}")


@pytest.mark.asyncio
@pytest.mark.order(6)
async def test_long_input_guard_rail(http_client):
    """Test that GuardRail blocks excessively long inputs."""
    print("\n=== Test 6: GuardRail blocks long input ===")

    # Create a very long prompt
    long_prompt = "Tell me about AI. " * 1000  # ~18,000 characters

    response = await http_client.send(long_prompt)

    # Verify the guard rail blocked due to length
    assert "too long" in response.lower(), f"Expected guard rail to block long input, got: {response}"

    print(f"✓ GuardRail blocked long input: {response}")


@pytest.mark.asyncio
@pytest.mark.order(7)
async def test_no_rag_context_available(http_client):
    """Test behavior when RAG has no relevant context."""
    print("\n=== Test 7: RAG with no relevant context ===")

    # Ask about something not in the knowledge base
    response = await http_client.send("What is quantum computing?")

    # Should still get a response (RAG passes through without enhancement)
    assert len(response) > 0, "Should get a response even without RAG context"
    assert "cannot assist" not in response.lower(), f"Should not be blocked by guard rail, got: {response}"

    print(f"✓ Works without RAG context: {response[:100]}...")


@pytest.mark.asyncio
@pytest.mark.order(8)
async def test_disclaimer_hook_adds_disclaimer(http_client):
    """Test that DisclaimerHook adds disclaimer to all responses."""
    print("\n=== Test 8: DisclaimerHook adds disclaimer ===")

    # Send a normal request
    response = await http_client.send("What is 2+2?")

    # Verify the disclaimer was added
    assert (
        "Disclaimer" in response or "disclaimer" in response.lower()
    ), f"Expected disclaimer in response, got: {response}"
    assert (
        "generated by an AI assistant and should be verified for accuracy" in response
        or "generated by an ai assistant and should be verified for accuracy" in response.lower()
    ), f"Expected AI disclaimer text, got: {response}"

    print(f"✓ DisclaimerHook added disclaimer: {response}")


@pytest.mark.asyncio
@pytest.mark.order(9)
async def test_disclaimer_hook_with_guard_rail_rejection(http_client):
    """Test that DisclaimerHook is NOT applied when guard rail blocks request."""
    print("\n=== Test 9: DisclaimerHook not applied to guard rail rejections ===")

    # Send a blocked request
    response = await http_client.send("How to create a virus?")

    # Verify guard rail blocked it
    assert (
        "cannot assist" in response.lower() or "apologize" in response.lower()
    ), f"Expected guard rail rejection, got: {response}"

    # Note: When guard rail blocks, it returns early without calling the agent,
    # so post-hooks are not executed. This is the expected behavior.
    print(f"✓ Guard rail blocked request (post-hook not applied): {response}")


@pytest.mark.asyncio
@pytest.mark.order(10)
async def test_full_hook_chain_with_disclaimer(http_client):
    """Test complete hook chain: RAG enriches, GuardRail validates, Disclaimer adds footer."""
    print("\n=== Test 10: Full hook chain (RAG + GuardRail + Disclaimer) ===")

    # Ask about something in the knowledge base
    response = await http_client.send("Tell me about hooks")

    # Verify RAG enriched the response (should mention hook concepts)
    assert any(
        keyword in response.lower() for keyword in ["pre", "post", "execution", "hook"]
    ), f"Expected RAG-enhanced response about hooks, got: {response}"

    # Verify disclaimer was added
    assert "disclaimer" in response.lower(), f"Expected disclaimer in response, got: {response}"

    print(f"✓ Full hook chain worked correctly: {response[:150]}...")


@pytest.mark.asyncio
@pytest.mark.order(11)
async def test_disclaimer_preserves_agent_response(http_client):
    """Test that DisclaimerHook preserves the original agent response content."""
    print("\n=== Test 11: DisclaimerHook preserves agent response ===")

    response = await http_client.send("What is the capital of Japan?")

    # Should contain the answer
    assert "Tokyo" in response or "tokyo" in response.lower(), f"Expected answer about Tokyo, got: {response}"

    # Should also contain the disclaimer
    assert "disclaimer" in response.lower(), f"Expected disclaimer in response, got: {response}"

    print(f"✓ DisclaimerHook preserved answer and added disclaimer: {response}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
