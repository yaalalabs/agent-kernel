"""``e2b`` provider — managed Firecracker micro-VM sandboxes via the E2B cloud (``e2b`` extra).

Uses the native async SDK (``e2b-code-interpreter``): ``AsyncSandbox.create`` /
``AsyncSandbox.connect(id)``; ``run_code`` executes in a persistent Jupyter kernel
(``stateful=True`` — variables survive across calls), ``commands.run`` covers shell and the
validated installer command from ``package_installers``, and the sandbox filesystem backs the
file operations.

The profile's ``idle_timeout`` is passed as the sandbox ``timeout`` at create, so E2B
auto-kills idle sandboxes natively (spec §Idle timeout). Policy mapping: ``deny`` egress
becomes ``allow_internet_access=False``; an ``allowlist`` becomes the sandbox network
``allow_out`` rules — both genuinely enforced by the E2B plane. cpu/memory are fixed by
the E2B tier (unenforceable → ``policy_resources=False``).

The API key is read from the environment variable named by ``api_key_env`` and passed
explicitly on every SDK call.
"""

import logging
import os
import time
from typing import Optional

from e2b.exceptions import NotFoundException, TimeoutException
from e2b.sandbox.commands.command_handle import CommandExitException
from e2b_code_interpreter import AsyncSandbox

from ..base import Sandbox, SandboxProvider
from ..errors import SandboxCapabilityError, SandboxConfigError, SandboxError, SandboxGoneError, SandboxTimeoutError
from ..model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult
from ..packages import PackageInstaller

logger = logging.getLogger("ak.sandbox.provider")


class E2BSandbox(Sandbox):
    """Handle to one running E2B sandbox; executions run in its persistent kernel."""

    def __init__(self, sandbox: AsyncSandbox, *, capabilities: SandboxCapabilities, installer: PackageInstaller) -> None:
        """Bind the handle to the SDK sandbox object; the E2B sandbox id is the sandbox id.
        ``capabilities`` are the provider instance's."""
        self.id = sandbox.sandbox_id
        self._sandbox = sandbox
        self._capabilities = capabilities
        self._installer = installer

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        """Run the code in the sandbox's Jupyter kernel; an execution error is a non-zero result.
        The SDK's native timeout raises ``SandboxTimeoutError`` (see ``_timeout_error``)."""
        if language not in self._capabilities.languages:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        started = time.monotonic()
        try:
            execution = await self._sandbox.run_code(code, timeout=timeout)
        except TimeoutException as exc:
            raise self._timeout_error(exc, started, timeout, "code execution") from exc
        stderr = "".join(execution.logs.stderr)
        if execution.error is not None:
            stderr = stderr + ("\n" if stderr else "") + f"{execution.error.name}: {execution.error.value}"
        return SandboxResult(
            stdout="".join(execution.logs.stdout),
            stderr=stderr,
            exit_code=0 if execution.error is None else 1,
        )

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        """Run a shell command; the SDK raises on non-zero exit, which is converted back to a result.
        The SDK's native timeout raises ``SandboxTimeoutError`` (see ``_timeout_error``)."""
        started = time.monotonic()
        try:
            result = await self._sandbox.commands.run(command, timeout=timeout)
        except CommandExitException as exc:  # non-zero exit is data, not an error (ABC contract)
            return SandboxResult(stdout=exc.stdout, stderr=exc.stderr, exit_code=exc.exit_code)
        except TimeoutException as exc:
            raise self._timeout_error(exc, started, timeout, "command") from exc
        return SandboxResult(stdout=result.stdout, stderr=result.stderr, exit_code=result.exit_code)

    @staticmethod
    def _timeout_error(exc: TimeoutException, started: float, timeout: float | None, what: str) -> SandboxError:
        """``SandboxTimeoutError`` when the call ran for its whole timeout (the SDK's native timeout
        fired). The SDK's ``TimeoutException`` also covers the sandbox's own lifetime expiring, a
        paused or shut-down sandbox, and request timeouts; those are not the execution's timeout and
        stay a plain ``SandboxError`` carrying the SDK's message. Decided by elapsed time, not by
        the SDK's message text, which changes between versions."""
        if timeout is not None and time.monotonic() - started >= timeout:
            return SandboxTimeoutError(f"e2b {what} exceeded timeout {timeout}s")
        return SandboxError(f"e2b {what} failed: {exc}")

    async def install_packages(self, packages: list[str], ecosystem: str = "python", timeout: float | None = None) -> SandboxResult:
        """Run the ecosystem's validated installer command, under the SDK's native command timeout."""
        if ecosystem not in self._capabilities.package_ecosystems:
            raise SandboxCapabilityError(self.__class__.__name__, f"package_ecosystem:{ecosystem}")
        return await self.execute_command(self._installer.command(packages, ecosystem), timeout)

    async def upload_file(self, path: str, content: bytes) -> None:
        """Write the bytes to the sandbox filesystem."""
        await self._sandbox.files.write(path, content)

    async def download_file(self, path: str) -> bytes:
        """Read the file bytes from the sandbox filesystem."""
        data = await self._sandbox.files.read(path, format="bytes")
        return bytes(data)

    async def close(self) -> None:
        """Leave the sandbox running so a later ``attach`` can reconnect (E2B's own
        ``timeout`` reclaims it when idle). Idempotent."""
        return None


class E2BSandboxProvider(SandboxProvider):
    """Micro-VM-per-sandbox provider over the E2B async SDK."""

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.MICRO_VM,
        shell=True,
        languages=["python"],
        files=True,
        package_ecosystems=["python"],  # the default; each instance declares its package_installers keys
        stateful=True,  # Jupyter-kernel model — variables persist across execute_code calls
        attach=True,
        principal_user=False,
        policy_network=True,  # deny -> allow_internet_access=False; allowlist -> network allow_out rules
        policy_filesystem=False,
        policy_resources=False,  # cpu/memory are fixed by the E2B tier
    )

    def __init__(self, config, idle_timeout: Optional[float] = None) -> None:
        """Store the config and the profile's idle_timeout (passed as the native sandbox timeout),
        and build the installer that sets this instance's package ecosystems."""
        super().__init__(config)
        self._idle_timeout = idle_timeout
        self._installer = PackageInstaller.from_config(config)
        self.capabilities = type(self).capabilities.derive(package_ecosystems=self._installer.ecosystems)

    def _handle(self, sandbox: AsyncSandbox) -> E2BSandbox:
        """Wrap an SDK sandbox in a handle carrying this instance's capabilities and installer."""
        return E2BSandbox(sandbox, capabilities=self.capabilities, installer=self._installer)

    def _api_key(self) -> str:
        """Read the API key from the configured environment variable; missing fails loud."""
        api_key = os.environ.get(self._config.api_key_env)
        if not api_key:
            raise SandboxConfigError(f"e2b provider requires the {self._config.api_key_env} environment variable")
        return api_key

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Create a sandbox from the configured template with the policy mapped onto
        E2B create options and the idle timeout passed through natively."""
        kwargs: dict = {"template": self._config.template, "api_key": self._api_key()}
        if self._idle_timeout is not None:
            kwargs["timeout"] = int(self._idle_timeout)
        if policy.network_egress == "deny":
            kwargs["allow_internet_access"] = False
        elif policy.network_egress == "allowlist":
            kwargs["network"] = {"allow_out": list(policy.network_allow)}
        sandbox = await AsyncSandbox.create(**kwargs)
        return self._handle(sandbox)

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Reconnect to a running sandbox by id; a missing sandbox raises ``SandboxGoneError``."""
        try:
            sandbox = await AsyncSandbox.connect(sandbox_id, api_key=self._api_key())
        except NotFoundException as exc:
            raise SandboxGoneError(f"e2b sandbox '{sandbox_id}' no longer exists") from exc
        return self._handle(sandbox)

    async def destroy(self, sandbox_id: str) -> None:
        """Kill the sandbox. Idempotent; an already-gone sandbox is a no-op."""
        try:
            await AsyncSandbox.kill(sandbox_id, api_key=self._api_key())
        except NotFoundException:
            pass
