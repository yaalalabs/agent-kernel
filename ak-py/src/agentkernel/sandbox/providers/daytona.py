"""``daytona`` provider — container sandboxes on the Daytona cloud (``daytona`` extra).

The SDK is synchronous, so every call runs in ``asyncio.to_thread``. Executions are
``process.code_run`` / ``process.exec``; files travel via ``fs.upload_file`` /
``fs.download_file``; ``install_packages`` is a ``pip install`` exec.

The sandbox base is configurable: ``daytona.image`` launches from a container image,
``daytona.snapshot`` from a named Daytona snapshot (mutually exclusive; neither = Daytona's
default snapshot), and ``daytona.env_vars`` sets environment variables inside it. The
profile's ``idle_timeout`` maps onto Daytona's native ``auto_stop_interval`` (minutes,
rounded up — spec §Idle timeout). Policy mapping: ``deny`` egress → ``network_block_all``;
``allowlist`` → ``network_allow_list`` (comma-separated CIDRs); cpu/memory → ``Resources``.
Daytona only attaches ``Resources`` to an **image-based** sandbox, so a resource policy
forces the image path (using ``daytona.image`` or the default ``python:3.12-slim``); a
resource policy against a configured ``snapshot`` is rejected as a conflict.

The API key is read from the environment variable named by ``api_key_env``.
"""

import asyncio
import logging
import math
import os
import shlex
from typing import Any, Optional

from daytona import (
    CreateSandboxFromImageParams,
    CreateSandboxFromSnapshotParams,
    Daytona,
    DaytonaConfig,
    Resources,
)
from daytona.common.errors import DaytonaError

from ..base import Sandbox, SandboxProvider
from ..errors import SandboxCapabilityError, SandboxConfigError, SandboxGoneError
from ..model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult

logger = logging.getLogger("ak.sandbox.provider")

_DEFAULT_IMAGE = "python:3.12-slim"


class DaytonaSandbox(Sandbox):
    """Handle to one running Daytona sandbox; every SDK call runs in a thread."""

    def __init__(self, sandbox: Any) -> None:
        """Bind the handle to the SDK sandbox object; the Daytona sandbox id is the sandbox id."""
        self.id = sandbox.id
        self._sandbox = sandbox

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        """Run the code via ``process.code_run``; a non-zero exit is data on the response."""
        if language not in DaytonaSandboxProvider.capabilities.languages:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        response = await asyncio.to_thread(self._sandbox.process.code_run, code, timeout=int(timeout) if timeout else None)
        return _to_result(response)

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        """Run a shell command via ``process.exec``."""
        response = await asyncio.to_thread(self._sandbox.process.exec, command, timeout=int(timeout) if timeout else None)
        return _to_result(response)

    async def install_packages(self, packages: list[str]) -> SandboxResult:
        """Install packages with pip via ``process.exec``."""
        return await self.execute_command("pip install " + " ".join(shlex.quote(p) for p in packages))

    async def upload_file(self, path: str, content: bytes) -> None:
        """Upload the bytes to the sandbox filesystem."""
        await asyncio.to_thread(self._sandbox.fs.upload_file, content, path)

    async def download_file(self, path: str) -> bytes:
        """Download the file bytes from the sandbox filesystem."""
        data = await asyncio.to_thread(self._sandbox.fs.download_file, path)
        if data is None:
            raise FileNotFoundError(path)
        return bytes(data)

    async def close(self) -> None:
        """Leave the sandbox running so a later ``attach`` can reconnect (Daytona's own
        ``auto_stop_interval`` reclaims it when idle). Idempotent."""
        return None


def _to_result(response: Any) -> SandboxResult:
    """Map a Daytona ``ExecuteResponse`` (merged output in ``result``) onto ``SandboxResult``."""
    exit_code = response.exit_code if response.exit_code is not None else -1
    output = response.result or ""
    # Daytona merges the streams; attribute stderr only on failure so exit 0 stays clean.
    return SandboxResult(
        stdout=output if exit_code == 0 else "",
        stderr="" if exit_code == 0 else output,
        exit_code=exit_code,
    )


class DaytonaSandboxProvider(SandboxProvider):
    """Container-per-sandbox provider over the synchronous Daytona SDK."""

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.CONTAINER,
        shell=True,
        languages=["python"],
        files=True,
        package_install=True,
        stateful=False,
        attach=True,
        principal_user=False,
        policy_network=True,  # deny -> network_block_all; allowlist -> network_allow_list CIDRs
        policy_filesystem=False,
        policy_resources=True,  # cpu/memory -> Resources on an image-based sandbox
    )

    def __init__(self, config, idle_timeout: Optional[float] = None) -> None:
        """Store the config and the profile's idle_timeout (mapped to auto_stop_interval);
        the Daytona client is created lazily on first use."""
        super().__init__(config)
        self._idle_timeout = idle_timeout
        self._client_instance: Optional[Daytona] = None

    def _client(self) -> Daytona:
        """Return the lazily created Daytona client, keyed from the configured env variable."""
        if self._client_instance is None:
            api_key = os.environ.get(self._config.api_key_env)
            if not api_key:
                raise SandboxConfigError(f"daytona provider requires the {self._config.api_key_env} environment variable")
            self._client_instance = Daytona(DaytonaConfig(api_key=api_key, target=self._config.target))
        return self._client_instance

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Create a sandbox with the policy mapped onto Daytona create params and the
        idle timeout passed through as ``auto_stop_interval``."""
        params = self._create_params(policy)
        sandbox = await asyncio.to_thread(self._client().create, params)
        return DaytonaSandbox(sandbox)

    def _create_params(self, policy: SandboxPolicy) -> Any:
        """Map the config's base (``image`` / ``snapshot``) and the ``SandboxPolicy`` onto
        Daytona create params.

        A sandbox launches from either an image or a snapshot, never both (enforced by config
        validation). Resource limits (cpu/memory) are only attachable to an **image-based**
        sandbox, so: an explicit ``image`` or a resource policy takes the image path (falling
        back to the default image when only resources force it); an explicit ``snapshot`` (or
        neither, using Daytona's default snapshot) takes the snapshot path. A resource policy
        against a configured ``snapshot`` is a genuine conflict and is rejected."""
        kwargs: dict = {"language": "python"}
        if self._config.env_vars:
            kwargs["env_vars"] = dict(self._config.env_vars)
        if self._idle_timeout is not None:
            kwargs["auto_stop_interval"] = max(1, math.ceil(self._idle_timeout / 60))
        if policy.network_egress == "deny":
            kwargs["network_block_all"] = True
        elif policy.network_egress == "allowlist":
            kwargs["network_allow_list"] = ",".join(policy.network_allow)

        has_resources = policy.cpu is not None or policy.memory_mb is not None
        if has_resources and self._config.snapshot:
            raise SandboxConfigError(
                "daytona: cpu/memory limits require an image-based sandbox, but this profile pins a 'snapshot'; "
                "use 'image' instead of 'snapshot', or drop the cpu/memory policy"
            )

        if self._config.image or has_resources:
            if has_resources:
                kwargs["resources"] = Resources(
                    cpu=max(1, math.ceil(policy.cpu)) if policy.cpu is not None else None,
                    memory=max(1, math.ceil(policy.memory_mb / 1024)) if policy.memory_mb is not None else None,
                )
            return CreateSandboxFromImageParams(image=self._config.image or _DEFAULT_IMAGE, **kwargs)

        if self._config.snapshot:
            kwargs["snapshot"] = self._config.snapshot
        return CreateSandboxFromSnapshotParams(**kwargs)

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Reattach to a sandbox by id; a missing sandbox raises ``SandboxGoneError``."""
        try:
            sandbox = await asyncio.to_thread(self._client().get, sandbox_id)
        except DaytonaError as exc:
            raise SandboxGoneError(f"daytona sandbox '{sandbox_id}' no longer exists") from exc
        return DaytonaSandbox(sandbox)

    async def destroy(self, sandbox_id: str) -> None:
        """Delete the sandbox. Idempotent; an already-gone sandbox is a no-op."""

        def remove() -> None:
            client = self._client()
            try:
                sandbox = client.get(sandbox_id)
            except DaytonaError:
                return
            client.delete(sandbox)

        await asyncio.to_thread(remove)
