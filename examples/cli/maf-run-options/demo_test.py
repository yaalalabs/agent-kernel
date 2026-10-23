import re

import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

STATS = re.compile(r"Run stats: (.*)$", re.MULTILINE)


def _stats(response: str) -> dict[str, str]:
    """Parse the deterministic stats line the post-hook appends; assert on it, never on the model's wording."""
    match = STATS.search(response)
    assert match, f"no 'Run stats:' line in: {response!r}"
    return dict(part.split("=") for part in match.group(1).split(", "))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_a_tool_turn_reports_what_the_native_calls_received(test_client):
    response = await test_client.send("What's the weather in Tokyo? Use the get_weather tool.")
    stats = _stats(response)
    assert stats["declared_max_tokens"] == "300"  # the declared option, verbatim
    assert stats["max_tokens"] == "300"  # ... arrived in the model call's own options
    assert stats["tenant"] == "acme"  # function_invocation_kwargs arrived in the tool call
    assert int(stats["llm_calls"]) >= 2  # one request to call the tool, one to answer from its result
    assert int(stats["tool_calls"]) >= 1


@pytest.mark.order(2)
async def test_counters_are_per_turn(test_client):
    response = await test_client.send("And what about Paris? Use the get_weather tool.")
    stats = _stats(response)
    assert stats["max_tokens"] == "300"
    assert stats["tenant"] == "acme"
    assert int(stats["tool_calls"]) >= 1
