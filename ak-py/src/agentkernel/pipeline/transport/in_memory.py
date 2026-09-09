import itertools
import threading
import time
import uuid
from collections import deque
from typing import Any, ClassVar, Deque, Dict, List, Optional, Tuple

from ..envelope import QueueMessage, QueueName
from .base import QueueTransport, TransportConsumer

# In-process redelivery exists to rescue a stuck/crashed worker *thread*; a process death loses
# the queues entirely. A tight timeout therefore buys nothing locally and risks double-running
# long LLM-bound agent turns, so the default is deliberately generous (vs SQS's 30 s).
DEFAULT_ACK_WAIT_SECONDS = 300.0
DEFAULT_DEDUP_WINDOW_SECONDS = 300.0


class _InMemoryQueue:
    """One in-process queue with SQS-FIFO-parity semantics (spec #495 §4).

    Per-group FIFO: messages are held in one deque per ``group_id`` (a message without a group
    gets a per-message synthetic group), and at most one message per group is in flight: one
    session in order, sessions in parallel. Unacked messages return to their group head after
    ``ack_wait`` with ``receive_count`` incremented; ``nack`` returns them immediately. ``send``
    drops messages whose ``dedup_id`` was seen within ``dedup_window``. No durability and no size
    bound (documented design boundary).
    """

    def __init__(self, name: QueueName, ack_wait: float, dedup_window: float):
        self._name = name
        self._ack_wait = ack_wait
        self._dedup_window = dedup_window
        self._lock = threading.Lock()
        self._ready_cond = threading.Condition(self._lock)
        self._groups: Dict[str, Deque[QueueMessage]] = {}
        self._ready: Deque[str] = deque()
        self._ready_set: set[str] = set()
        self._in_flight: Dict[str, Tuple[QueueMessage, float]] = {}  # group -> (message, redelivery deadline)
        self._message_group: Dict[int, str] = {}  # id(message) -> group, while in flight
        self._dedup: Dict[str, float] = {}  # dedup_id -> expiry
        self._synthetic_group_counter = itertools.count()

    def send(self, message: QueueMessage) -> Optional[dict]:
        """Enqueue a copy of the message; returns None when dropped by the dedup window."""
        now = time.monotonic()
        with self._ready_cond:
            self._prune_dedup(now)
            if message.dedup_id:
                if message.dedup_id in self._dedup:
                    return None
                self._dedup[message.dedup_id] = now + self._dedup_window

            stored = message.model_copy()
            if stored.message_id is None:
                stored.message_id = str(uuid.uuid4())
            group = stored.group_id or f"__msg-{next(self._synthetic_group_counter)}"
            self._groups.setdefault(group, deque()).append(stored)
            self._mark_ready(group)
            self._ready_cond.notify_all()
            return {"message_id": stored.message_id}

    def fetch(self, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        """Deliver the heads of up to ``batch_size`` distinct groups, blocking up to ``wait_seconds``."""
        deadline = time.monotonic() + wait_seconds
        with self._ready_cond:
            while True:
                now = time.monotonic()
                self._requeue_expired(now)

                batch: List[QueueMessage] = []
                while self._ready and len(batch) < batch_size:
                    group = self._ready.popleft()
                    self._ready_set.discard(group)
                    message = self._groups[group].popleft()
                    self._in_flight[group] = (message, now + self._ack_wait)
                    self._message_group[id(message)] = group
                    batch.append(message)
                if batch:
                    return batch

                remaining = deadline - now
                if remaining <= 0:
                    return []
                timeout = remaining
                if self._in_flight:
                    next_expiry = min(dl for _, dl in self._in_flight.values()) - now
                    if next_expiry <= 0:
                        continue
                    timeout = min(timeout, next_expiry)
                self._ready_cond.wait(timeout)

    def ack(self, message: QueueMessage) -> None:
        """Remove the message permanently and release its group for the next delivery."""
        with self._ready_cond:
            group = self._message_group.pop(id(message), None)
            if group is None:
                return  # already expired and requeued: at-least-once, the redelivery owns it now
            self._in_flight.pop(group, None)
            self._release_group(group)
            self._ready_cond.notify_all()

    def nack(self, message: QueueMessage) -> None:
        """Return the message to its group head immediately, with receive_count incremented.

        A stale handle (the message expired via ack_wait and was redelivered to another consumer)
        is a silent no-op, mirroring SQS rejecting an expired receipt handle.
        """
        with self._ready_cond:
            group = self._message_group.pop(id(message), None)
            if group is None:
                return
            self._in_flight.pop(group, None)
            self._requeue_at_head(group, message)
            self._ready_cond.notify_all()

    def _requeue_expired(self, now: float) -> None:
        """Return in-flight messages whose ack_wait deadline passed to their group heads."""
        for group in [g for g, (_, dl) in self._in_flight.items() if dl <= now]:
            message, _ = self._in_flight.pop(group)
            self._message_group.pop(id(message), None)
            self._requeue_at_head(group, message)

    def _requeue_at_head(self, group: str, message: QueueMessage) -> None:
        """Requeue a fresh copy at the group head with receive_count incremented.

        Requeuing a copy (not the original object) invalidates the previous delivery's handle:
        the consumer that still holds the original can no longer ack/nack it (its id() is gone
        from the registry), so a late ack after an ack_wait redelivery cannot release the group
        while the redelivery is still in flight, and a late nack cannot duplicate it. This
        preserves the one-in-flight-per-group guarantee (SQS FIFO parity: stale receipt handles
        are rejected).
        """
        requeued = message.model_copy()
        requeued.receive_count += 1
        self._groups.setdefault(group, deque()).appendleft(requeued)
        self._mark_ready(group)

    def _release_group(self, group: str) -> None:
        """After an ack: drop an emptied group or mark it deliverable again."""
        pending = self._groups.get(group)
        if not pending:
            self._groups.pop(group, None)
            return
        self._mark_ready(group)

    def _mark_ready(self, group: str) -> None:
        if group not in self._ready_set and group not in self._in_flight:
            self._ready.append(group)
            self._ready_set.add(group)

    def _prune_dedup(self, now: float) -> None:
        for dedup_id in [d for d, expiry in self._dedup.items() if expiry <= now]:
            del self._dedup[dedup_id]


class InMemoryTransportConsumer(TransportConsumer):
    """Consumer over one in-process queue. Cheap; one per consumer thread as per the contract."""

    def __init__(self, queue: _InMemoryQueue):
        self._queue = queue

    def fetch(self, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        return self._queue.fetch(batch_size, wait_seconds)

    def ack(self, message: QueueMessage) -> None:
        self._queue.ack(message)

    def nack(self, message: QueueMessage) -> None:
        self._queue.nack(message)


class InMemoryTransport(QueueTransport):
    """The default queue transport: full queue-mode semantics in-process, zero backing services.

    Queues are process-wide (class-level) so every component in the single-process topology:
    request handler, agent runner, response handler: sees the same two queues regardless of
    which factory call created its transport instance. The first construction fixes each queue's
    ``ack_wait``/``dedup_window``; later instances reuse the existing queues.
    """

    _queues: ClassVar[Dict[QueueName, _InMemoryQueue]] = {}
    _queues_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, ack_wait: float = DEFAULT_ACK_WAIT_SECONDS, dedup_window: float = DEFAULT_DEDUP_WINDOW_SECONDS):
        self._ack_wait = ack_wait
        self._dedup_window = dedup_window

    def _queue(self, queue: QueueName) -> _InMemoryQueue:
        with self._queues_lock:
            if queue not in self._queues:
                self._queues[queue] = _InMemoryQueue(queue, self._ack_wait, self._dedup_window)
            return self._queues[queue]

    def send(self, queue: QueueName, message: QueueMessage) -> Any:
        return self._queue(queue).send(message)

    def create_consumer(self, queue: QueueName) -> InMemoryTransportConsumer:
        return InMemoryTransportConsumer(self._queue(queue))

    @classmethod
    def reset(cls) -> None:
        """Drop all process-wide queue state. Test isolation only."""
        with cls._queues_lock:
            cls._queues.clear()
