"""``BrokerWorkerCore`` — the flavor-independent sandbox execution engine.

Every broker flavor (embedded, thread, ECS, Lambda) drives the same engine to turn one
``SandboxBrokerRequest`` into a result. Two entry points:

* ``run`` — executes and returns ``(SandboxResult, SandboxSession)``, raising ``SandboxError``
  on any machinery/policy failure. In-process flavors that report synchronously use this so
  the real exception reaches the caller.
* ``process`` — the terminal-guarantee wrapper for asynchronous flavors: never raises, always
  returns a ``SandboxCompletion`` (a failure becomes a ``failed``/``timed_out`` completion).
"""

import asyncio
import logging
import time
from typing import Optional

from ...core.config import AKConfig
from ..base import SandboxProvider
from ..errors import (
    SandboxCapabilityError,
    SandboxConfigError,
    SandboxError,
    SandboxGoneError,
    SandboxPolicyError,
    SandboxTimeoutError,
)
from ..factory import SandboxProviderFactory
from ..model import SandboxFile, SandboxResult, SandboxSession
from .base import SandboxBrokerRequest, SandboxCompletion

logger = logging.getLogger("ak.sandbox.broker")


class BrokerWorkerCore:
    """Processes one request against the resolved provider, serialized per sandbox session."""

    def __init__(self, *, inline_payload_max_bytes: Optional[int] = None) -> None:
        """Create an engine instance. ``inline_payload_max_bytes`` is the offload threshold
        for flavors that support it (``None`` for in-process flavors, which never offload)."""
        self._inline_max = inline_payload_max_bytes
        self._locks: dict[str, asyncio.Lock] = {}  # per sandbox_session_id
        self._policy_warned: set[tuple[str, str]] = set()  # process-lifetime memo per (provider, profile)

    def _lock_for(self, sandbox_session_id: str) -> asyncio.Lock:
        """Return (creating on first use) the lock serializing operations per sandbox session."""
        lock = self._locks.get(sandbox_session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[sandbox_session_id] = lock
        return lock

    async def run(self, request: SandboxBrokerRequest) -> tuple[SandboxResult, SandboxSession]:
        """Execute one request and return ``(result, updated session)``.

        Raises the real ``SandboxError`` on any machinery/policy failure, so synchronous
        (in-process) flavors surface the true exception type to the caller. Steps follow
        the spec: resolve provider, fail-closed checks, attach-or-create with self-heal,
        serialize per session, execute under the effective timeout.
        """
        # 1. Resolve profile -> provider.
        provider = SandboxProviderFactory.get(request.profile)
        if provider is None:
            raise SandboxConfigError("sandbox capability is disabled")

        session = request.sandbox_session

        # Teardown short-circuits before the fail-closed checks — it never executes code.
        if request.operation == "destroy":
            if session.sandbox_id:
                await provider.destroy(session.sandbox_id)
            session.status = "closed"
            session.sandbox_id = None
            return SandboxResult(sandbox_session_id=session.sandbox_session_id), session

        # 2. Fail-closed checks: principal, then policy (before any provider call).
        self._check_principal(provider, request)
        self._enforce_policy(provider, request)

        async with self._lock_for(session.sandbox_session_id):
            # 3. Attach-or-create with self-heal.
            sandbox, recreated = await self._acquire(provider, request)
            session.sandbox_id = sandbox.id
            session.last_used_at = time.time()
            # 4 (serialize, above) + 5. Execute under the effective timeout.
            result = await self._execute(sandbox, request)

        # 6. Stamp the session id; in-process flavors never offload.
        result.sandbox_session_id = session.sandbox_session_id
        if recreated and result.notice is None:
            result.notice = (
                f"the sandbox behind session '{session.sandbox_session_id}' no longer existed and was recreated empty; "
                "its previous workspace state is gone"
            )
        return result, session

    async def process(self, request: SandboxBrokerRequest) -> SandboxCompletion:
        """Terminal-guarantee wrapper: always returns a completion, never raises (step 8)."""
        try:
            result, session = await self.run(request)
            return SandboxCompletion(task_id=request.task_id, status="succeeded", result=result, sandbox_session=session)
        except SandboxTimeoutError as exc:
            logger.warning("Sandbox task %s timed out: %s", request.task_id, exc)
            return SandboxCompletion(task_id=request.task_id, status="timed_out", error=str(exc), sandbox_session=request.sandbox_session)
        except Exception as exc:  # noqa: BLE001 — terminal guarantee: never end a task without a completion
            logger.warning("Sandbox task %s failed: %s", request.task_id, exc)
            return SandboxCompletion(task_id=request.task_id, status="failed", error=str(exc), sandbox_session=request.sandbox_session)

    # -- internals ---------------------------------------------------------- #

    def _check_principal(self, provider: SandboxProvider, request: SandboxBrokerRequest) -> None:
        """Fail closed on user identity: a ``user``-mode profile requires both a provider
        that declares ``principal_user`` and a resolver that actually produced a user
        principal; otherwise raise before any provider call."""
        profile_cfg = AKConfig.get().sandbox.profiles.get(request.profile)
        desired_mode = profile_cfg.identity.mode if profile_cfg is not None else "agent"
        if desired_mode != "user":
            return
        if not provider.capabilities.principal_user:
            raise SandboxCapabilityError(type(provider).__name__, "principal_user")
        if request.principal.mode != "user":
            raise SandboxPolicyError(
                f"profile '{request.profile}' requires user identity, but the resolver returned an agent-mode principal; "
                "no user identity is available on the session"
            )

    def _enforce_policy(self, provider: SandboxProvider, request: SandboxBrokerRequest) -> None:
        """Check every non-default policy dimension against the provider's declared
        ``policy_*`` capabilities: unenforceable under ``strict`` raises
        ``SandboxPolicyError`` listing all of them; non-strict proceeds with one WARNING
        per (provider, profile) for the process lifetime."""
        caps = provider.capabilities
        policy = request.policy
        unenforceable: list[str] = []
        if policy.network_egress != "allow" and not caps.policy_network:
            unenforceable.append("network_egress")
        if (policy.fs_allow_read or policy.fs_allow_write) and not caps.policy_filesystem:
            unenforceable.append("filesystem")
        if (policy.cpu is not None or policy.memory_mb is not None) and not caps.policy_resources:
            unenforceable.append("resources")
        # policy.timeout is always enforceable (framework-side asyncio.wait_for) — never listed.
        if not unenforceable:
            return
        if policy.strict:
            raise SandboxPolicyError(
                f"provider '{type(provider).__name__}' cannot enforce policy dimensions {unenforceable} (strict); "
                "relax the policy or set strict=false"
            )
        memo = (type(provider).__name__, request.profile)
        if memo not in self._policy_warned:
            self._policy_warned.add(memo)
            logger.warning(
                "Sandbox provider %s (profile %s) cannot enforce policy dimensions %s; proceeding because strict=false",
                type(provider).__name__,
                request.profile,
                unenforceable,
            )

    async def _acquire(self, provider: SandboxProvider, request: SandboxBrokerRequest):
        """Attach to the session's existing sandbox, self-healing a stale handle
        (``SandboxGoneError`` recreates under the same session id), or create a new one.
        Returns ``(sandbox, recreated)`` — ``recreated`` marks the self-heal case so the
        caller can surface the silent workspace reset as a result notice."""
        session = request.sandbox_session
        if session.sandbox_id:
            try:
                return await provider.attach(session.sandbox_id, principal=request.principal, policy=request.policy), False
            except SandboxGoneError:
                logger.info(
                    "Sandbox %s for session %s is gone; recreating (self-heal)",
                    session.sandbox_id,
                    session.sandbox_session_id,
                )
                return await provider.create(principal=request.principal, policy=request.policy), True
        return await provider.create(principal=request.principal, policy=request.policy), False

    async def _execute(self, sandbox, request: SandboxBrokerRequest) -> SandboxResult:
        """Dispatch the request's operation to the sandbox handle under
        ``asyncio.wait_for(policy.timeout)``; expiry raises ``SandboxTimeoutError``."""
        op = request.operation
        payload = request.payload
        timeout = request.policy.timeout

        async def call() -> SandboxResult:
            """Map the operation name to the corresponding sandbox method call."""
            if op == "execute_code":
                return await sandbox.execute_code(payload["code"], payload.get("language", "python"), timeout=timeout)
            if op == "execute_command":
                return await sandbox.execute_command(payload["command"], timeout=timeout)
            if op == "install_packages":
                return await sandbox.install_packages(payload["packages"])
            if op == "upload_file":
                await sandbox.upload_file(payload["path"], payload["content"])
                return SandboxResult(exit_code=0)
            if op == "download_file":
                content = await sandbox.download_file(payload["path"])
                return SandboxResult(output_files=[SandboxFile(path=payload["path"], content=content)])
            raise SandboxConfigError(f"unknown sandbox operation: {op}")

        try:
            return await asyncio.wait_for(call(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise SandboxTimeoutError(f"sandbox operation '{op}' exceeded timeout {timeout}s") from exc
        except SandboxError:
            raise
