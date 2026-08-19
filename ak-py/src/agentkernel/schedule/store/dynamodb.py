"""DynamoDB-backed scheduled-task store.

Expected table schema:
    Partition Key: ``task_id`` (S)
    Sort Key:      none
    TTL attribute: ``expiry_time`` (N) — Unix epoch seconds (optional, disabled by default)

Item layout (one item per task):
    task_id     -> the partition key
    data        -> the ScheduledTask as JSON
    user_id     -> owner, denormalized so a listing can filter without parsing every document
    updated_at  -> ISO-8601 timestamp, denormalized so a listing can sort the same way

Listings scan the table with a filter expression rather than using an index: schedules are a
low-cardinality resource (one item per registered task, no per-message growth), so the thread
store's precedent applies without needing a GSI.
"""

import logging
from typing import List, Optional, Tuple

from boto3.dynamodb.conditions import Attr

from ...core.config import AKConfig
from ...core.util.driver.dynamodb import DynamoDBDriver
from ...core.util.pagination import DEFAULT_PAGE_SIZE, paginate
from ..model import ScheduledTask, ScheduleStatus, utc_now_iso
from .base import ScheduleStore


class DynamoDBScheduleStore(ScheduleStore):
    """DynamoDB-backed implementation of the ScheduleStore interface."""

    def __init__(self):
        self._log = logging.getLogger("ak.schedule.store.dynamodb")
        schedule_config = AKConfig.get().schedule
        cfg = schedule_config.store.dynamodb if schedule_config is not None else None
        if cfg is None or not cfg.table_name:
            raise ValueError("AKConfig.schedule.store.dynamodb.table_name must be set to use DynamoDBScheduleStore")
        # A task is one item written whole, so the driver's own expiry_time handling is enough here
        # (unlike the thread store, which needs per-operation TTL decisions across several items).
        self._driver = DynamoDBDriver(table_name=cfg.table_name, partition_key="task_id", ttl=int(cfg.ttl))

    def create(self, task: ScheduledTask) -> ScheduledTask:
        self._log.debug(f"Storing scheduled task {task.task_id} for user {task.user_id}")
        return self._write(task)

    def get(self, task_id: str) -> Optional[ScheduledTask]:
        item = self._driver.get(task_id)
        if not item:
            return None
        return ScheduledTask.model_validate_json(item["data"])

    def update(self, task: ScheduledTask) -> ScheduledTask:
        return self._write(task)

    def delete(self, task_id: str) -> None:
        self._driver.delete(task_id)

    def list(self, user_id: Optional[str] = None, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> Tuple[List[ScheduledTask], Optional[int]]:
        scan_kwargs = {} if user_id is None else {"FilterExpression": Attr("user_id").eq(user_id)}
        tasks: List[ScheduledTask] = []
        resp = self._driver.table.scan(**scan_kwargs)
        while True:
            for item in resp.get("Items", []):
                tasks.append(ScheduledTask.model_validate_json(item["data"]))
            if "LastEvaluatedKey" not in resp:
                break
            resp = self._driver.table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **scan_kwargs)

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
        self._log.debug("Clearing all stored scheduled tasks")
        self._driver.clear_all()

    def _write(self, task: ScheduledTask) -> ScheduledTask:
        """Write a task as one item, carrying the attributes a listing filters and sorts on.

        :param task: The full record to write.
        :return: The written task.
        """
        self._driver.put(
            {
                "task_id": task.task_id,
                "data": task.model_dump_json(),
                "user_id": task.user_id,
                "updated_at": task.updated_at,
            }
        )
        return task
