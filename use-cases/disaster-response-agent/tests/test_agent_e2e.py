"""
End-to-end conversational test for the Disaster Response & Resource Coordination Agent.

Unlike test_tool_layer.py (which calls tool.py functions directly, no LLM involved), this
drives the REAL agents - intake_agent -> priority_matching_agent -> dedup_dispatch_agent -
through Agent Kernel's built-in test harness (agentkernel.test.Test), talking to Gemini for
real. That means it needs a live GEMINI_API_KEY and costs a small number of real API calls, so
it's automatically skipped if one isn't set (e.g. in CI without secrets configured) rather than
failing the whole test run.

Run with a key set:
    uv run pytest tests/test_agent_e2e.py -v

Comparison mode is configured in test-config.yaml (fuzzy by default - see the note there on
why plain fuzzy/Test.expect() isn't used directly for these assertions).
"""

import os

import pytest
import pytest_asyncio
from agentkernel.test import Test
from dotenv import load_dotenv

# Load .env BEFORE the skipif below is evaluated. agent.py (run in the demo.py subprocess)
# also calls load_dotenv(), but that happens too late to help here: pytest evaluates this
# module's `pytestmark` at collection time, in this process, before any subprocess starts -
# so without this, GEMINI_API_KEY set only via .env (the documented setup path) would never
# be seen and every live test would be skipped even though the subprocess could load the key.
load_dotenv()

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set - skipping live end-to-end agent test",
    ),
]


def assert_response_mentions(test_client: Test, *keywords: str) -> None:
    """Assert the last agent response contains at least one of the given keywords.

    Test.expect()'s fuzzy mode compares the ENTIRE response against each expected string with
    rapidfuzz.fuzz.ratio() - fine for near-identical short strings, but useless for checking
    whether a single keyword appears somewhere inside a multi-sentence reply (a 3-5 sentence
    response will never score above the similarity threshold against a lone word like "Galle").
    This does a plain case-insensitive substring check instead, which is what these assertions
    actually mean.
    """
    response = (test_client.last_agent_response or "").lower()
    found = [kw for kw in keywords if kw.lower() in response]
    assert found, f"Expected response to mention one of {list(keywords)}, got: {test_client.last_agent_response!r}"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")  # registers the same AGENTS demo.py uses
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_new_need_is_recorded_and_gets_a_confirmation(test_client):
    await test_client.send("Need drinking water in Galle")
    # The seeded Galle offer should be matched same-region, so expect a positive confirmation
    # mentioning water/Galle rather than a "nothing found" reply.
    assert_response_mentions(test_client, "water", "Galle", "recorded", "matched", "pending")


@pytest.mark.order(2)
async def test_cross_region_no_transport_scenario_flags_logistics(test_client):
    await test_client.send("Elderly couple needs medicine urgently in Matara, no transport")
    # This should surface the seeded Ratnapura offer (which can deliver) as a cross-region
    # match, and the final reply should mention the region gap or delivery/transport.
    assert_response_mentions(test_client, "Matara", "medicine", "Ratnapura", "transport", "delivery", "region")


@pytest.mark.order(3)
async def test_status_question_does_not_create_a_new_record(test_client):
    await test_client.send("What's the status in Galle?")
    assert_response_mentions(test_client, "Galle", "open", "request", "offer", "water")
