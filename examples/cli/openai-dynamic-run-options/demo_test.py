import re

import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

STATS = re.compile(r"Run stats: (.*)$", re.MULTILINE)


def _stats(response: str) -> dict[str, int]:
    """Parse the deterministic stats line the post-hook appends; assert on it, never on the model's wording."""
    match = STATS.search(response)
    assert match, f"no 'Run stats:' line in: {response!r}"
    return {key: int(value) for key, value in (part.split("=") for part in match.group(1).split(", "))}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_the_factory_runs_and_the_static_limit_applies_to_a_regular_session(test_client):
    response = await test_client.send("What's the weather in Tokyo? Use the get_weather tool.")
    stats = _stats(response)
    assert stats["factory_runs"] >= 1  # the factory ran for this turn
    assert stats["max_turns"] == 25  # the CLI session is not a guest session, so the static limit applied
    assert stats["llm_calls"] >= 1  # the static hooks keyword still reached the SDK beside the factory
    assert stats["tool_calls"] >= 1


@pytest.mark.order(2)
async def test_the_factory_runs_again_on_the_next_turn(test_client):
    response = await test_client.send("And what about Paris? Use the get_weather tool.")
    stats = _stats(response)
    assert stats["factory_runs"] >= 1  # counters are per turn, so this is the second turn's own resolution
    assert stats["max_turns"] == 25
    assert stats["tool_calls"] >= 1
