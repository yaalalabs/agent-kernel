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
async def test_workspace_profile_persists(test_client):
    await test_client.send("In the workspace, write a file marker.txt containing exactly: kept")
    await test_client.send("Read marker.txt from the workspace and reply with only its contents.")
    await test_client.expect(["kept"])


@pytest.mark.order(2)
async def test_scratch_profile_is_isolated(test_client):
    # marker.txt lives in the persistent workspace profile, not in a fresh scratch sandbox.
    await test_client.send(
        "Using the scratch profile (a fresh throwaway sandbox), check whether marker.txt exists. "
        "Reply with exactly 'present' if it exists, or 'absent' if it does not."
    )
    await test_client.expect(["absent"])
