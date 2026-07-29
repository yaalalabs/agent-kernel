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
async def test_guarded_profile_runs_within_envelope(test_client):
    # Every guarded dimension is enforceable on docker, so execution proceeds normally
    # inside the envelope (deny egress, cpu/memory limits).
    await test_client.send("Using the guarded profile, run Python code to compute 6 * 7. Reply with only the number.")
    await test_client.expect(["42"])


@pytest.mark.order(2)
async def test_guarded_profile_network_deny_is_enforced(test_client):
    # network_egress: deny becomes network_mode: none, so the fetch genuinely fails inside
    # the container. The sentinel keeps the assertion deterministic: enforced policy yields
    # OFFLINE, while unenforced egress would yield the fetched status code.
    await test_client.send(
        "Using ONLY the guarded profile (never any other profile), run Python code that fetches "
        "https://example.com with a 5 second timeout and prints the HTTP status code. "
        "If the request fails for any reason, reply with only the single word: OFFLINE"
    )
    await test_client.expect(["OFFLINE"])


@pytest.mark.order(3)
async def test_restricted_profile_fails_closed(test_client):
    # The restricted profile sets an egress allowlist, the one network mode docker cannot
    # enforce, so with strict: true the sandbox rejects the execution. A compliant rejection
    # yields the BLOCKED sentinel (or relays the policy error); a silent workaround would
    # yield the code's output, which fuzzy-matches neither expected string.
    await test_client.send(
        "Using ONLY the restricted profile (never any other profile), run Python code that prints the "
        "text hello. If the sandbox refuses to run it for any reason, reply with only the single word: BLOCKED"
    )
    await test_client.expect(
        [
            "BLOCKED",
            "docker cannot enforce a network egress allowlist; use 'deny' or 'allow', or set strict=false",
        ]
    )


@pytest.mark.order(4)
async def test_relaxed_profile_proceeds_with_warning(test_client):
    # Same allowlist intent with strict: false: the execution proceeds (egress effectively
    # unrestricted), so the same computation that was rejected on 'restricted' now runs.
    await test_client.send("Using the relaxed profile, run Python code to compute 6 * 7. Reply with only the number.")
    await test_client.expect(["42"])
