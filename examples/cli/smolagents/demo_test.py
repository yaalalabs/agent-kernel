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
    await test_client.send(
        "Which country won the 1996 men's cricket world cup final played in Lahore?, answer with only the country name"
    )
    await test_client.expect(["Sri Lanka"])


@pytest.mark.order(2)
async def test_follow_up_question(test_client):
    await test_client.send(
        "Which South Asian countries co-hosted that tournament?, answer with only the country names and make sure to mention all of the co-hosting countries"
    )
    await test_client.expect(
        ["Sri Lanka, India and Pakistan", "India, Pakistan and Sri Lanka", "India, Pakistan, Sri Lanka"]
    )
