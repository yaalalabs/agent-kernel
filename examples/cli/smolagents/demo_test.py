import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py", match_threshold=20)
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_first_question(test_client):
    await test_client.send("What is 4 times 5?, give the answer only")
    await test_client.expect(["20"])


@pytest.mark.order(2)
async def test_follow_up_question(test_client):
    await test_client.send("and what if we add 10 to that result (20)?, give the answer only")
    await test_client.expect(["30"])
