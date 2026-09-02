"""``docker`` provider — container-per-sandbox via the Docker SDK (``sandbox-docker`` extra).

Each sandbox is a detached container running ``sleep infinity``; executions are
``exec_run`` calls of the language interpreter, files travel via ``put_archive`` /
``get_archive`` under the ``/workspace`` working directory, and ``install_packages`` is a
``pip install`` exec. The SDK is synchronous, so every call runs in ``asyncio.to_thread``.

``close()`` leaves the container running (that is what makes reattach work);
``destroy()`` is ``remove(force=True)``. Policy mapping: ``deny`` egress becomes
``network_mode="none"`` (an allowlist is unenforceable and fails closed under
``strict``); cpu/memory become container limits; filesystem restrictions become a
read-only rootfs with a writable tmpfs workdir.
"""

import asyncio
import io
import logging
import posixpath
import tarfile
from typing import Optional

import docker

from ..base import Sandbox, SandboxProvider
from ..errors import SandboxCapabilityError, SandboxGoneError, SandboxPolicyError, SandboxTimeoutError
from ..model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult

logger = logging.getLogger("ak.sandbox.provider")

WORKDIR = "/workspace"


def _safe_rel(path: str) -> str:
    """Resolve a caller path to a WORKDIR-relative POSIX path: an absolute path is treated
    as workdir-relative (its leading ``/`` is stripped), and ``..`` traversal that would
    escape the workdir is rejected (mirrors the local_subprocess escape check)."""
    rel = path.lstrip("/")
    resolved = posixpath.normpath(posixpath.join(WORKDIR, rel))
    if resolved != WORKDIR and not resolved.startswith(WORKDIR + "/"):
        raise SandboxPolicyError(f"path '{path}' escapes the sandbox working directory")
    return posixpath.relpath(resolved, WORKDIR)


class DockerSandbox(Sandbox):
    """Handle to one running container; executions are ``exec_run`` calls inside it."""

    def __init__(self, container) -> None:
        """Bind the handle to a Docker SDK container object; the container id is the sandbox id."""
        self.id = container.id
        self._container = container

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        """Exec the language interpreter with the code (``python -c`` in v1)."""
        if language not in DockerSandboxProvider.capabilities.languages:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        return await self._exec(["python", "-c", code], timeout)

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        """Exec a shell command via ``/bin/sh -c``."""
        return await self._exec(["/bin/sh", "-c", command], timeout)

    async def install_packages(self, packages: list[str]) -> SandboxResult:
        """Exec ``pip install`` for the given packages."""
        return await self._exec(["pip", "install", *packages], None)

    async def _exec(self, argv: list[str], timeout: float | None) -> SandboxResult:
        """Run ``exec_run`` in a thread under ``asyncio.wait_for``; on expiry make a
        best-effort kill of the exec'd process and raise ``SandboxTimeoutError``."""

        def run():
            return self._container.exec_run(argv, workdir=WORKDIR, demux=True)

        try:
            exec_result = await asyncio.wait_for(asyncio.to_thread(run), timeout=timeout)
        except asyncio.TimeoutError as exc:
            await self._best_effort_kill(argv[0])
            raise SandboxTimeoutError(f"docker exec exceeded timeout {timeout}s") from exc
        stdout, stderr = exec_result.output if exec_result.output is not None else (b"", b"")
        return SandboxResult(
            stdout=(stdout or b"").decode(errors="replace"),
            stderr=(stderr or b"").decode(errors="replace"),
            exit_code=exec_result.exit_code if exec_result.exit_code is not None else -1,
        )

    async def _best_effort_kill(self, interpreter: str) -> None:
        """Kill the timed-out exec'd process by interpreter name. Safe because the
        concurrency contract allows at most one in-flight execution per sandbox."""
        try:
            await asyncio.to_thread(self._container.exec_run, ["pkill", "-9", posixpath.basename(interpreter)])
        except Exception as exc:  # noqa: BLE001 — the kill is best-effort by contract
            logger.warning("Best-effort kill in container %s failed: %s", self.id, exc)

    async def upload_file(self, path: str, content: bytes) -> None:
        """Ship the file into the container workdir as a single-member tar via ``put_archive``."""
        rel = _safe_rel(path)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=rel)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        await asyncio.to_thread(self._container.put_archive, WORKDIR, buf.getvalue())

    async def download_file(self, path: str) -> bytes:
        """Fetch the file from the container workdir via ``get_archive`` and untar it."""
        target = posixpath.join(WORKDIR, _safe_rel(path))

        def fetch() -> bytes:
            bits, _stat = self._container.get_archive(target)
            return b"".join(bits)

        data = await asyncio.to_thread(fetch)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    return tar.extractfile(member).read()
        raise FileNotFoundError(path)

    async def close(self) -> None:
        """Leave the container running so a later ``attach`` can reconnect. Idempotent."""
        return None


class DockerSandboxProvider(SandboxProvider):
    """Container-per-sandbox provider over the synchronous Docker SDK."""

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.CONTAINER,
        shell=True,
        languages=["python"],
        files=True,
        package_install=True,
        stateful=False,
        attach=True,
        attaches_external=True,  # attach_to binds to a container the framework did not create
        principal_user=False,
        policy_network=True,  # deny -> network_mode="none"; allowlist is unenforceable (fails closed under strict)
        policy_filesystem=True,  # coarse: read-only rootfs + writable tmpfs workdir
        policy_resources=True,
    )

    def __init__(self, config) -> None:
        """Store the config; the Docker client is created lazily on first use."""
        super().__init__(config)
        self._client_instance: Optional["docker.DockerClient"] = None

    def _client(self):
        """Return the lazily created Docker client (``docker.from_env()``)."""
        if self._client_instance is None:
            self._client_instance = docker.from_env()
        return self._client_instance

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Start a ``sleep infinity`` container with the policy mapped onto container
        options; with ``attach_to`` configured, attach to that container instead (mode 3)."""
        if self._config.attach_to:
            return await self.attach(self._config.attach_to, principal=principal, policy=policy)
        kwargs = self._container_kwargs(policy)
        container = await asyncio.to_thread(self._client().containers.run, self._config.image, **kwargs)
        return DockerSandbox(container)

    def _container_kwargs(self, policy: SandboxPolicy) -> dict:
        """Map the ``SandboxPolicy`` onto ``containers.run`` keyword arguments."""
        kwargs: dict = {"command": ["sleep", "infinity"], "detach": True, "working_dir": WORKDIR}
        if self._config.runtime and self._config.runtime != "docker":
            kwargs["runtime"] = self._config.runtime
        if policy.network_egress == "deny":
            kwargs["network_mode"] = "none"
        elif policy.network_egress == "allowlist":
            if policy.strict:
                raise SandboxPolicyError("docker cannot enforce a network egress allowlist; use 'deny' or 'allow', or set strict=false")
            logger.warning("docker cannot enforce a network egress allowlist; proceeding with unrestricted egress because strict=false")
        if policy.cpu is not None:
            kwargs["nano_cpus"] = int(policy.cpu * 1_000_000_000)
        if policy.memory_mb is not None:
            kwargs["mem_limit"] = f"{policy.memory_mb}m"
        if policy.fs_allow_read or policy.fs_allow_write:
            kwargs["read_only"] = True
            kwargs["tmpfs"] = {WORKDIR: ""}
        return kwargs

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Reattach to a container by id, starting it if stopped; a missing container
        raises ``SandboxGoneError`` (the self-heal signal)."""

        def fetch():
            try:
                container = self._client().containers.get(sandbox_id)
            except docker.errors.NotFound as exc:
                raise SandboxGoneError(f"container '{sandbox_id}' no longer exists") from exc
            if getattr(container, "status", "running") != "running":
                container.start()
            return container

        return DockerSandbox(await asyncio.to_thread(fetch))

    async def destroy(self, sandbox_id: str) -> None:
        """``remove(force=True)`` the container. Idempotent; unknown ids are a no-op."""

        def remove():
            try:
                self._client().containers.get(sandbox_id).remove(force=True)
            except docker.errors.NotFound:
                pass

        await asyncio.to_thread(remove)
