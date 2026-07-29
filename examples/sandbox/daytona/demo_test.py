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
async def test_sandbox_executes_code_in_cloud(test_client):
    await test_client.send("Run Python code in the sandbox to compute 6 * 7. Reply with only the number.")
    await test_client.expect(["42"])


@pytest.mark.order(2)
async def test_cloud_workspace_persists_across_turns(test_client):
    await test_client.send("Write a file named notes.txt in the sandbox containing exactly this text: hello sandbox")
    await test_client.send("Read notes.txt from the sandbox and reply with only its contents.")
    await test_client.expect(["hello sandbox"])


@pytest.mark.order(3)
async def test_package_install_in_cloud_sandbox(test_client):
    # install_packages is a pip install exec'd in the cloud sandbox; the package is tiny
    # and the converted value is exact, so the assertion stays deterministic.
    await test_client.send(
        "Install the 'roman' package in the sandbox, then use it to convert 42 to a Roman numeral. "
        "Reply with only the numeral."
    )
    await test_client.expect(["XLII"])


@pytest.mark.order(4)
async def test_offline_profile_blocks_network(test_client):
    # The offline profile's network_egress: deny becomes Daytona network_block_all, so the
    # request genuinely fails inside a cloud sandbox. Starting a FRESH session on the offline
    # profile (rather than reusing the default-profile session) forces a real offline sandbox
    # to be provisioned, so this exercises the cloud-side network block, not the manager's
    # profile-binding guard. The sentinel keeps the assertion deterministic: a compliant
    # failure yields OFFLINE, while unenforced policy would yield the fetched status code.
    await test_client.send(
        "Start a new sandbox session named 'net-check' on the offline profile. In that session, "
        "run Python code that fetches https://example.com with a 5 second timeout and prints the "
        "HTTP status code. If the request fails for any reason, reply with only the single word: OFFLINE"
    )
    await test_client.expect(["OFFLINE"])
