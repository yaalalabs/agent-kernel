"""
Smoke test for the CLI entrypoint (demo.py).

LLM replies from profile_agent/matching_agent vary from run to run, so this deliberately
does not assert on exact wording. It only checks that a message gets a real, non-empty
reply with no provider error embedded in it, guarding against wiring regressions (broken
imports, broken agent registration, a bad model string).

Requires GOOGLE_API_KEY or GEMINI_API_KEY (skipped otherwise, per ak-dev-testing-conventions'
pattern for external-credential-gated tests).
"""

import os

import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(
        not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")),
        reason="Requires GOOGLE_API_KEY or GEMINI_API_KEY",
    ),
]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_profile_agent_responds(test_client):
    """profile_agent (the default entry agent) should return a real, non-empty reply."""
    response = await test_client.send("Hello")
    assert response, "Expected a non-empty reply from profile_agent"
    assert "error" not in response.lower(), f"Agent reply looked like a provider/wiring error: {response!r}"
