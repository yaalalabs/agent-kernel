import pytest
import pytest_asyncio

from ak.test import Test


@pytest_asyncio.fixture(loop_scope="session")
async def test_client():
    client = Test("demo.py")
    await client.start()
    try:
        yield client
    finally:
        await client.stop()


@pytest.mark.order(1)
@pytest.mark.asyncio(loop_scope="session")
async def test_first_question(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    await test_client.expect("Sri Lanka won the 1996 cricket world cup.")


@pytest.mark.order(2)
@pytest.mark.asyncio(loop_scope="session")
async def test_follow_up_question(test_client):
    await test_client.send("Which country hosted the tournament?")
    await test_client.expect("Co-hosted by India, Pakistan and Sri Lanka.")
