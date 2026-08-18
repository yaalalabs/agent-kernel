"""ScheduleManager — service façade for the scheduling capability.

Owns the scheduled-task lifecycle: semantic validation of an occurrence rule, the ordering of
store and provider writes (and the rollback when the second one fails), ownership enforcement,
the frozen trigger body every occurrence delivers, and occurrence recording. A single shared
instance serves the ChatService interception, the management routes and the agent tools.
"""

import json
import logging
import uuid
from threading import RLock
from typing import Any, ClassVar, Dict, Optional

from ..core.config import AKConfig
from ..core.model import BaseChatRequest, ScheduleSpec
from ..core.runtime import Runtime
from ..core.util.factory import AKConfigError
from ..core.util.pagination import DEFAULT_PAGE_SIZE, clamp_limit, decode_cursor, encode_cursor
from ..pipeline.transport.base import QueueTransportFactory
from .model import TOKEN_OCCURRENCE_TIME, TOKEN_REQUEST_ID, ScheduledTask, ScheduledTaskPage, ScheduleStatus, utc_now_iso
from .provider.base import ScheduleProvider, ScheduleProviderFactory
from .store.base import ScheduleStore, ScheduleStoreBuilder
from .timing import OccurrenceCalculator

# Fields an amendment may carry: the occurrence rule, the prompt, and the paused/active switch.
# Everything else about a task (its owner, its session, its occurrence history) is immutable.
_SPEC_AMENDABLE_FIELDS = frozenset({"at", "cron", "timezone", "session_mode"})
_AMENDABLE_FIELDS = _SPEC_AMENDABLE_FIELDS | {"prompt", "status"}

# Statuses an amendment may set: completing and cancelling are lifecycle outcomes, not amendments.
_AMENDABLE_STATUSES = (ScheduleStatus.ACTIVE, ScheduleStatus.PAUSED)

# Statuses that close a task: neither an amendment nor a cancellation applies to one.
_TERMINAL_STATUSES = (ScheduleStatus.COMPLETED, ScheduleStatus.CANCELLED)


class ScheduleManager:
    """Service façade owning scheduled-task lifecycle, ownership and trigger bodies."""

    _instance: ClassVar[Optional["ScheduleManager"]] = None
    _lock: ClassVar[RLock] = RLock()
    _log = logging.getLogger("ak.schedule.manager")

    def __init__(self, provider: ScheduleProvider, store: ScheduleStore):
        """Initialize a ScheduleManager instance. Use :meth:`get`, not this constructor.

        :param provider: Backend that fires the task's occurrences.
        :param store: Backend that persists the task records.
        :raises AKConfigError: If the provider cannot deliver to the configured queue transport.
        """
        self._provider = provider
        self._store = store
        self._validate_transport_compatibility()

    @classmethod
    def get(cls) -> Optional["ScheduleManager"]:
        """Return the shared ScheduleManager instance, or None when the scheduling capability is
        not configured (no 'schedule' block). Callers use the None check as the feature-enabled check.

        :return: The shared instance, or None if the capability is disabled.
        :raises AKConfigError: If the configured provider, store, or transport pairing is unusable.
        """
        if AKConfig.get().schedule is None:
            return None
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(provider=ScheduleProviderFactory.create(), store=ScheduleStoreBuilder.build())
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared instance so the next get() rebuilds from config. Intended for testing."""
        with cls._lock:
            cls._instance = None

    def create_from_request(self, req: BaseChatRequest) -> ScheduledTask:
        """Register the schedule block of a chat request as a scheduled task.

        :param req: The chat request carrying the schedule block.
        :return: The created task.
        :raises ValueError: If the request carries no schedule block, or the schedule is unusable.
        :raises ScheduleError: If the provider rejected the registration.
        """
        if req.schedule is None:
            raise ValueError("The request carries no 'schedule' block")
        return self.create(
            user_id=req.user_id,
            prompt=req.prompt,
            spec=req.schedule,
            agent=req.agent,
            session_id=req.session_id,
        )

    def create(
        self,
        user_id: Optional[str],
        prompt: Optional[str],
        spec: ScheduleSpec,
        agent: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ScheduledTask:
        """Validate, store and register a new scheduled task.

        The record is written before the provider registration and rolled back (hard-deleted) if
        that registration fails, so a stored active task always has a live registration behind it.

        :param user_id: Owning user; required, since every later mutation is checked against it.
        :param prompt: The prompt each occurrence runs.
        :param spec: The occurrence rule.
        :param agent: The agent each occurrence runs on, or None for the default.
        :param session_id: Originating session of the task.
        :return: The created task, carrying its provider reference.
        :raises ValueError: If the owner, prompt, session, agent or occurrence rule is unusable.
        :raises ScheduleError: If the provider rejected the registration.
        """
        if not user_id:
            raise ValueError("Scheduling requires a user identity: include user_id on the chat request")
        if not prompt:
            raise ValueError("Scheduling requires a prompt to run at the scheduled time")
        if not session_id:
            raise ValueError("Scheduling requires a session_id on the request")
        # Every occurrence runs unattended, so a named agent that does not exist has to fail here,
        # where the caller still sees it, rather than in the runner at each fire time. Only a named
        # agent is checked: an unnamed one resolves to whatever default the firing process has, and
        # that process is not necessarily this one.
        if agent:
            Runtime.ensure_agent_available(agent)
        OccurrenceCalculator.validate(spec)

        now = utc_now_iso()
        task = ScheduledTask(
            task_id=str(uuid.uuid4()),
            user_id=user_id,
            prompt=prompt,
            agent=agent,
            session_id=session_id,
            spec=spec,
            created_at=now,
            updated_at=now,
        )
        self._store.create(task)
        try:
            provider_ref = self._provider.create(task, self._build_trigger_body(task))
        except Exception:
            self._log.error(f"Rolling back scheduled task {task.task_id}: provider registration failed")
            self._store.delete(task.task_id)
            raise
        self._log.info(f"Created scheduled task {task.task_id} for user {user_id}")
        return self._store.update(task.model_copy(update={"provider_ref": provider_ref, "updated_at": utc_now_iso()}))

    def get_task(self, task_id: str, user_id: Optional[str] = None) -> Optional[ScheduledTask]:
        """Load a task by id, optionally enforcing ownership.

        :param task_id: Identifier of the task.
        :param user_id: When provided, the task's owner must match.
        :return: The task, or None if it does not exist.
        :raises PermissionError: If user_id is provided and does not own the task.
        """
        task = self._store.get(task_id)
        if task is None:
            return None
        self._check_ownership(task, user_id)
        return task

    def list_tasks(self, user_id: Optional[str] = None, limit: Optional[int] = None, cursor: Optional[str] = None) -> ScheduledTaskPage:
        """Return a page of scheduled tasks, most-recently updated first.

        :param user_id: Filter by owning user id; unfiltered when omitted.
        :param limit: Maximum number of tasks (clamped to [1, MAX_PAGE_SIZE]).
        :param cursor: Opaque cursor from a previous page's next_cursor.
        :return: A ScheduledTaskPage with the tasks and the next opaque cursor.
        :raises ValueError: If the cursor is malformed.
        """
        offset = decode_cursor(cursor)
        page_size = clamp_limit(limit, DEFAULT_PAGE_SIZE)
        tasks, next_offset = self._store.list(user_id=user_id, limit=page_size, offset=offset)
        return ScheduledTaskPage(tasks=tasks, next_cursor=encode_cursor(next_offset))

    def update(self, task_id: str, amendment: Dict[str, Any], user_id: Optional[str] = None) -> ScheduledTask:
        """Amend a task's occurrence rule, prompt, or paused/active state.

        The amendment carries the full amendable representation (PUT semantics): the occurrence
        rule is replaced as a unit, so an amendment that names any occurrence field and omits the
        others clears them rather than keeping the previous values (see :meth:`_apply_amendment`).
        The store is written first and restored to the previous record if the provider rejects
        the amendment.

        :param task_id: Identifier of the task to amend.
        :param amendment: The amendable fields: at, cron, timezone, session_mode, prompt, status.
        :param user_id: When provided, the task's owner must match.
        :return: The amended task.
        :raises KeyError: If the task does not exist.
        :raises PermissionError: If user_id is provided and does not own the task.
        :raises ValueError: If the task is closed, or the amendment is unusable.
        :raises ScheduleError: If the provider rejected the amendment.
        """
        previous = self._require_amendable_task(task_id, user_id)
        unknown_fields = set(amendment) - _AMENDABLE_FIELDS
        if unknown_fields:
            raise ValueError(f"Cannot amend {sorted(unknown_fields)} of a scheduled task; amendable fields are {sorted(_AMENDABLE_FIELDS)}")

        amended = self._apply_amendment(previous, amendment)
        OccurrenceCalculator.validate(amended.spec)
        self._store.update(amended)
        try:
            self._provider.update(amended, self._build_trigger_body(amended))
        except Exception:
            self._log.error(f"Restoring scheduled task {task_id}: provider amendment failed")
            self._store.update(previous)
            raise
        self._log.info(f"Amended scheduled task {task_id} (status {amended.status.value})")
        return amended

    def cancel(self, task_id: str, user_id: Optional[str] = None) -> ScheduledTask:
        """Cancel a task: deregister its occurrences and record the cancellation.

        The record survives as the audit trail, so cancellation is a status transition rather
        than a delete. Deregistration tolerates a registration that is already gone, which is the
        normal state of a one-time schedule that has already fired.

        :param task_id: Identifier of the task to cancel.
        :param user_id: When provided, the task's owner must match.
        :return: The cancelled task.
        :raises KeyError: If the task does not exist.
        :raises PermissionError: If user_id is provided and does not own the task.
        :raises ValueError: If the task is already closed.
        :raises ScheduleError: If the provider rejected the deregistration.
        """
        task = self._require_amendable_task(task_id, user_id)
        if task.provider_ref:
            self._provider.delete(task.provider_ref)
        self._log.info(f"Cancelled scheduled task {task_id}")
        return self._store.update(task.model_copy(update={"status": ScheduleStatus.CANCELLED, "updated_at": utc_now_iso()}))

    def record_trigger(self, task_id: str, request_id: Optional[str] = None, occurred_at: Optional[str] = None) -> None:
        """Record that an occurrence of a task fired, and complete a one-time task.

        Never raises: the occurrence fields are advisory bookkeeping, and a store that cannot
        take them must not fail the run the trigger started.

        :param task_id: Identifier of the task that fired.
        :param request_id: Request id of the run the occurrence produced, when known.
        :param occurred_at: Occurrence timestamp reported by the provider; now when omitted.
        """
        try:
            task = self._store.get(task_id)
            if task is None:
                self._log.warning(f"Trigger received for unknown scheduled task {task_id}")
                return
            # A one-time schedule has no further occurrences, so the trigger closes it.
            self._store.record_trigger(
                task_id,
                request_id=request_id,
                occurred_at=occurred_at or utc_now_iso(),
                completed=task.spec.at is not None,
            )
        except Exception as exc:
            self._log.error(f"Failed to record trigger of scheduled task {task_id}: {exc}")

    def _validate_transport_compatibility(self) -> None:
        """Fail fast when the provider cannot deliver to the configured queue transport.

        The declared transport type is resolved rather than the transport itself, so the check
        holds on deployments whose pipeline transport class is not the one consuming the queue.

        :raises AKConfigError: If the pairing cannot deliver a trigger.
        """
        supported_transports = type(self._provider).supported_transports
        if supported_transports is None:
            return
        transport_type = QueueTransportFactory.resolve_type()
        if transport_type in supported_transports:
            return
        provider_type = AKConfig.get().schedule.provider.type
        raise AKConfigError(
            f"schedule provider '{provider_type}' delivers to {sorted(supported_transports)} transports, "
            f"but the configured queue transport is '{transport_type}'"
        )

    def _require_amendable_task(self, task_id: str, user_id: Optional[str]) -> ScheduledTask:
        """Load a task that a mutation may still be applied to.

        :param task_id: Identifier of the task.
        :param user_id: When provided, the task's owner must match.
        :return: The task.
        :raises KeyError: If the task does not exist.
        :raises PermissionError: If user_id is provided and does not own the task.
        :raises ValueError: If the task is completed or cancelled.
        """
        task = self._store.get(task_id)
        if task is None:
            raise KeyError(f"Scheduled task {task_id} not found")
        self._check_ownership(task, user_id)
        if task.status in _TERMINAL_STATUSES:
            raise ValueError(f"Scheduled task {task_id} is {task.status.value} and can no longer be changed")
        return task

    @staticmethod
    def _check_ownership(task: ScheduledTask, user_id: Optional[str]) -> None:
        """Enforce that a resolved user owns the task.

        :param task: The task being accessed.
        :param user_id: The resolved user, or None when the caller is unauthenticated.
        :raises PermissionError: If user_id is provided and does not own the task.
        """
        if user_id is not None and task.user_id != user_id:
            raise PermissionError(f"Scheduled task {task.task_id} is not owned by user {user_id}")

    @staticmethod
    def _apply_amendment(previous: ScheduledTask, amendment: Dict[str, Any]) -> ScheduledTask:
        """Build the amended task from the previous record and the amendment.

        The occurrence rule is replaced as a unit: an amendment naming any of at/cron/timezone/
        session_mode rebuilds the whole spec from what that amendment carries, so an omitted field
        falls back to its default rather than to the stored value. An amendment naming none of them
        leaves the rule untouched, which is how a prompt-only or pause/resume amendment works.

        :param previous: The stored record being amended.
        :param amendment: The amendable fields.
        :return: The amended task (not yet persisted).
        :raises ValueError: If the amended spec, prompt or status is invalid.
        """
        spec_fields = {field: value for field, value in amendment.items() if field in _SPEC_AMENDABLE_FIELDS}
        # Built from the amendment alone, not merged over the stored spec: the occurrence rule is
        # replaced as a unit, so an omitted field falls back to its default rather than to the
        # stored value. Rebuilding also runs the spec's own structural validation on the result.
        spec = ScheduleSpec(**spec_fields) if spec_fields else previous.spec

        prompt = amendment.get("prompt", previous.prompt)
        if not prompt:
            raise ValueError("A scheduled task's prompt cannot be emptied")

        status = ScheduleManager._parse_amended_status(amendment["status"]) if "status" in amendment else previous.status
        return previous.model_copy(update={"spec": spec, "prompt": prompt, "status": status, "updated_at": utc_now_iso()})

    @staticmethod
    def _parse_amended_status(value: Any) -> ScheduleStatus:
        """Resolve an amendment's status value, rejecting the ones an amendment cannot set.

        :param value: The requested status.
        :return: The resolved status.
        :raises ValueError: If the value is not one an amendment may set.
        """
        allowed = [status.value for status in _AMENDABLE_STATUSES]
        if value not in allowed:
            raise ValueError(f"A scheduled task's status can only be amended to one of {allowed}: got '{value}'")
        return ScheduleStatus(value)

    @staticmethod
    def _build_trigger_body(task: ScheduledTask) -> str:
        """Freeze the JSON body every occurrence of the task delivers into the input queue.

        The occurrence placeholders are left for the provider to substitute. The body carries no
        schedule block: an occurrence must execute as a plain chat request, otherwise firing a
        schedule would register another one.

        :param task: The task the body belongs to.
        :return: The frozen trigger body as a JSON string.
        """
        reuses_session = task.spec.session_mode == "reuse"
        body = {
            "prompt": task.prompt,
            "agent": task.agent,
            "user_id": task.user_id,
            "session_id": task.session_id if reuses_session else f"ak-sched-{task.task_id}-{TOKEN_OCCURRENCE_TIME}",
            "scheduled_task_id": task.task_id,
            "request_id": TOKEN_REQUEST_ID,
            "scheduled_time": TOKEN_OCCURRENCE_TIME,
        }
        return json.dumps(body)
