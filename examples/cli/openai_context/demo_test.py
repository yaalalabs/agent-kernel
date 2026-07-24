import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_first_item_appears_in_cart_line(test_client):
    # The AppendCartPostHook appends a deterministic "Current cart:" line to every reply, so we can
    # assert on it directly rather than fuzzy-matching the LLM's free-form text.
    response = await test_client.send("Add milk to my cart.")
    assert "Current cart:" in response
    assert "milk" in response.lower()


@pytest.mark.order(2)
async def test_second_item_added_to_cart_line(test_client):
    response = await test_client.send("Add eggs as well.")
    assert "milk" in response.lower() and "eggs" in response.lower()


@pytest.mark.order(3)
async def test_cart_persists_across_turns(test_client):
    # This turn is a fresh run, yet the post-hook still reports both earlier items — proving the
    # per-run framework_context round-tripped across turns rather than resetting each run.
    response = await test_client.send("What's in my cart right now?")
    assert "Current cart:" in response
    assert "milk" in response.lower() and "eggs" in response.lower()
