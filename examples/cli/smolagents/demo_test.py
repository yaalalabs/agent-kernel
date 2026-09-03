import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo_toolcalling.py", match_threshold=0.2)
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_first_question(test_client):
    await test_client.send("Who won the 1996 cricket world cup?, answer with only the country name")
    await test_client.expect(["Sri Lanka"])


@pytest.mark.order(2)
async def test_follow_up_question(test_client):
    await test_client.send("Which countries hosted the tournament? Answer with only the country names, listing all of them.")
    await test_client.expect(["Sri Lanka, India and Pakistan"])
