"""``local_subprocess`` provider — zero-dependency local execution. NO isolation.

Each sandbox is a per-sandbox temporary working directory; each execution is a fresh
subprocess (``sys.executable -c`` for python, ``bash -c`` for bash/shell) started in its
own session so a timeout can kill the whole process group. File operations map onto the
working directory, and ``attach`` reconnects to it by path on the same host — which is
also what makes per-session persistence work across turns.

Development/test use only; never the factory default. Every policy dimension except
``timeout`` is undeclared, so a strict non-default policy fails closed in the worker.
"""

import asyncio
import logging
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

from ..base import Sandbox, SandboxProvider
from ..errors import SandboxCapabilityError, SandboxGoneError, SandboxPolicyError, SandboxTimeoutError
from ..model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult

logger = logging.getLogger("ak.sandbox.provider")

_TEMP_PREFIX = "ak-sandbox-"


class LocalSubprocessSandbox(Sandbox):
    """Handle to one local working directory; every execution is a fresh subprocess."""

    def __init__(self, workdir: Path) -> None:
        """Bind the handle to its working directory; the directory path is the sandbox id."""
        self.id = str(workdir)
        self._workdir = workdir

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        """Run ``code`` as ``sys.executable -c`` (python) or ``bash -c`` (bash)."""
        if language == "python":
            argv = [sys.executable, "-c", code]
        elif language == "bash":
            argv = ["bash", "-c", code]
        else:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        return await self._run(argv, timeout)

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        """Run a shell command via ``bash -c``."""
        return await self._run(["bash", "-c", command], timeout)

    async def _run(self, argv: list[str], timeout: float | None) -> SandboxResult:
        """Spawn the subprocess in the workdir (own session); on timeout kill the whole
        process group and raise ``SandboxTimeoutError``."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self._workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._kill_process_group(proc)
            await proc.wait()
            raise SandboxTimeoutError(f"subprocess exceeded timeout {timeout}s") from exc
        return SandboxResult(
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
        )

    @staticmethod
    def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
        """Best-effort SIGKILL of the subprocess's whole process group."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # already gone, or not ours to kill
            pass

    async def upload_file(self, path: str, content: bytes) -> None:
        """Write ``content`` under the working directory (parents created as needed)."""
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def download_file(self, path: str) -> bytes:
        """Read a file from the working directory; missing paths raise ``FileNotFoundError``."""
        target = self._resolve(path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return target.read_bytes()

    def _resolve(self, path: str) -> Path:
        """Map a sandbox path onto the working directory, refusing traversal escapes."""
        candidate = (self._workdir / path.lstrip("/")).resolve()
        if not candidate.is_relative_to(self._workdir.resolve()):
            raise SandboxPolicyError(f"path '{path}' escapes the sandbox working directory")
        return candidate

    async def close(self) -> None:
        """No live handle to release (each execution is its own process); the working
        directory persists for a later attach. Idempotent."""
        return None


class LocalSubprocessSandboxProvider(SandboxProvider):
    """Stdlib-only provider: temp-dir sandboxes with fresh-subprocess execution."""

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.NONE,
        shell=True,
        languages=["python", "bash"],
        files=True,
        package_install=False,
        stateful=False,
        attach=True,  # same-host reconnect to the working directory by path
        principal_user=False,
        policy_network=False,
        policy_filesystem=False,
        policy_resources=False,
    )

    def __init__(self, config) -> None:
        """Store the config and log the mandatory no-isolation warning."""
        super().__init__(config)
        logger.warning("local_subprocess provides NO isolation: development/test use only")

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Create a fresh per-sandbox temp directory (under ``workdir`` when configured)."""
        base = self._config.workdir
        if base:
            Path(base).mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir=base))
        return LocalSubprocessSandbox(workdir)

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Reconnect to an existing working directory by path (same host only);
        a missing directory raises ``SandboxGoneError``."""
        workdir = Path(sandbox_id)
        if not workdir.is_dir():
            raise SandboxGoneError(f"sandbox working directory '{sandbox_id}' no longer exists")
        return LocalSubprocessSandbox(workdir)

    async def destroy(self, sandbox_id: str) -> None:
        """Remove the working directory. Idempotent; only paths this provider minted
        (``ak-sandbox-`` prefix) are ever deleted."""
        path = Path(sandbox_id)
        if path.name.startswith(_TEMP_PREFIX) and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
