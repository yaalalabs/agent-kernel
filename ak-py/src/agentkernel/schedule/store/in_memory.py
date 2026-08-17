"""In-memory scheduled-task store for local development and testing."""

import logging
from typing import ClassVar, List, Optional, Tuple

from ...core.util.pagination import paginate
from ..model import ScheduledTask, ScheduleStatus, utc_now_iso
from .base import ScheduleStore


class InMemoryScheduleStore(ScheduleStore):
    """Process-local task store.

    Records are shared across instances via a ClassVar, so they live as long as the process —
    which matches the local provider's timers, whose armed occurrences are equally process-bound.
    Stored records are copied in and out so callers cannot mutate persisted state by accident.
    """

    _tasks: ClassVar[dict[str, ScheduledTask]] = {}  # task_id -> stored record
    _log = logging.getLogger("ak.schedule.store.inmemory")

    def create(self, task: ScheduledTask) -> ScheduledTask:
        self._log.debug(f"Storing scheduled task {task.task_id} for user {task.user_id}")
        self._tasks[task.task_id] = task.model_copy(deep=True)
        return task

    def get(self, task_id: str) -> Optional[ScheduledTask]:
        stored = self._tasks.get(task_id)
        return stored.model_copy(deep=True) if stored is not None else None

    def update(self, task: ScheduledTask) -> ScheduledTask:
        self._tasks[task.task_id] = task.model_copy(deep=True)
        return task

    def delete(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def list(self, user_id: Optional[str] = None, limit: int = 50, offset: int = 0) -> Tuple[List[ScheduledTask], Optional[int]]:
        matches = [task.model_copy(deep=True) for task in self._tasks.values() if user_id is None or task.user_id == user_id]
        matches.sort(key=lambda task: task.updated_at, reverse=True)
        return paginate(matches, limit, offset)

    def record_trigger(self, task_id: str, request_id: Optional[str], occurred_at: str, completed: bool) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            self._log.warning(f"Ignoring trigger record for unknown scheduled task {task_id}")
            return
        task.last_triggered_at = occurred_at
        task.last_request_id = request_id
        task.trigger_count += 1
        task.updated_at = utc_now_iso()
        if completed:
            task.status = ScheduleStatus.COMPLETED

    def clear(self) -> None:
        self._log.debug("Clearing all stored scheduled tasks")
        self._tasks.clear()
