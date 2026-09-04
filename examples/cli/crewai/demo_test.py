import os
import sys

import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")


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
    await test_client.send("Who won the 1996 cricket world cup?, answer with only the country name")
    await test_client.expect(["Sri Lanka"])


@pytest.mark.order(2)
async def test_follow_up_question(test_client):
    await test_client.send(
        "Which country hosted the tournament?, answer with only the country names and make sure to mention all the contries that hosted this tournament"
    )
    await test_client.expect(["Sri Lanka, India and Pakistan"])
