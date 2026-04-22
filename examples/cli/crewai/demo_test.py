import os
import pytest
import pytest_asyncio
from unittest.mock import patch
from agentkernel.test import Test


os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["CI"] = "true"

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="session", autouse=True)
def block_interactive_prompts():
    """
    Automatically answers 'n' to any CLI input request.
    Because autouse=True, this wraps around every test automatically
    and prevents the CI runner from hanging on CrewAI's trace prompts.
    """
    with patch('builtins.input', return_value='n'):
        yield


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
    await test_client.send("Who won the 1996 cricket world cup?")
    await test_client.expect(["The 1996 Cricket World Cup was won by Sri Lanka."])

@pytest.mark.order(2)
async def test_follow_up_question(test_client):
    await test_client.send("Which country hosted the tournament?")
    await test_client.expect(["Sri Lanka hosted the 1996 Cricket World Cup alongside India and Pakistan"])