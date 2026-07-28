"""``SandboxManager`` — the agent-side façade over the sandbox capability.

A process-wide singleton (mirroring ``ConversationThreadManager``) that owns:

* the broker client (built from ``sandbox.broker.flavor`` via the factory),
* the principal resolver (``sandbox.principal_resolver`` dotted path, or the default),
* the sandbox-session registry.

Session addressing is namespace-isolated: ``per_session``/``per_call`` sessions live in the
current AK session's non-volatile cache, so one AK session can never address another's
sandboxes; ``per_runtime`` keeps a single shared entry per profile in process memory.
"""

import logging
import time
import uuid
from threading import RLock
from typing import Any, ClassVar, Optional, Union

from ..core.base import Session
from ..core.config import AKConfig
from ..core.util.factory import resolve_dotted
from .broker.base import SandboxBroker, SandboxBrokerRequest, SandboxCompletion
from .errors import SandboxConfigError, SandboxSessionNotFoundError
from .factory import SandboxBrokerFactory
from .model import SandboxPolicy, SandboxPrincipal, SandboxResult, SandboxSession, SandboxTask
from .principal import AgentPrincipalResolver, PrincipalResolver


class SandboxManager:
    _instance: ClassVar[Optional["SandboxManager"]] = None
    _lock: ClassVar[RLock] = RLock()
    _runtime_registry: ClassVar[dict[str, SandboxSession]] = {}  # per_runtime scope: sandbox_session_id -> session
    _log = logging.getLogger("ak.sandbox")

    _REGISTRY_KEY = "sandbox"  # key under the AK session's non-volatile cache

    def __init__(self, config: Any) -> None:
        """Build the manager from the ``sandbox`` config section: the broker client (via the
        factory) and the principal resolver. Use :meth:`get`, not this constructor."""
        self._config = config
        self._broker: SandboxBroker = SandboxBrokerFactory.get()
        self._resolver: PrincipalResolver = self._build_resolver(config)

    @staticmethod
    def _build_resolver(config: Any) -> PrincipalResolver:
        """Instantiate the configured ``principal_resolver`` dotted path, or the default
        ``AgentPrincipalResolver`` when none is configured."""
        if config.principal_resolver:
            return resolve_dotted(config.principal_resolver, base=PrincipalResolver, error=SandboxConfigError)()
        return AgentPrincipalResolver()

    @classmethod
    def get(cls) -> Optional["SandboxManager"]:
        """Return the shared instance, or None when the sandbox capability is disabled.
        Callers use the None check as the feature-enabled check."""
        config = AKConfig.get().sandbox
        if not config.enabled:
            return None
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config)
            return cls._instance

    @classmethod
    def _reset(cls) -> None:
        """Drop the shared instance and the per_runtime registry. Intended for testing."""
        with cls._lock:
            cls._instance = None
            cls._runtime_registry = {}

    # -- public API --------------------------------------------------------- #

    async def execute(
        self,
        *,
        code: Optional[str] = None,
        command: Optional[str] = None,
        language: str = "python",
        profile: Optional[str] = None,
        sandbox_session_id: Optional[str] = None,
        wait: Optional[float] = None,
    ) -> Union[SandboxResult, SandboxTask]:
        """Execute ``code`` (in ``language``) or a shell ``command`` in a sandbox.

        Exactly one of ``code``/``command`` must be given. Returns a ``SandboxResult`` when
        the execution completes within ``wait`` seconds, or a ``SandboxTask`` handle when it
        is promoted to run asynchronously (``wait=None`` means the broker decides per flavor).
        """
        if code is not None:
            operation, payload = "execute_code", {"code": code, "language": language}
        elif command is not None:
            operation, payload = "execute_command", {"command": command}
        else:
            raise ValueError("execute() requires either code or command")
        return await self._submit_op(operation, payload, profile=profile, sandbox_session_id=sandbox_session_id, wait=wait)

    async def upload(self, path: str, content: bytes, *, profile: Optional[str] = None, sandbox_session_id: Optional[str] = None) -> None:
        """Write ``content`` to ``path`` inside the resolved sandbox session's workspace."""
        await self._submit_op("upload_file", {"path": path, "content": content}, profile=profile, sandbox_session_id=sandbox_session_id)

    async def download(self, path: str, *, profile: Optional[str] = None, sandbox_session_id: Optional[str] = None) -> bytes:
        """Read and return the bytes at ``path`` from the resolved sandbox session's workspace."""
        result = await self._submit_op("download_file", {"path": path}, profile=profile, sandbox_session_id=sandbox_session_id)
        if isinstance(result, SandboxResult) and result.output_files:
            return result.output_files[0].content
        return b""

    async def task_status(self, task_id: str) -> Optional[SandboxTask]:
        """Return the current state of a promoted task, or ``None`` when unknown.

        Registry first; a still-pending entry (or a task missing from this session's
        registry, e.g. after suspend/resume) falls through to ``broker.result()``.
        """
        reg = self._nv_registry()
        data = reg["tasks"].get(task_id)
        if data is not None:
            task = SandboxTask(**data)
            if task.status == "pending":
                completion = await self._broker.result(task_id)
                if completion is not None:
                    task.status = completion.status
                    task.consumed = data.get("consumed", False)
                    reg["tasks"][task_id] = task.model_dump()
                    self._save_nv_registry(reg)
                    # Persist the completed run's updated session handle (its newly created
                    # sandbox_id) via the scope-aware writer, so the next operation on the
                    # session attaches to the promoted run's sandbox instead of creating a
                    # fresh, orphaning one.
                    self._write_session(completion.sandbox_session)
                    # The completion is now durable in the registry; release the broker's copy.
                    await self._broker.discard(task_id)
            return task
        completion = await self._broker.result(task_id)
        if completion is not None:
            return SandboxTask(
                task_id=task_id,
                sandbox_session_id=completion.sandbox_session.sandbox_session_id,
                profile=completion.sandbox_session.profile,
                status=completion.status,
                submitted_at=time.time(),
            )
        return None

    def ingest_completion(self, completion: SandboxCompletion) -> Optional[SandboxTask]:
        """Consume a task-completion event (called by ``SandboxPreHook`` under the session lock).

        Returns the updated task after marking it consumed and terminal and refreshing the
        sandbox-session handle, or ``None`` when the task is unknown or already consumed —
        the at-least-once dedup signal the hook turns into a halting no-op reply."""
        reg = self._nv_registry()
        data = reg["tasks"].get(completion.task_id)
        if data is None or data.get("consumed"):
            return None
        task = SandboxTask(**data)
        task.status = completion.status
        task.consumed = True
        reg["tasks"][completion.task_id] = task.model_dump()
        self._save_nv_registry(reg)
        self._write_session(completion.sandbox_session)
        return task

    def new_session(self, profile: Optional[str] = None, name: Optional[str] = None) -> SandboxSession:
        """Mint and register a fresh sandbox session for ``profile`` (default profile when
        omitted) and return it — the only way an explicit ``sandbox_session_id`` comes into
        existence. ``name`` is an optional human-friendly label surfaced by
        ``list_sessions``; addressing stays by id. Restricted to ``per_session`` scope:
        ``per_call`` sessions are ephemeral per execution and ``per_runtime`` is a single
        shared session by design."""
        profile_name = profile or self._config.default_profile
        profile_cfg = self._config.profiles.get(profile_name)
        if profile_cfg is None:
            raise SandboxConfigError(f"unknown sandbox profile '{profile_name}'; configured profiles: {sorted(self._config.profiles)}")
        if profile_cfg.scope != "per_session":
            raise SandboxConfigError(
                f"cannot mint a new sandbox session for profile '{profile_name}': scope '{profile_cfg.scope}' does not support "
                "explicit sessions (per_call is ephemeral per execution; per_runtime is a single shared session)"
            )
        now = time.time()
        session = SandboxSession(
            sandbox_session_id=uuid.uuid4().hex, name=name, profile=profile_name, provider_type=profile_cfg.type, created_at=now, last_used_at=now
        )
        self._write_session(session)
        return session

    async def destroy_session(self, sandbox_session_id: str) -> None:
        """Destroy the backend sandbox and remove the session from its registry. Idempotent."""
        session = self._find_session(sandbox_session_id)
        if session is None:
            return  # idempotent
        await self._destroy_backend(session)
        self._remove_session(session)

    def list_sessions(self) -> list[SandboxSession]:
        """Return the sandbox sessions addressable right now: the current AK session's
        registry plus the process-wide ``per_runtime`` entries."""
        reg = self._nv_registry()
        sessions = [SandboxSession(**data) for data in reg["sessions"].values()]
        sessions.extend(self._runtime_registry.values())
        return sessions

    # -- operation submission ---------------------------------------------- #

    async def _submit_op(
        self,
        operation: str,
        payload: dict[str, Any],
        *,
        profile: Optional[str] = None,
        sandbox_session_id: Optional[str] = None,
        wait: Optional[float] = None,
    ) -> Union[SandboxResult, SandboxTask]:
        """Resolve profile, session, principal, and policy into a ``SandboxBrokerRequest``
        and submit it. Persists the (updated) session handle on success; ``per_call``
        sessions are ephemeral and their backend is torn down in ``finally``.

        When an explicit ``sandbox_session_id`` is given, the profile is taken from the
        session's own record (the profile it was minted under), not the caller's ``profile``
        argument — a session is bound to its provider, so a mismatched or omitted caller
        profile must never reroute it to a different backend."""
        profile_name = self._resolve_profile_name(profile, sandbox_session_id)
        profile_cfg = self._config.profiles.get(profile_name)
        if profile_cfg is None:
            raise SandboxConfigError(f"unknown sandbox profile '{profile_name}'; configured profiles: {sorted(self._config.profiles)}")

        session, ephemeral, notice = await self._resolve_session(profile_name, sandbox_session_id, profile_cfg)
        principal = await self._resolve_principal()
        request = SandboxBrokerRequest(
            task_id=uuid.uuid4().hex,
            operation=operation,  # type: ignore[arg-type]
            payload=payload,
            profile=profile_name,
            principal=principal,
            policy=self._policy_from(profile_cfg),
            sandbox_session=session,
            ak_session_id=self._current_session_id(),
            agent=self._current_agent_name(),
            wait_deadline=self._deadline(wait),
        )
        try:
            outcome = await self._broker.submit(request, wait)
            if not ephemeral:
                self._write_session(request.sandbox_session)
            if notice and outcome.notice is None:
                # Carry the idle-reset advisory on whichever outcome type came back — a
                # promotion (SandboxTask) must not silently drop it ("recreation is never
                # silent").
                outcome.notice = notice
            if isinstance(outcome, SandboxTask):
                self._record_task(outcome)
            return outcome
        finally:
            if ephemeral:
                # per_call: dispose the ephemeral sandbox regardless of success/failure.
                await self._destroy_backend(request.sandbox_session)

    def _resolve_profile_name(self, profile: Optional[str], sandbox_session_id: Optional[str]) -> str:
        """Pick the profile for this operation. An explicit ``sandbox_session_id`` binds the
        profile to the one the session was minted under (found across both registries); a
        caller ``profile`` that contradicts it is a config error, and omitting it is fine. No
        explicit id → the caller's ``profile`` or the default."""
        if sandbox_session_id is not None:
            existing = self._find_session(sandbox_session_id)
            if existing is not None:
                if profile is not None and profile != existing.profile:
                    raise SandboxConfigError(
                        f"sandbox session '{sandbox_session_id}' belongs to profile '{existing.profile}', "
                        f"but profile '{profile}' was requested; omit profile to reuse a session"
                    )
                return existing.profile
        return profile or self._config.default_profile

    def _record_task(self, task: SandboxTask) -> None:
        """Record a promoted task in the current AK session's registry so ``task_status``
        and completion ingestion can resolve it on a later turn."""
        reg = self._nv_registry()
        reg["tasks"][task.task_id] = task.model_dump()
        self._save_nv_registry(reg)

    # -- principal / policy ------------------------------------------------- #

    async def _resolve_principal(self) -> SandboxPrincipal:
        """Resolve the execution identity from the current session and agent."""
        return await self._resolver.resolve(Session.current(), self._current_agent())

    @staticmethod
    def _current_agent():
        """Return the agent from the active ``ToolContext``, or ``None`` when the operation
        is driven programmatically (no tool context)."""
        try:
            from ..core.tool import ToolContext

            ctx = ToolContext.get()
            return getattr(ctx, "agent", None) if ctx is not None else None
        except Exception:  # noqa: BLE001 — no tool context is a normal (programmatic) case
            return None

    @classmethod
    def _current_agent_name(cls) -> str:
        """The agent name for completion routing — always the agent, never the principal
        subject (which under user identity is the end-user id). ``"agent"`` when no agent
        context is available."""
        agent = cls._current_agent()
        return agent.name if agent is not None else "agent"

    @staticmethod
    def _policy_from(profile_cfg: Any) -> SandboxPolicy:
        """Convert a profile's policy config block into the ``SandboxPolicy`` wire model."""
        p = profile_cfg.policy
        return SandboxPolicy(
            network_egress=p.network_egress,
            network_allow=list(p.network_allow),
            fs_allow_read=list(p.fs_allow_read),
            fs_allow_write=list(p.fs_allow_write),
            cpu=p.cpu,
            memory_mb=p.memory_mb,
            timeout=p.timeout,
            strict=p.strict,
        )

    @staticmethod
    def _deadline(wait: Optional[float]) -> Optional[float]:
        """Turn a relative ``wait`` in seconds into an absolute epoch deadline (``None`` passes through)."""
        return None if wait is None else time.time() + wait

    @staticmethod
    def _current_session_id() -> str:
        """Return the current AK session id, or ``""`` outside any session context."""
        session = Session.current()
        return session.id if session is not None else ""

    # -- session resolution / registry ------------------------------------- #

    async def _resolve_session(
        self, profile_name: str, sandbox_session_id: Optional[str], profile_cfg: Any
    ) -> tuple[SandboxSession, bool, Optional[str]]:
        """Resolve the target sandbox session; returns ``(session, ephemeral, notice)``.

        ``per_call`` scope always returns a fresh ephemeral session. An explicit id must
        exist in the registry (miss raises ``SandboxSessionNotFoundError``); an omitted id
        maps to the profile's ``default:<profile>`` session, created on first use. An
        idle-expired session is destroyed here and recreated under the same id on next use;
        that reset is reported through ``notice`` so the agent can tell the user instead of
        silently facing an empty workspace.
        """
        now = time.time()
        scope = profile_cfg.scope
        if scope == "per_call":
            session = SandboxSession(
                sandbox_session_id=uuid.uuid4().hex, profile=profile_name, provider_type=profile_cfg.type, created_at=now, last_used_at=now
            )
            return session, True, None

        if sandbox_session_id is not None:
            existing = self._read_session(sandbox_session_id, scope)
            if existing is None:
                raise SandboxSessionNotFoundError(f"unknown sandbox session '{sandbox_session_id}'")
        else:
            default_id = f"default:{profile_name}"
            existing = self._read_session(default_id, scope)
            if existing is None:
                existing = SandboxSession(
                    sandbox_session_id=default_id, profile=profile_name, provider_type=profile_cfg.type, created_at=now, last_used_at=now
                )

        # Idle timeout: opportunistically close+destroy an expired sandbox on touch, then let
        # the worker recreate it under the same sandbox_session_id.
        notice = None
        if existing.sandbox_id and (now - existing.last_used_at) > profile_cfg.idle_timeout:
            await self._destroy_backend(existing)
            existing.sandbox_id = None
            existing.status = "active"
            existing.created_at = now
            notice = (
                f"sandbox session '{existing.sandbox_session_id}' was idle for more than {profile_cfg.idle_timeout}s "
                "and has been reset; its previous workspace state was discarded"
            )
        existing.last_used_at = now
        return existing, False, notice

    def _profile_scope(self, profile_name: str) -> str:
        """Return the configured scope of a profile, defaulting to ``per_session``."""
        profile_cfg = self._config.profiles.get(profile_name)
        return profile_cfg.scope if profile_cfg is not None else "per_session"

    def _read_session(self, sandbox_session_id: str, scope: str) -> Optional[SandboxSession]:
        """Look up a session in the registry the given scope addresses, or ``None``."""
        if scope == "per_runtime":
            return self._runtime_registry.get(sandbox_session_id)
        reg = self._nv_registry()
        data = reg["sessions"].get(sandbox_session_id)
        return SandboxSession(**data) if data is not None else None

    def _write_session(self, session: SandboxSession) -> None:
        """Persist a session handle into its scope's registry (nv_cache or process memory)."""
        if self._profile_scope(session.profile) == "per_runtime":
            self._runtime_registry[session.sandbox_session_id] = session
            return
        reg = self._nv_registry()
        reg["sessions"][session.sandbox_session_id] = session.model_dump()
        self._save_nv_registry(reg)

    def _remove_session(self, session: SandboxSession) -> None:
        """Delete a session handle from its scope's registry."""
        if self._profile_scope(session.profile) == "per_runtime":
            self._runtime_registry.pop(session.sandbox_session_id, None)
            return
        reg = self._nv_registry()
        reg["sessions"].pop(session.sandbox_session_id, None)
        self._save_nv_registry(reg)

    def _find_session(self, sandbox_session_id: str) -> Optional[SandboxSession]:
        """Look up a session id across both registries (per_runtime first), or ``None``."""
        if sandbox_session_id in self._runtime_registry:
            return self._runtime_registry[sandbox_session_id]
        reg = self._nv_registry()
        data = reg["sessions"].get(sandbox_session_id)
        return SandboxSession(**data) if data is not None else None

    def _nv_registry(self) -> dict:
        """Load the current AK session's sandbox registry (``{"sessions": ..., "tasks": ...}``)
        from its non-volatile cache; an empty registry outside any session context."""
        session = Session.current()
        if session is None:
            # No AK session context: only per_runtime addressing is possible.
            return {"sessions": {}, "tasks": {}}
        reg = session.get_non_volatile_cache().get(self._REGISTRY_KEY)
        if reg is None:
            reg = {"sessions": {}, "tasks": {}}
        return reg

    def _save_nv_registry(self, reg: dict) -> None:
        """Write the sandbox registry back to the current AK session's non-volatile cache."""
        session = Session.current()
        if session is not None:
            session.get_non_volatile_cache().set(self._REGISTRY_KEY, reg)

    async def _destroy_backend(self, session: SandboxSession) -> None:
        """Best-effort destroy of a session's backend sandbox via the broker.

        Failures are logged, never raised (teardown must not mask the primary flow); the
        handle is always marked closed and its ``sandbox_id`` cleared.
        """
        if not session.sandbox_id:
            session.status = "closed"
            return
        request = SandboxBrokerRequest(
            task_id=uuid.uuid4().hex,
            operation="destroy",
            payload={},
            profile=session.profile,
            principal=SandboxPrincipal(mode="agent", subject="agent"),
            policy=SandboxPolicy(),
            sandbox_session=session,
            ak_session_id=self._current_session_id(),
            agent="agent",
        )
        try:
            await self._broker.submit(request, None)
        except Exception as exc:  # noqa: BLE001 — teardown is best-effort; never mask the primary flow
            self._log.warning("Error destroying sandbox %s (session %s): %s", session.sandbox_id, session.sandbox_session_id, exc)
        session.status = "closed"
        session.sandbox_id = None
