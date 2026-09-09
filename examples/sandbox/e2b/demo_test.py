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
async def test_sandbox_executes_code_in_micro_vm(test_client):
    await test_client.send("Run Python code in the sandbox to compute 6 * 7. Reply with only the number.")
    await test_client.expect(["42"])


@pytest.mark.order(2)
async def test_kernel_variables_persist_across_turns(test_client):
    # E2B is stateful: run_code executes in a persistent Jupyter kernel, so a Python
    # variable defined in one execution is still bound in the next — something a
    # stateless provider (docker, daytona) cannot do. This is the provider's signature.
    await test_client.send("In the sandbox, run Python that assigns secret = 1729. Just confirm it ran.")
    await test_client.send(
        "Now run Python that prints the value of the variable `secret`. Reply with only that number."
    )
    await test_client.expect(["1729"])


@pytest.mark.order(3)
async def test_package_install_in_micro_vm(test_client):
    # install_packages runs pip in the sandbox; the package is tiny and the converted value
    # is exact, so the assertion stays deterministic.
    await test_client.send(
        "Install the 'roman' package in the sandbox, then use it to convert 42 to a Roman numeral. "
        "Reply with only the numeral."
    )
    await test_client.expect(["XLII"])


@pytest.mark.order(4)
async def test_offline_profile_blocks_network(test_client):
    # The offline profile's network_egress: deny becomes allow_internet_access=false, so the
    # request fails inside the micro-VM. Starting a FRESH session on the offline profile forces
    # a real offline sandbox to be provisioned, so this exercises the enforced network block,
    # not the manager's profile-binding guard. The sentinel keeps the assertion deterministic.
    await test_client.send(
        "Start a new sandbox session named 'net-check' on the offline profile. In that session, "
        "run Python code that fetches https://example.com with a 5 second timeout and prints the "
        "HTTP status code. If the request fails for any reason, reply with only the single word: OFFLINE"
    )
    await test_client.expect(["OFFLINE"])
