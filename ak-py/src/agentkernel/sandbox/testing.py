"""Public testing helpers for sandbox providers.

Two things live here, both importable by bring-your-own-backend authors:

* ``FakeSandboxProvider`` — a dependency-free, in-memory ``SandboxProvider`` used across the
  test suite as a reference backend.
* ``SandboxProviderContract`` — a reusable pytest suite asserting the ABC semantics every
  provider must honor. Subclass it in a test module and override the ``provider`` fixture; it
  is deliberately NOT named ``Test*`` so pytest does not collect it on its own.

This module imports ``pytest`` and is therefore only meant to be imported from test code — it
is intentionally left out of ``agentkernel.sandbox``'s eager exports so ``import
agentkernel.sandbox`` stays free of a pytest dependency.
"""

import uuid
from typing import Optional

import pytest
from pydantic import BaseModel

from .base import Sandbox, SandboxProvider
from .errors import SandboxCapabilityError, SandboxGoneError
from .model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult

# execute_code / execute_command treat code containing this marker as a program that exits
# non-zero (returned as data, never raised). As a bare Python statement it is also an
# undefined name, so it is a genuine non-zero exit for real python backends too.
FAIL_MARKER = "__nonzero_exit__"


class _EmptyConfig(BaseModel):
    """Placeholder config for FakeSandboxProvider (it reads no configuration)."""


class FakeSandbox(Sandbox):
    """In-memory sandbox handle backing ``FakeSandboxProvider``."""

    def __init__(self, sandbox_id: str, languages: list[str]) -> None:
        self.id = sandbox_id
        self._languages = languages
        self._files: dict[str, bytes] = {}
        self.closed = False

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        if language not in self._languages:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        if FAIL_MARKER in code:
            return SandboxResult(stderr="simulated non-zero exit", exit_code=1)
        return SandboxResult(stdout=code, exit_code=0)

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        if FAIL_MARKER in command:
            return SandboxResult(stderr="simulated non-zero exit", exit_code=1)
        return SandboxResult(stdout=command, exit_code=0)

    async def upload_file(self, path: str, content: bytes) -> None:
        self._files[path] = content

    async def download_file(self, path: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]

    # install_packages is intentionally NOT overridden: package_install is declared False,
    # so the base ABC raises SandboxCapabilityError — capability honesty in action.

    async def close(self) -> None:
        self.closed = True  # idempotent


class FakeSandboxProvider(SandboxProvider):
    """Dependency-free reference provider for tests.

    Declares a deliberate mix of capabilities (shell/files/attach on, package_install off) so
    the contract exercises both the "supported" and the "raises" branches.
    """

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.NONE,
        shell=True,
        languages=["python", "bash"],
        files=True,
        package_install=False,
        stateful=True,
        attach=True,
        principal_user=False,
        policy_network=False,
        policy_filesystem=False,
        policy_resources=False,
    )

    def __init__(self, config: Optional[BaseModel] = None) -> None:
        super().__init__(config if config is not None else _EmptyConfig())
        self._sandboxes: dict[str, FakeSandbox] = {}
        self.created_ids: list[str] = []
        self.destroyed_ids: list[str] = []

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        sandbox_id = uuid.uuid4().hex
        sandbox = FakeSandbox(sandbox_id, list(self.capabilities.languages))
        self._sandboxes[sandbox_id] = sandbox
        self.created_ids.append(sandbox_id)
        return sandbox

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            raise SandboxGoneError(f"sandbox {sandbox_id} no longer exists")
        sandbox.closed = False
        return sandbox

    async def destroy(self, sandbox_id: str) -> None:
        self._sandboxes.pop(sandbox_id, None)  # idempotent; unknown ids are a no-op
        self.destroyed_ids.append(sandbox_id)


class SandboxProviderContract:
    """Reusable contract suite asserting ``SandboxProvider``/``Sandbox`` ABC semantics.

    Subclass in a test module and override the ``provider`` fixture::

        class TestMyProviderContract(SandboxProviderContract):
            @pytest.fixture
            def provider(self):
                return MyProvider(my_config)

    Not collected on its own — the class name is intentionally not prefixed ``Test``.
    """

    def failing_program(self) -> tuple[str, str]:
        """Return ``(code, language)`` this provider runs to a non-zero exit WITHOUT raising.

        The default is an undefined-name Python statement, which is a non-zero exit for any
        real Python backend and for ``FakeSandboxProvider``. Override per provider if needed.
        """
        return (FAIL_MARKER, "python")

    @pytest.fixture
    def provider(self) -> SandboxProvider:
        raise NotImplementedError("subclasses must override the `provider` fixture")

    @pytest.fixture
    def principal_policy(self) -> tuple[SandboxPrincipal, SandboxPolicy]:
        return SandboxPrincipal(subject="contract-agent"), SandboxPolicy()

    @pytest.mark.asyncio
    async def test_contract_execute_code_python_is_mandatory(self, provider, principal_policy):
        principal, policy = principal_policy
        sandbox = await provider.create(principal=principal, policy=policy)
        try:
            result = await sandbox.execute_code("print('hi')", "python")
            assert isinstance(result, SandboxResult)
            assert result.exit_code == 0
        finally:
            await sandbox.close()

    @pytest.mark.asyncio
    async def test_contract_undeclared_language_raises(self, provider, principal_policy):
        principal, policy = principal_policy
        undeclared = "definitely-not-a-language"
        assert undeclared not in provider.capabilities.languages
        sandbox = await provider.create(principal=principal, policy=policy)
        try:
            with pytest.raises(SandboxCapabilityError):
                await sandbox.execute_code("noop", undeclared)
        finally:
            await sandbox.close()

    @pytest.mark.asyncio
    async def test_contract_capability_honesty(self, provider, principal_policy):
        principal, policy = principal_policy
        caps = provider.capabilities
        sandbox = await provider.create(principal=principal, policy=policy)
        try:
            if caps.shell:
                assert isinstance(await sandbox.execute_command("echo hi"), SandboxResult)
            else:
                with pytest.raises(SandboxCapabilityError):
                    await sandbox.execute_command("echo hi")

            if caps.files:
                await sandbox.upload_file("f.txt", b"data")
                assert await sandbox.download_file("f.txt") == b"data"
            else:
                with pytest.raises(SandboxCapabilityError):
                    await sandbox.upload_file("f.txt", b"data")
                with pytest.raises(SandboxCapabilityError):
                    await sandbox.download_file("f.txt")

            if caps.package_install:
                assert isinstance(await sandbox.install_packages(["pip-noop"]), SandboxResult)
            else:
                with pytest.raises(SandboxCapabilityError):
                    await sandbox.install_packages(["pip-noop"])
        finally:
            await sandbox.close()

    @pytest.mark.asyncio
    async def test_contract_program_failure_is_result_not_exception(self, provider, principal_policy):
        principal, policy = principal_policy
        code, language = self.failing_program()
        sandbox = await provider.create(principal=principal, policy=policy)
        try:
            result = await sandbox.execute_code(code, language)
            assert isinstance(result, SandboxResult)
            assert result.exit_code != 0
        finally:
            await sandbox.close()

    @pytest.mark.asyncio
    async def test_contract_close_is_idempotent(self, provider, principal_policy):
        principal, policy = principal_policy
        sandbox = await provider.create(principal=principal, policy=policy)
        await sandbox.close()
        await sandbox.close()  # second close must not raise

    @pytest.mark.asyncio
    async def test_contract_destroy_is_idempotent(self, provider, principal_policy):
        principal, policy = principal_policy
        sandbox = await provider.create(principal=principal, policy=policy)
        await provider.destroy(sandbox.id)
        await provider.destroy(sandbox.id)  # repeat is a no-op
        await provider.destroy("unknown-sandbox-id")  # unknown id is a no-op

    @pytest.mark.asyncio
    async def test_contract_attach_honesty(self, provider, principal_policy):
        principal, policy = principal_policy
        if provider.capabilities.attach:
            sandbox = await provider.create(principal=principal, policy=policy)
            reattached = await provider.attach(sandbox.id, principal=principal, policy=policy)
            assert isinstance(reattached, Sandbox)
            with pytest.raises(SandboxGoneError):
                await provider.attach("nonexistent-id", principal=principal, policy=policy)
        else:
            with pytest.raises(SandboxCapabilityError):
                await provider.attach("whatever", principal=principal, policy=policy)
