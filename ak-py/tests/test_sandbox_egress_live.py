"""The network-egress allowlist against REAL sandbox providers (spec #692 Testing: the live gate).

``network_egress: allowlist`` joins the documented hardening recipe for ``e2b`` and ``daytona``
only once this passes against each provider: with the PyPI hosts listed, a sandbox must reach
them, must not reach an unlisted host, and a permitted install must succeed. The research behind
#692 suspects both mappings (e2b sends ``allow_out`` without ``deny_out``; daytona's
``network_allow_list`` takes CIDRs, not domains), so a failure here is a finding, not a flake.

Each live class is skipped unless the gate and that provider's API key are set, so the normal
unit run is unaffected; ``TestFakeEgressAllowlist`` runs the same contract against a local fake
so the probe and teardown logic is exercised on every run:

    AK_TEST_SANDBOX_EGRESS=1 E2B_API_KEY=... DAYTONA_API_KEY=... \
        uv run pytest tests/test_sandbox_egress_live.py -v

Every test creates its own sandbox and destroys it, so runs never share state.
"""

import os
import re
import shlex
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest

from agentkernel.sandbox.base import Sandbox, SandboxProvider
from agentkernel.sandbox.model import SandboxPolicy, SandboxPrincipal, SandboxResult
from agentkernel.sandbox.testing import FakeSandbox, FakeSandboxProvider

LIVE = os.getenv("AK_TEST_SANDBOX_EGRESS") == "1"

# pip needs both hosts: the index (pypi.org) and the file CDN (files.pythonhosted.org).
ALLOWED_HOSTS = ["pypi.org", "files.pythonhosted.org"]
LISTED_URL = "https://pypi.org/simple/"
UNLISTED_URL = "https://example.com/"
PROBE_TIMEOUT_SECONDS = 60  # well above the probe's own urlopen(timeout=10): a blocked connect may hang

# One stdlib-only probe line per outcome, so a blocked host can never be confused with a broken sandbox.
_PROBE = """\
import urllib.error, urllib.request
try:
    urllib.request.urlopen({url!r}, timeout=10).read(1)
    print("REACHED")
except urllib.error.HTTPError as exc:  # a response came back, from the host or an enforcing proxy
    print("HTTP:" + str(exc.code))
except (urllib.error.URLError, OSError):
    print("BLOCKED")
except Exception as exc:
    print("OTHER:" + type(exc).__name__)
"""


def _allowlist_policy() -> SandboxPolicy:
    return SandboxPolicy(network_egress="allowlist", network_allow=list(ALLOWED_HOSTS), strict=True)


async def _probe(sandbox: Sandbox, url: str) -> str:
    """Run the probe for ``url`` inside the sandbox and return its outcome marker."""
    command = shlex.join(["python3", "-c", _PROBE.format(url=url)])
    result = await sandbox.execute_command(command, timeout=PROBE_TIMEOUT_SECONDS)
    lines = result.stdout.strip().splitlines()
    outcome = lines[-1] if lines else ""
    assert outcome in ("REACHED", "BLOCKED") or outcome.startswith(
        ("HTTP:", "OTHER:")
    ), f"probe of {url} produced no outcome marker (exit {result.exit_code}): stdout={result.stdout!r} stderr={result.stderr!r}"
    return outcome


def _reached(outcome: str) -> bool:
    """A successful response from the host: REACHED, or an HTTP 2xx/3xx status."""
    return outcome == "REACHED" or outcome.startswith(("HTTP:2", "HTTP:3"))


class EgressAllowlistContract:
    """The allowlist behaviour every provider must show before the recipe documents it.

    Subclass and override :meth:`make_provider`. Not collected on its own: the class name is
    intentionally not prefixed ``Test``.
    """

    def make_provider(self) -> SandboxProvider:
        """The provider under test; every subclass must override this."""
        raise NotImplementedError("subclasses must override make_provider")

    @asynccontextmanager
    async def _sandbox(self) -> AsyncIterator[Sandbox]:
        """A fresh sandbox under the allowlist policy, destroyed afterwards whatever happens."""
        provider = self.make_provider()
        principal = SandboxPrincipal(subject=f"egress-live-{uuid.uuid4().hex[:8]}")
        sandbox = await provider.create(principal=principal, policy=_allowlist_policy())
        try:
            yield sandbox
        finally:
            try:
                await sandbox.close()
            finally:
                await provider.destroy(sandbox.id)  # always: a leaked live sandbox keeps billing

    @pytest.mark.asyncio
    async def test_listed_registry_host_is_reachable(self):
        async with self._sandbox() as sandbox:
            outcome = await _probe(sandbox, LISTED_URL)
            assert _reached(outcome), f"listed host {LISTED_URL}: {outcome}"

    @pytest.mark.asyncio
    async def test_unlisted_host_is_blocked(self):
        async with self._sandbox() as sandbox:
            # The listed host first, in the same sandbox: proves its network works, so BLOCKED below means blocked.
            listed = await _probe(sandbox, LISTED_URL)
            assert _reached(listed), f"listed host {LISTED_URL}: {listed}"
            # Strict on purpose. An HTTP:<code> here means a response came back: either the host itself was
            # reached, or an enforcing proxy answered (e.g. HTTP:403). The marker in the message tells which to record.
            outcome = await _probe(sandbox, UNLISTED_URL)
            assert outcome == "BLOCKED", f"unlisted host {UNLISTED_URL}: {outcome}"

    @pytest.mark.asyncio
    async def test_install_succeeds_under_the_allowlist(self):
        async with self._sandbox() as sandbox:
            result = await sandbox.install_packages(["six"], timeout=120)
            assert result.exit_code == 0, f"install failed: stdout={result.stdout!r} stderr={result.stderr!r}"


@pytest.mark.skipif(
    not (LIVE and os.getenv("E2B_API_KEY")),
    reason="AK_TEST_SANDBOX_EGRESS=1 and E2B_API_KEY not set: the live egress gate runs against a real e2b account",
)
class TestE2BEgressAllowlistLive(EgressAllowlistContract):
    """The allowlist contract against a real E2B sandbox (default ``base`` template)."""

    def make_provider(self) -> SandboxProvider:
        from agentkernel.core.config import _SandboxE2BConfig
        from agentkernel.sandbox.providers.e2b import E2BSandboxProvider

        return E2BSandboxProvider(_SandboxE2BConfig())


@pytest.mark.skipif(
    not (LIVE and os.getenv("DAYTONA_API_KEY")),
    reason="AK_TEST_SANDBOX_EGRESS=1 and DAYTONA_API_KEY not set: the live egress gate runs against a real Daytona account",
)
class TestDaytonaEgressAllowlistLive(EgressAllowlistContract):
    """The allowlist contract against a real Daytona sandbox (default snapshot)."""

    def make_provider(self) -> SandboxProvider:
        from agentkernel.core.config import _SandboxDaytonaConfig
        from agentkernel.sandbox.providers.daytona import DaytonaSandboxProvider

        return DaytonaSandboxProvider(_SandboxDaytonaConfig())


# --------------------------------------------------------------------------- #
# The same contract against a local fake (always runs)
# --------------------------------------------------------------------------- #

_URL_HOST = re.compile(r"https?://([^/'\"]+)")


class _AllowlistSandbox(FakeSandbox):
    """Answers the probe as a perfectly enforced allowlist would; installs always succeed."""

    def __init__(self, sandbox_id: str, languages: list[str], allowed: list[str]) -> None:
        super().__init__(sandbox_id, languages)
        self._allowed = allowed

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        match = _URL_HOST.search(command)
        if match is None:
            return await super().execute_command(command, timeout)
        outcome = "REACHED" if match.group(1) in self._allowed else "BLOCKED"
        return SandboxResult(stdout=f"{outcome}\n", exit_code=0)

    async def install_packages(self, packages: list[str], ecosystem: str = "python", timeout: float | None = None) -> SandboxResult:
        return SandboxResult(stdout=f"installed {' '.join(packages)}", exit_code=0)


class _AllowlistProvider(FakeSandboxProvider):
    capabilities = FakeSandboxProvider.capabilities.derive(package_ecosystems=["python"], package_install=True)

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        base = await super().create(principal=principal, policy=policy)
        sandbox = _AllowlistSandbox(base.id, list(self.capabilities.languages), list(policy.network_allow))
        self._sandboxes[base.id] = sandbox
        return sandbox


class TestFakeEgressAllowlist(EgressAllowlistContract):
    """The contract body (probe, markers, teardown) against a fake that enforces the allowlist."""

    def make_provider(self) -> SandboxProvider:
        return _AllowlistProvider()
