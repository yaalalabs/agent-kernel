import pytest
import pytest_asyncio

from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session") # uses a single session for all tests


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
    await test_client.expect("Stephen Hawking discovered energy emission from black holes, known as Hawking radiation.")