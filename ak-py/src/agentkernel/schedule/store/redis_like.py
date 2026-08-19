"""Redis-like implementation of the ScheduleStore interface.

Layout (keys under the configured prefix):
  - Task:        {prefix}task:{task_id}        -> ScheduledTask JSON document
  - User index:  {prefix}index:user:{user_id}  -> set of task_ids
  - All index:   {prefix}index:all             -> set of task_ids

A task is one document, so every write is a full SET of that document and the index sets exist
only to answer listings without scanning the keyspace. TTL defaults to 0 for schedules (a task
that silently expired would stop firing with no audit trail); when one is configured it is
refreshed on every write of the record it belongs to.
"""

import logging
from typing import List, Optional, Tuple

from ...core.util.driver.redis_like import _RedisLikeDriver
from ...core.util.pagination import DEFAULT_PAGE_SIZE, paginate
from ..model import ScheduledTask, ScheduleStatus, utc_now_iso
from .base import ScheduleStore


class _RedisLikeScheduleStore(ScheduleStore):
    """Shared scheduled-task store body for the Redis-protocol backends.

    Concrete subclasses (``RedisScheduleStore``, ``ValkeyScheduleStore``) implement only
    ``__init__``, where they must set all three attributes below — this class reads them but never
    assigns them. Mirrors ``_RedisLikeThreadStore``, whose subclasses supply their driver the same way.
    """

    _driver: _RedisLikeDriver
    _prefix: str
    _log: logging.Logger

    def _task_key(self, task_id: str) -> str:
        return self._driver.key(f"task:{task_id}")

    def _user_index_key(self, user_id: str) -> str:
        return self._driver.key(f"index:user:{user_id}")

    def _all_index_key(self) -> str:
        return self._driver.key("index:all")

    def _expire(self, *keys: str) -> None:
        if self._driver.ttl > 0:
            for key in keys:
                self._driver.expire(key)

    def create(self, task: ScheduledTask) -> ScheduledTask:
        self._log.debug(f"Storing scheduled task {task.task_id} for user {task.user_id}")
        return self._write(task)

    def get(self, task_id: str) -> Optional[ScheduledTask]:
        payload = self._driver.get(self._task_key(task_id))
        if payload is None:
            return None
        return ScheduledTask.model_validate_json(payload)

    def update(self, task: ScheduledTask) -> ScheduledTask:
        return self._write(task)

    def delete(self, task_id: str) -> None:
        task = self.get(task_id)
        self._driver.delete(self._task_key(task_id))
        if task is not None:
            self._driver.srem(self._user_index_key(task.user_id), task_id)
        # The all-index is cleaned unconditionally: a record whose document already expired must
        # still lose its index membership, otherwise every later listing keeps skipping it.
        self._driver.srem(self._all_index_key(), task_id)

    def list(self, user_id: Optional[str] = None, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> Tuple[List[ScheduledTask], Optional[int]]:
        index_key = self._all_index_key() if user_id is None else self._user_index_key(user_id)
        tasks: List[ScheduledTask] = []
        for task_id in self._driver.smembers(index_key):
            task = self.get(task_id)
            # A member without a document is a task whose TTL elapsed ahead of the index set.
            if task is None:
                continue
            if user_id is not None and task.user_id != user_id:
                continue
            tasks.append(task)
        tasks.sort(key=lambda task: task.updated_at, reverse=True)
        return paginate(tasks, limit, offset)

    def record_trigger(self, task_id: str, request_id: Optional[str], occurred_at: str, completed: bool) -> None:
        task = self.get(task_id)
        if task is None:
            self._log.warning(f"Ignoring trigger record for unknown scheduled task {task_id}")
            return
        task.last_triggered_at = occurred_at
        task.last_request_id = request_id
        task.trigger_count += 1
        task.updated_at = utc_now_iso()
        if completed and task.status is not ScheduleStatus.CANCELLED:
            task.status = ScheduleStatus.COMPLETED
        self._write(task)

    def clear(self) -> None:
        self._log.debug(f"Clearing all scheduled task keys with prefix {self._prefix}")
        self._driver.clear_prefix()

    def _write(self, task: ScheduledTask) -> ScheduledTask:
        """Write a task document and (re)register it in both index sets.

        The index memberships are re-added on every write, not just on creation: under a configured
        TTL an index set can expire while the task is still live, and a task missing from the index
        would vanish from every listing.

        :param task: The full record to write.
        :return: The written task.
        """
        task_key = self._task_key(task.task_id)
        user_index_key = self._user_index_key(task.user_id)
        all_index_key = self._all_index_key()
        self._driver.set(task_key, task.model_dump_json())
        self._driver.sadd(user_index_key, task.task_id)
        self._driver.sadd(all_index_key, task.task_id)
        self._expire(task_key, user_index_key, all_index_key)
        return task
