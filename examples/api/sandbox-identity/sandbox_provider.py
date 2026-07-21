"""A bring-your-own sandbox provider that makes the acting identity observable.

Real user-identity providers (kubernetes impersonation, bedrock_agentcore / ec2_ssm via
``sts:AssumeRole``) need cloud infrastructure to demonstrate. To show the end-to-end identity
flow with no external services, this demo provider declares ``principal_user = True`` and runs
code locally with the caller's identity exposed as the ``SANDBOX_PRINCIPAL`` environment
variable — so the same code, run for different users, observably runs *as* different users.

It is wired by config as a dotted path (`sandbox_provider.DemoIdentitySandboxProvider`) — the
same bring-your-own mechanism any third-party provider uses.

NOT for production: like ``local_subprocess`` it provides no isolation.
"""

import asyncio
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from agentkernel.sandbox import Sandbox, SandboxProvider
from agentkernel.sandbox.errors import SandboxCapabilityError, SandboxGoneError, SandboxTimeoutError
from agentkernel.sandbox.model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult
from pydantic import BaseModel

_LANGUAGES = ["python", "bash"]


class DemoIdentitySandbox(Sandbox):
    """Runs code in a temp dir with SANDBOX_PRINCIPAL set to the acting identity."""

    def __init__(self, workdir: Path, principal_subject: str) -> None:
        self.id = str(workdir)
        self._workdir = workdir
        self._principal = principal_subject

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        # Honor the ABC contract: an undeclared language fails loud (a typo like "pyhton"
        # must not silently run under bash).
        if language not in _LANGUAGES:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        argv = [sys.executable, "-c", code] if language == "python" else ["bash", "-c", code]
        return await self._run(argv, timeout)

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        return await self._run(["bash", "-c", command], timeout)

    async def _run(self, argv: list[str], timeout: float | None) -> SandboxResult:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self._workdir,
            env={"SANDBOX_PRINCIPAL": self._principal, "PATH": "/usr/bin:/bin:/usr/local/bin"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            # Kill the timed-out process and reap it so it doesn't leak or hang shutdown.
            proc.kill()
            await proc.wait()
            raise SandboxTimeoutError(f"execution exceeded timeout {timeout}s") from exc
        return SandboxResult(
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
        )

    async def close(self) -> None:
        return None


class DemoIdentitySandboxProvider(SandboxProvider):
    """Demo provider that supports user identity and exposes it to executed code."""

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.NONE,
        shell=True,
        languages=["python", "bash"],
        files=False,
        attach=True,  # per_session reuse re-acquires via attach(); must be declared (capability honesty)
        principal_user=True,  # this is what lets a user-mode profile run instead of failing closed
    )

    def __init__(self, config: BaseModel) -> None:
        # The factory always passes a Pydantic config (this provider's params via a permissive
        # model). Follow the real SandboxProvider contract so the example is copy/paste-safe,
        # even though this demo reads nothing from it.
        super().__init__(config)
        self._sandboxes: dict[str, DemoIdentitySandbox] = {}

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        # The principal resolved from the request identity is handed to the provider here —
        # this is where a cloud provider would assume the role / set impersonation.
        workdir = Path(tempfile.mkdtemp(prefix="ak-demo-identity-"))
        sandbox = DemoIdentitySandbox(workdir, principal.subject)
        self._sandboxes[sandbox.id] = sandbox
        return sandbox

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            raise SandboxGoneError(f"sandbox {sandbox_id} no longer exists")
        return sandbox

    async def destroy(self, sandbox_id: str) -> None:
        self._sandboxes.pop(sandbox_id, None)
        path = Path(sandbox_id)
        if path.name.startswith("ak-demo-identity-") and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
