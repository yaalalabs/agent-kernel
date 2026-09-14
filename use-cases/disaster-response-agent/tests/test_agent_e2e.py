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

Comparison mode (fuzzy/judge/fallback) is configured in test-config.yaml.
"""

import os

import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set - skipping live end-to-end agent test",
    ),
]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")  # registers the same AGENTS demo.py/cli.py use
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
    await test_client.expect(["water", "Galle", "recorded", "matched", "pending"])


@pytest.mark.order(2)
async def test_cross_region_no_transport_scenario_flags_logistics(test_client):
    await test_client.send("Elderly couple needs medicine urgently in Matara, no transport")
    # This should surface the seeded Ratnapura offer (which can deliver) as a cross-region
    # match, and the final reply should mention the region gap or delivery/transport.
    await test_client.expect(["Matara", "medicine", "Ratnapura", "transport", "delivery", "region"])


@pytest.mark.order(3)
async def test_status_question_does_not_create_a_new_record(test_client):
    await test_client.send("What's the status in Galle?")
    await test_client.expect(["Galle", "open", "request", "offer", "water"])
