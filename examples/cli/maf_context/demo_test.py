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
    # The last line is appended from stored context by the post-hook, independently of the LLM's prose.
    response = await test_client.send("Add milk to my cart.")
    assert "current cart: milk" in response.lower().splitlines()[-1]


@pytest.mark.order(2)
async def test_second_item_added_to_cart_line(test_client):
    response = await test_client.send("Add eggs as well.")
    assert "current cart: milk, eggs" in response.lower().splitlines()[-1]


@pytest.mark.order(3)
async def test_tool_added_key_round_trips(test_client):
    # The delivery note was not seeded; its footer appears only after the tool's new key is stored.
    response = await test_client.send("Leave the order at the front door.")
    note_line = response.lower().splitlines()[-1]
    assert note_line.startswith("delivery note:")
    assert "door" in note_line


@pytest.mark.order(4)
async def test_context_persists_across_turns(test_client):
    response = await test_client.send("What's in my cart right now?")
    cart_line, note_line = response.lower().splitlines()[-2:]
    assert "current cart: milk, eggs" in cart_line
    assert note_line.startswith("delivery note:")
    assert "door" in note_line
