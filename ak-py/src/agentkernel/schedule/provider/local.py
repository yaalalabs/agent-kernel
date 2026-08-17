"""In-process schedule provider: the default, for local development and single-process runs."""

import datetime
import heapq
import itertools
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import ClassVar, List, Optional, Tuple

from ...pipeline.envelope import QueueMessage, QueueName
from ...pipeline.transport.base import QueueTransport
from ..model import TOKEN_OCCURRENCE_TIME, TOKEN_REQUEST_ID, ScheduledTask, ScheduleStatus
from ..timing import OccurrenceCalculator
from .base import ScheduleProvider

# Occurrence-time format substituted into a trigger body. Second precision in UTC, matching the
# shape EventBridge Scheduler resolves its scheduled-time context attribute to, so the trigger
# contract reads the same whichever provider produced it.
OCCURRENCE_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class _ArmedTask:
    """A task with one occurrence armed in the scheduler thread's heap."""

    task: ScheduledTask
    body_template: str
    fire_time: datetime.datetime  # the armed occurrence, timezone-aware
    fire_at: float  # the same instant as epoch seconds, the heap's ordering key


class LocalScheduleProvider(ScheduleProvider):
    """Fires occurrences from a single daemon thread in this process.

    One min-heap of armed occurrences guarded by a condition variable: ``create``/``update``/
    ``delete`` adjust the heap and wake the thread, which sleeps until the earliest occurrence is
    due, delivers its trigger to the input queue, and re-arms the task's next occurrence. The
    thread starts on the first registration, so a process that never schedules anything never
    starts it.

    Transport-agnostic (the trigger contract is body-only, exactly as EventBridge's is), and
    deliberately process-bound: armed occurrences do not survive a restart, which is the
    documented boundary between this provider and a durable one.
    """

    supported_transports: ClassVar[Optional[frozenset[str]]] = None

    _log = logging.getLogger("ak.schedule.provider.local")

    def __init__(self, transport: QueueTransport):
        """Initialize the provider.

        :param transport: Queue transport the triggers are delivered through.
        """
        self._transport = transport
        self._armed: dict[str, _ArmedTask] = {}  # task_id -> its currently armed occurrence
        self._heap: List[Tuple[float, int, str]] = []  # (fire_at, sequence, task_id)
        self._sequence = itertools.count()  # keeps heap entries orderable when two share an instant
        self._condition = threading.Condition()
        self._thread: Optional[threading.Thread] = None

    def create(self, task: ScheduledTask, body_template: str) -> str:
        """Arm the task's first occurrence and start the scheduler thread if it is not running.

        :param task: The task to arm.
        :param body_template: The frozen trigger body.
        :return: The task id, which is this provider's reference.
        """
        self._arm(task, body_template)
        self._start_thread()
        return task.task_id

    def update(self, task: ScheduledTask, body_template: str) -> None:
        """Re-arm the amended task, dropping its previous occurrence.

        A task that is no longer active is simply disarmed: pausing and cancelling both reach the
        provider this way.

        :param task: The amended task.
        :param body_template: The re-frozen trigger body.
        """
        self._arm(task, body_template)
        self._start_thread()

    def delete(self, provider_ref: str) -> None:
        """Disarm the task. Disarming an unarmed task is a no-op.

        :param provider_ref: The task id returned by :meth:`create`.
        """
        with self._condition:
            self._armed.pop(provider_ref, None)
            self._condition.notify_all()

    def get(self, provider_ref: str) -> Optional[dict]:
        """Return the armed occurrence of a task.

        :param provider_ref: The task id returned by :meth:`create`.
        :return: The next fire time, or None when the task has nothing armed.
        """
        with self._condition:
            armed = self._armed.get(provider_ref)
        if armed is None:
            return None
        return {"task_id": armed.task.task_id, "next_fire_time": armed.fire_time.isoformat()}

    def _arm(self, task: ScheduledTask, body_template: str, after: Optional[datetime.datetime] = None) -> None:
        """Replace a task's armed occurrence with its next one, or disarm it when it has none.

        :param task: The task to arm.
        :param body_template: The frozen trigger body.
        :param after: Search the occurrence rule from this instant; now when omitted.
        """
        if task.status is not ScheduleStatus.ACTIVE:
            self.delete(task.task_id)
            return
        fire_time = OccurrenceCalculator.next_fire_time(task.spec, after=after)
        if fire_time is None:
            self._log.info(f"Scheduled task {task.task_id} has no further occurrences")
            self.delete(task.task_id)
            return
        with self._condition:
            self._armed[task.task_id] = _ArmedTask(task=task, body_template=body_template, fire_time=fire_time, fire_at=fire_time.timestamp())
            heapq.heappush(self._heap, (fire_time.timestamp(), next(self._sequence), task.task_id))
            self._condition.notify_all()
        self._log.debug(f"Armed scheduled task {task.task_id} for {fire_time.isoformat()}")

    def _start_thread(self) -> None:
        """Start the scheduler thread on first use. Daemon: it must never hold up a shutdown."""
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="ak-schedule-local", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        """Scheduler loop: sleep until the earliest armed occurrence is due, then deliver it."""
        while True:
            try:
                due = self._take_due_occurrence()
                if due is not None:
                    self._deliver(due)
            except Exception as exc:
                # The loop owns every future occurrence in this process, so it must outlive any
                # single failure.
                self._log.error(f"Local schedule loop iteration failed: {exc}")

    def _take_due_occurrence(self) -> Optional[_ArmedTask]:
        """Wait for the earliest armed occurrence and claim it once it is due.

        Claiming re-arms the task's following occurrence immediately, still under the lock, so a
        delivery that is slow cannot leave the task unarmed or resurrect one deleted mid-delivery.

        :return: The occurrence to deliver, or None when the wait ended without one (a new
                 registration arrived, or the earliest occurrence is not due yet).
        """
        with self._condition:
            while not self._heap:
                self._condition.wait()
            fire_at, _, task_id = self._heap[0]
            remaining = fire_at - time.time()
            if remaining > 0:
                self._condition.wait(timeout=remaining)
                return None
            heapq.heappop(self._heap)
            armed = self._armed.get(task_id)
            if armed is None or armed.fire_at != fire_at:
                # Stale entry: the task was disarmed, or re-armed at a different time.
                return None
            # The condition's lock is reentrant, so the re-arm joins this critical section.
            self._arm(armed.task, armed.body_template, after=armed.fire_time)
            return armed

    def _deliver(self, armed: _ArmedTask) -> None:
        """Substitute the occurrence's values into the frozen body and send it to the input queue.

        A failed send skips the occurrence: the task's following occurrence is already armed, so
        one unreachable queue does not end the schedule.

        :param armed: The occurrence being fired.
        """
        message = QueueMessage(
            body=self._substitute_tokens(armed.body_template, armed.fire_time),
            # Empty by design: EventBridge Scheduler cannot set message attributes, so the trigger
            # contract carries its metadata in the body and both providers deliver it identically.
            attributes={},
            group_id=self.message_group_id(armed.task),
            dedup_id=None,
        )
        self._log.info(f"Firing scheduled task {armed.task.task_id} for occurrence {armed.fire_time.isoformat()}")
        try:
            self._transport.send(QueueName.INPUT, message)
        except Exception as exc:
            self._log.error(f"Skipped occurrence of scheduled task {armed.task.task_id}: trigger delivery failed: {exc}")

    @staticmethod
    def _substitute_tokens(body_template: str, fire_time: datetime.datetime) -> str:
        """Fill the occurrence placeholders in a frozen trigger body.

        :param body_template: The frozen trigger body.
        :param fire_time: The occurrence being fired.
        :return: The body to send.
        """
        occurrence_time = fire_time.astimezone(datetime.timezone.utc).strftime(OCCURRENCE_TIME_FORMAT)
        return body_template.replace(TOKEN_REQUEST_ID, str(uuid.uuid4())).replace(TOKEN_OCCURRENCE_TIME, occurrence_time)
