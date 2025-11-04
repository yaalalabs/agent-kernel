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
async def test_first_question(test_client):
    await test_client.send("!select physics")
    await test_client.send("Who discovered energy emission from black holes?")
    await test_client.expect("Stephen Hawking")

    await test_client.send("!select geography")
    await test_client.send("What is the prehistoric single continent of which all current continents broke off from?")
    await test_client.expect("Pangea")

    await test_client.send("!select triage")
    await test_client.expect("No agent found with name 'triage'")
