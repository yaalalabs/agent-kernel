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
async def test_relaxed_profile_runs_code(test_client):
    # The relaxed profile (strict: false) proceeds despite unenforceable policy dimensions.
    await test_client.send("Using the relaxed profile, run Python code to compute 6 * 7. Reply with only the number.")
    await test_client.expect(["42"])


@pytest.mark.order(2)
async def test_guarded_profile_fails_closed(test_client):
    # The guarded profile (strict: true) sets policy local_subprocess can't enforce, so the
    # sandbox rejects the execution. The prompt pins the agent to the guarded profile and
    # demands a sentinel word on rejection, so the assertion is deterministic: a compliant
    # rejection yields BLOCKED, while any silent workaround would yield the code's output.
    await test_client.send(
        "Using ONLY the guarded profile (never any other profile), run Python code that prints the text hello. "
        "If the sandbox refuses to run it for any reason, reply with only the single word: BLOCKED"
    )
    await test_client.expect(["BLOCKED"])
