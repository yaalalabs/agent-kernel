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
async def test_math_question(test_client):
    await test_client.send("What is 15 multiplied by 12?")
    await test_client.expect(["180", "15 multiplied by 12 is 180.", "The answer is 180."])


@pytest.mark.order(2)
async def test_weather_question(test_client):
    await test_client.send("What is the weather in Tokyo?")
    await test_client.expect(["The weather in Tokyo is sunny."])
