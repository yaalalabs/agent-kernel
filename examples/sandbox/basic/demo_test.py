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
async def test_sandbox_executes_code(test_client):
    await test_client.send("Run Python code in the sandbox to compute 6 * 7. Reply with only the number.")
    await test_client.expect(["42"])


@pytest.mark.order(2)
async def test_sandbox_workspace_persists_across_turns(test_client):
    await test_client.send("Write a file named notes.txt in the sandbox containing exactly this text: hello sandbox")
    await test_client.send("Read notes.txt from the sandbox and reply with only its contents.")
    await test_client.expect(["hello sandbox"])


@pytest.mark.order(3)
async def test_sandbox_computes_deterministic_result(test_client):
    await test_client.send(
        "Run Python code in the sandbox to compute the sum of all prime numbers below 50. Reply with only the number."
    )
    await test_client.expect(["328"])


@pytest.mark.order(4)
async def test_fresh_named_session_starts_empty(test_client):
    await test_client.send(
        "Create a fresh sandbox session named test-env and list the files in it. If there are no files, reply with exactly: empty"
    )
    await test_client.expect(["empty"])
