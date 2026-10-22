"""``BrokerWorkerCore`` — the flavor-independent sandbox execution engine.

Every broker flavor (embedded, thread, ECS, Lambda) drives the same engine to turn one
``ExecutionRequest`` into a result. Two entry points:

* ``run`` — executes and returns ``(SandboxResult, SandboxSession)``, raising ``SandboxError``
  on any machinery/policy failure. In-process flavors that report synchronously use this so
  the real exception reaches the caller.
* ``process`` — the terminal-guarantee wrapper for asynchronous flavors: never raises, always
  returns a ``ExecutionCompletion`` (a failure becomes a ``failed``/``timed_out`` completion).
"""

import asyncio
import inspect
import logging
import time
from typing import Any, ClassVar, Optional

from ...core.config import AKConfig
from ..base import Sandbox, SandboxProvider
from ..errors import (
    SandboxCapabilityError,
    SandboxConfigError,
    SandboxError,
    SandboxGoneError,
    SandboxPermissionDeniedError,
    SandboxPolicyError,
    SandboxTimeoutError,
)
from ..factory import SandboxProviderFactory
from ..model import SandboxFile, SandboxResult, SandboxSession
from ..packages import PackageInstaller
from ..permission import SandboxPermissionGuard
from .base import ExecutionCompletion, ExecutionRequest

logger = logging.getLogger("ak.sandbox.broker")


class BrokerWorkerCore:
    """Processes one request against the resolved provider, serialized per sandbox session."""

    # The handle owns the operation's timeout; the worker's own timer fires this much later as a backstop.
    BACKSTOP_GRACE_SECONDS: ClassVar[float] = 10.0
    # The keywords the worker passes to install_packages; a pre-#692 override may lack either.
    INSTALL_KEYWORDS: ClassVar[frozenset[str]] = frozenset({"ecosystem", "timeout"})

    def __init__(self, *, inline_payload_max_bytes: Optional[int] = None) -> None:
        """Create an engine instance. ``inline_payload_max_bytes`` is the offload threshold
        for flavors that support it (``None`` for in-process flavors, which never offload)."""
        self._inline_max = inline_payload_max_bytes
        self._locks: dict[str, asyncio.Lock] = {}  # per sandbox_session_id
        # Process-lifetime warning memo: (provider, profile) for _enforce_policy,
        # (provider, profile, "permission") for _warn_capability_mismatch.
        self._policy_warned: set[tuple[str, ...]] = set()
        self._guard = SandboxPermissionGuard()
        self._install_params: dict[type, frozenset[str]] = {}  # Sandbox subclass -> install keywords it accepts
        self._install_warned: set[type] = set()  # legacy Sandbox subclasses already given the deprecation warning

    def _lock_for(self, sandbox_session_id: str) -> asyncio.Lock:
        """Return (creating on first use) the lock serializing operations per sandbox session."""
        lock = self._locks.get(sandbox_session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[sandbox_session_id] = lock
        return lock

    async def run(self, request: ExecutionRequest) -> tuple[SandboxResult, SandboxSession]:
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
        attached = self._environment_mode(request.profile) == "attached"

        # Teardown short-circuits before the fail-closed checks — it never executes code.
        # An attached environment is never disposed: only the session binding is dropped.
        if request.operation == "destroy":
            if session.sandbox_id and not attached:
                await provider.destroy(session.sandbox_id)
            session.status = "closed"
            session.sandbox_id = None
            return SandboxResult(sandbox_session_id=session.sandbox_session_id), session

        # 2. Fail-closed checks: principal, policy, then permission (before any provider call).
        self._warn_capability_mismatch(provider, request)
        self._check_principal(provider, request)
        self._enforce_policy(provider, request)
        self._guard.check(request)

        async with self._lock_for(session.sandbox_session_id):
            # 3. Attach-or-create with self-heal.
            sandbox, recreated = await self._acquire(provider, request, attached)
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

    async def process(self, request: ExecutionRequest) -> ExecutionCompletion:
        """Terminal-guarantee wrapper: always returns a completion, never raises (step 8)."""
        try:
            result, session = await self.run(request)
            return ExecutionCompletion(task_id=request.task_id, status="succeeded", result=result, sandbox_session=session)
        except SandboxTimeoutError as exc:
            logger.warning("Sandbox task %s timed out: %s", request.task_id, exc)
            return ExecutionCompletion(
                task_id=request.task_id,
                status="timed_out",
                error=str(exc),
                error_type=type(exc).__name__,
                sandbox_session=request.sandbox_session,
            )
        except SandboxPermissionDeniedError as exc:
            # The guard already logged this denial; no generic warning.
            return ExecutionCompletion(
                task_id=request.task_id,
                status="failed",
                error=str(exc),
                error_type=type(exc).__name__,
                sandbox_session=request.sandbox_session,
            )
        except Exception as exc:  # noqa: BLE001 — terminal guarantee: never end a task without a completion
            logger.warning("Sandbox task %s failed: %s", request.task_id, exc)
            return ExecutionCompletion(
                task_id=request.task_id,
                status="failed",
                error=str(exc),
                error_type=type(exc).__name__,
                sandbox_session=request.sandbox_session,
            )

    # -- internals ---------------------------------------------------------- #

    def _check_principal(self, provider: SandboxProvider, request: ExecutionRequest) -> None:
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

    def _enforce_policy(self, provider: SandboxProvider, request: ExecutionRequest) -> None:
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

    def _warn_capability_mismatch(self, provider: SandboxProvider, request: ExecutionRequest) -> None:
        """One WARNING per (provider, profile) when the policy permits what the instance does not declare.

        Such requests pass the guard and then fail in the handle with ``SandboxCapabilityError``;
        this surfaces the misconfiguration once instead of only per request.
        """
        caps = provider.capabilities
        policy = request.policy
        undeclared: list[str] = []
        if policy.package_install is not None:
            undeclared += [f"package ecosystem '{e}'" for e in policy.package_install.ecosystems if e not in caps.package_ecosystems]
        if policy.languages is not None:
            undeclared += [f"language '{lang}'" for lang in policy.languages if lang not in caps.languages]
        if not undeclared:
            return
        memo = (type(provider).__name__, request.profile, "permission")
        if memo in self._policy_warned:
            return
        self._policy_warned.add(memo)
        logger.warning(
            "Sandbox profile %s permits %s, but provider %s does not declare it; such requests will fail with SandboxCapabilityError",
            request.profile,
            ", ".join(undeclared),
            type(provider).__name__,
        )

    async def _acquire(self, provider: SandboxProvider, request: ExecutionRequest, attached: bool):
        """Attach to the session's existing sandbox, self-healing a stale handle
        (``SandboxGoneError`` recreates under the same session id), or create a new one.
        Returns ``(sandbox, recreated)`` — ``recreated`` marks the self-heal case so the
        caller can surface the silent workspace reset as a result notice.

        ``attached`` profiles never self-heal by provisioning: the framework does not own
        the environment, so a gone target is surfaced as the real ``SandboxGoneError``
        instead of being silently replaced with a fresh sandbox."""
        session = request.sandbox_session
        if session.sandbox_id:
            try:
                return await provider.attach(session.sandbox_id, principal=request.principal, policy=request.policy), False
            except SandboxGoneError:
                if attached:
                    raise SandboxGoneError(
                        f"attached environment '{session.sandbox_id}' (profile '{request.profile}') is unreachable; "
                        "not recreating — attached environments are never provisioned by the framework"
                    )
                logger.info(
                    "Sandbox %s for session %s is gone; recreating (self-heal)",
                    session.sandbox_id,
                    session.sandbox_session_id,
                )
                return await provider.create(principal=request.principal, policy=request.policy), True
        return await provider.create(principal=request.principal, policy=request.policy), False

    @staticmethod
    def _environment_mode(profile_name: str) -> str:
        """Return the profile's declared environment lifecycle ('managed' unless configured)."""
        profile_cfg = AKConfig.get().sandbox.profiles.get(profile_name)
        return getattr(profile_cfg, "environment", "managed") if profile_cfg is not None else "managed"

    async def _execute(self, sandbox, request: ExecutionRequest) -> SandboxResult:
        """Dispatch the request's operation to the sandbox handle with the operation's
        effective timeout, under a backstop ``asyncio.wait_for`` that fires
        ``BACKSTOP_GRACE_SECONDS`` later; backstop expiry raises ``SandboxTimeoutError``."""
        op = request.operation
        payload = request.payload
        timeout = request.policy.effective_timeout(op)

        async def call() -> SandboxResult:
            """Map the operation name to the corresponding sandbox method call."""
            if op == "execute_code":
                return await sandbox.execute_code(payload["code"], payload.get("language", "python"), timeout=timeout)
            if op == "execute_command":
                return await sandbox.execute_command(payload["command"], timeout=timeout)
            if op == "install_packages":
                return await self._call_install(sandbox, payload, timeout)
            if op == "upload_file":
                await sandbox.upload_file(payload["path"], payload["content"])
                return SandboxResult(exit_code=0)
            if op == "download_file":
                content = await sandbox.download_file(payload["path"])
                return SandboxResult(output_files=[SandboxFile(path=payload["path"], content=content)])
            raise SandboxConfigError(f"unknown sandbox operation: {op}")

        try:
            return await asyncio.wait_for(call(), timeout=timeout + self.BACKSTOP_GRACE_SECONDS)
        except asyncio.TimeoutError as exc:
            raise SandboxTimeoutError(f"sandbox operation '{op}' exceeded timeout {timeout}s (backstop)") from exc
        except SandboxError:
            raise

    async def _call_install(self, sandbox: Sandbox, payload: dict[str, Any], timeout: float) -> SandboxResult:
        """Dispatch install_packages with the keywords the override accepts; a pre-#692 override missing
        ``ecosystem`` and/or ``timeout`` goes through the deprecation shim. The ecosystem-independent
        package baseline runs first, for every override (ValueError on rejection)."""
        PackageInstaller.check_baseline(payload["packages"])
        ecosystem = payload.get("ecosystem", "python")
        sandbox_cls = type(sandbox)
        accepted = self._install_params_for(sandbox_cls)
        if accepted == self.INSTALL_KEYWORDS:
            return await sandbox.install_packages(payload["packages"], ecosystem=ecosystem, timeout=timeout)
        # An override without ``ecosystem`` can only mean pip; one without ``timeout`` has only the backstop.
        if "ecosystem" not in accepted and ecosystem != "python":
            raise SandboxCapabilityError(sandbox_cls.__name__, f"package_ecosystem:{ecosystem}")
        if sandbox_cls not in self._install_warned:
            self._install_warned.add(sandbox_cls)
            logger.warning(
                "Sandbox %s overrides install_packages without %s; this form is deprecated and will stop working in the next minor release",
                sandbox_cls.__name__,
                " and ".join(sorted(self.INSTALL_KEYWORDS - accepted)),
            )
        kwargs = {name: value for name, value in (("ecosystem", ecosystem), ("timeout", timeout)) if name in accepted}
        return await sandbox.install_packages(payload["packages"], **kwargs)

    def _install_params_for(self, sandbox_cls: type) -> frozenset[str]:
        """``install_parameters`` for ``sandbox_cls``, decided once per class."""
        accepted = self._install_params.get(sandbox_cls)
        if accepted is None:
            accepted = self.install_parameters(sandbox_cls)
            self._install_params[sandbox_cls] = accepted
        return accepted

    @classmethod
    def install_parameters(cls, sandbox_cls: type) -> frozenset[str]:
        """Which of ``ecosystem`` / ``timeout`` ``sandbox_cls.install_packages`` accepts (``**kwargs`` = both).

        Shared with ``SandboxProviderContract``, which must not pass an override a keyword it lacks.
        """
        params = inspect.signature(sandbox_cls.install_packages).parameters
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return cls.INSTALL_KEYWORDS
        return cls.INSTALL_KEYWORDS & frozenset(params)
