"""Abstract task store and builder for the scheduling capability."""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from ...core.config import AKConfig
from ...core.util.factory import AKConfigError, require_extra, resolve_dotted
from ...core.util.pagination import DEFAULT_PAGE_SIZE
from ..model import ScheduledTask

# Backends shipped with the capability; anything else is treated as a dotted path (BYO).
_BUILTIN_SCHEDULE_STORES = ["in_memory", "redis", "valkey", "dynamodb"]


class ScheduleStore(ABC):
    """Persistence interface for scheduled tasks, keyed by ``task_id``.

    A task is one document: writes are full-record ``update`` calls, so implementations need no
    field-level merging. Paged reads take a zero-based ``offset`` and a ``limit`` and return the
    page plus the ``next_offset`` for the following page (``None`` on the last page); the opaque
    cursor is the manager's concern, never the store's.
    """

    @abstractmethod
    def create(self, task: ScheduledTask) -> ScheduledTask:
        """Persist a new task record.

        :param task: The task to persist.
        :return: The persisted task.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, task_id: str) -> Optional[ScheduledTask]:
        """Load a task by id.

        :param task_id: Identifier of the task.
        :return: The task, or None if it does not exist.
        """
        raise NotImplementedError

    @abstractmethod
    def update(self, task: ScheduledTask) -> ScheduledTask:
        """Overwrite a task record with the given state.

        :param task: The full record to write.
        :return: The written task.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, task_id: str) -> None:
        """Remove a task record outright.

        Reserved for rolling back a creation whose provider registration failed: cancellation is
        a status transition, so the record survives as the audit trail. Deleting a task that is
        already gone is not an error.

        :param task_id: Identifier of the task to remove.
        """
        raise NotImplementedError

    @abstractmethod
    def list(self, user_id: Optional[str] = None, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> Tuple[List[ScheduledTask], Optional[int]]:
        """List task records, most-recently updated first.

        :param user_id: Filter by owning user id; unfiltered when omitted.
        :param limit: Maximum number of tasks to return.
        :param offset: Zero-based index of the first task to return.
        :return: A tuple of (tasks page, next_offset). next_offset is None on the last page.
        """
        raise NotImplementedError

    @abstractmethod
    def record_trigger(self, task_id: str, request_id: Optional[str], occurred_at: str, completed: bool) -> None:
        """Record that an occurrence of a task fired.

        Advances ``last_triggered_at``, ``trigger_count`` and ``last_request_id``, and moves the
        task to ``completed`` when ``completed`` is set (a one-time schedule has no further
        occurrences). Implementations read-modify-write: concurrent occurrences are last-writer-wins,
        which is acceptable because these fields are advisory. Recording against an unknown task
        is a no-op, since a cancelled-and-deleted task may still have a trigger in flight.

        :param task_id: Identifier of the task that fired.
        :param request_id: Request id of the run the occurrence produced, when known.
        :param occurred_at: ISO-8601 UTC timestamp of the occurrence.
        :param completed: Whether this was the task's final occurrence.
        """
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """Remove every stored task."""
        raise NotImplementedError


class ScheduleStoreBuilder:
    """Builds the ``ScheduleStore`` named by ``schedule.store.type``."""

    _log = logging.getLogger("ak.schedule.store.builder")

    @staticmethod
    def build() -> ScheduleStore:
        """Build and return a ScheduleStore instance based on the configured ``schedule.store.type``.

        ``type`` is a built-in short name (in_memory, redis, valkey, dynamodb) or a dotted path to a
        user-supplied ``ScheduleStore`` subclass (bring-your-own). An unknown, non-dotted value
        raises ``AKConfigError``.

        :return: The configured store.
        :raises ValueError: If the scheduling capability is not configured.
        :raises AKConfigError: If the configured type is neither a built-in nor a resolvable dotted path.
        """
        schedule_config = AKConfig.get().schedule
        if schedule_config is None:
            raise ValueError("Scheduling is not configured — add a 'schedule' block to config.yaml")

        store_type = schedule_config.store.type
        ScheduleStoreBuilder._log.info(f"Building '{store_type}' schedule store")
        key = store_type.lower()
        if key == "in_memory":
            from .in_memory import InMemoryScheduleStore

            return InMemoryScheduleStore()
        if key == "redis":
            with require_extra("redis", "schedule.store.type: redis"):
                from .redis import RedisScheduleStore

            return RedisScheduleStore()
        if key == "valkey":
            with require_extra("valkey", "schedule.store.type: valkey"):
                from .valkey import ValkeyScheduleStore

            return ValkeyScheduleStore()
        if key == "dynamodb":
            with require_extra("aws", "schedule.store.type: dynamodb"):
                from .dynamodb import DynamoDBScheduleStore

            return DynamoDBScheduleStore()
        if "." not in store_type:
            raise AKConfigError(
                f"unknown schedule store type '{store_type}'; expected one of {_BUILTIN_SCHEDULE_STORES} "
                "or a dotted path to a ScheduleStore subclass"
            )
        return resolve_dotted(store_type, base=ScheduleStore)()
