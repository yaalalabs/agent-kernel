import pytest
import pytest_asyncio
from ak.test import Test

from client import A2AHttpClient

pytestmark = pytest.mark.asyncio(loop_scope="function")  # uses a single session for all tests


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def test_server():
    test = Test("server.py", cli_mode=False)
    await test.start()
    print("Server started")
    try:
        yield test
    finally:
        await test.stop()


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def test_client(test_server):
    test_client = A2AHttpClient("http://127.0.0.1:8000/a2a/general")
    await test_client.init()
    print("Client initialized")
    try:
        yield test_client
    finally:
        pass


@pytest.mark.order(1)
async def test_first_question(test_server, test_client):
    response = await test_client.send("Who won the 1996 cricket world cup?")
    test_server.compare(response, "Sri Lanka won the world cup.")
    response = await test_client.send("Which countries hosted the tournament?")
    test_server.compare(response, "The 1996 Cricket World Cup was hosted by India, Pakistan, and Sri Lanka.")
