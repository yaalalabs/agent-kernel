import asyncio

import pytest
import pytest_asyncio
from ak.test import Test

from client import A2AHttpClient

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_server():
    test = Test("server.py", cli_mode=False)
    await test.start()
    print("Server started")
    try:
        yield test
    finally:
        await test.stop()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client(test_server):
    try:
        test_client = A2AHttpClient("http://localhost:8000/a2a/general")
        await asyncio.wait_for(test_client.init(), timeout=15.0)
        print("Client initialized")
        yield test_client
    except asyncio.TimeoutError as e:
        print(f"Client initialization timeout: {e}")
        raise
    except Exception as e:
        print(f"Client initialization failed: {e}")
        raise
    finally:
        pass


@pytest.mark.order(1)
async def test_first_question(test_server, test_client):
    response = await test_client.send("Who won the 1996 cricket world cup?")
    test_server.compare(response, "Sri Lanka won the world cup.")


@pytest.mark.order(2)
async def test_follow_up_question(test_client, test_server):
    response = await test_client.send("Which countries hosted the tournament?")
    test_server.compare(response, "The 1996 Cricket World Cup was hosted by India, Pakistan, and Sri Lanka")
