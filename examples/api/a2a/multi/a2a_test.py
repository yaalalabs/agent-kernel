import asyncio
import os
import signal
import subprocess
import time

import httpx
import pytest
import pytest_asyncio
from ak.test import Test

from client import A2AHttpClient

pytestmark = pytest.mark.asyncio


def timeout_handler(signum, frame):
    raise TimeoutError("Test timed out!")


@pytest_asyncio.fixture(scope="function")
async def test_server():
    print(f"=== Starting server fixture in environment: {os.environ.get('GITHUB_ACTIONS', 'local')} ===")
    test = None
    # Set a timeout for GitHub Actions
    if os.environ.get('GITHUB_ACTIONS'):
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(120)  # 2-minute timeout

    try:
        print("Creating Test instance...")
        test = Test("server.py", cli_mode=False)
        print("Test instance created")

        print("Calling test.start()...")
        start_time = time.time()
        await test.start()
        elapsed = time.time() - start_time
        print(f"test.start() completed in {elapsed:.2f}s")

        print("Checking if server process is running...")
        # Add process check if accessible

        print("Server started, yielding...")
        yield test

    except Exception as e:
        print(f"Error in server fixture: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        if os.environ.get('GITHUB_ACTIONS'):
            signal.alarm(0)  # Cancel timeout

        print("Stopping server...")
        try:
            await test.stop()
            print("Server stopped")
        except Exception as e:
            print(f"Error stopping server: {e}")


@pytest_asyncio.fixture(scope="function")
async def test_client(test_server):
    print("=== Starting client fixture ===")

    # Manual process check - bypass ak.test health check
    print("Checking if port 8000 is listening...")
    result = subprocess.run(
        ["netstat", "-ln"],
        capture_output=True,
        text=True,
        timeout=10
    )
    if ":8000" in result.stdout:
        print("Port 8000 is listening")
    else:
        print("Port 8000 is NOT listening")
        print("Netstat output:", result.stdout[:500])

    # Test direct HTTP connection
    print("Testing direct HTTP connection...")
    for attempt in range(5):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://127.0.0.1:8000/health", timeout=5.0)
                print(f"HTTP health check: {response.status_code}")
                break
        except Exception as e:
            print(f"HTTP health check attempt {attempt + 1}: {e}")
            await asyncio.sleep(2)

    print("Creating A2A client...")
    test_client = A2AHttpClient("http://127.0.0.1:8000/a2a/general")

    print("Initializing A2A client...")
    await test_client.init()
    print("Client initialized")

    yield test_client


@pytest.mark.order(1)
async def test_first_question(test_server, test_client):
    response = await test_client.send("Who won the 1996 cricket world cup?")
    test_server.compare(response, "Sri Lanka won the world cup.")
    response = await test_client.send("Which countries hosted the tournament?")
    test_server.compare(response, "The 1996 Cricket World Cup was hosted by India, Pakistan, and Sri Lanka.")
