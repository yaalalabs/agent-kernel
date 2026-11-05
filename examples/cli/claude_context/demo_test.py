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
    # The post-hook appends a deterministic "Current cart:" line, so assert on it rather than the LLM's text.
    response = await test_client.send("Add milk to my cart.")
    assert "Current cart:" in response
    assert "milk" in response.lower()


@pytest.mark.order(2)
async def test_second_item_added_to_cart_line(test_client):
    response = await test_client.send("Add eggs as well.")
    assert "milk" in response.lower() and "eggs" in response.lower()


@pytest.mark.order(3)
async def test_context_persists_across_turns(test_client):
    # A fresh run still reports both items, so the context round-tripped through the session.
    response = await test_client.send("What's in my cart right now?")
    cart_line = response.split("Current cart:", 1)[1].lower()
    assert "milk" in cart_line and "eggs" in cart_line
