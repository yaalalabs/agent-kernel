import asyncio
import inspect
import logging
import time
from typing import Callable, Optional

from .envelope import QueueMessage, QueueName
from .thread_runner import ThreadRunner
from .transport.base import TransportConsumer


class ConsumerLoop:
    """Generic queue-consumer machinery: batch loop, receive-count check, and the
    permanent-failure-then-ack flow (spec #495 §3, extracted from ECSSQSConsumer).

    Semantics, in order:

    1. ``run()`` starts ``num_consumers`` ThreadRunner tasks (``stop_all_on_failure=True,
       graceful=True``); each thread owns one ``TransportConsumer`` from ``consumer_factory``
       and loops until ``ThreadRunner.shutdown_event`` is set.
    2. Per message: ``receive_count > max_receive_count`` runs ``on_permanent_failure`` (which
       must catch its own exceptions) then hands the message to the transport's
       ``dead_letter`` disposition (which acks by default); otherwise ``process`` then ack. A
       raising ``process`` logs and nacks: redelivery is the transport's own mechanics.
    3. A raising ``fetch`` logs and retries after a fixed back-off.
    4. ``process`` may be an async callable; it is detected and driven via ``asyncio.run``.
    """

    _POLL_ERROR_BACKOFF_SECONDS = 5

    def __init__(
        self,
        *,
        process: Callable[[QueueMessage], None],
        on_permanent_failure: Callable[[QueueMessage], None],
        max_receive_count: int,
        num_consumers: int,
        batch_size: int,
        consumer_factory: Callable[[], TransportConsumer],
        thread_name_prefix: str,
        queue: Optional[QueueName] = None,
        wait_seconds: float = 20.0,
        logger: Optional[logging.Logger] = None,
        exit_on_shutdown: bool = True,
    ):
        """
        :param process: Handles one message; raising leaves the message for redelivery.
        :param on_permanent_failure: Runs when a message exceeds ``max_receive_count``; must be
            internally defensive: if it raises, the message is not acked and loops back.
        :param max_receive_count: Deliveries after which a message is permanently failed.
        :param num_consumers: Number of consumer threads.
        :param batch_size: Messages requested per fetch.
        :param consumer_factory: Creates the per-thread ``TransportConsumer``.
        :param thread_name_prefix: Thread names become ``{prefix}-{i}``.
        :param queue: Optional queue label, used in logs only.
        :param wait_seconds: Long-poll wait passed to ``fetch``.
        :param logger: Logger to emit on; defaults to ``ak.pipeline.consumer``. Legacy consumers
            pass their own so operator log filters keep working.
        :param exit_on_shutdown: Forwarded to ``ThreadRunner.run``. Loops nested inside an
            IOHandler task pass False so the drain returns (letting every sibling loop finish
            its in-flight work) and only the outermost runner exits the process.
        """
        self._process = process
        self._on_permanent_failure = on_permanent_failure
        self._max_receive_count = max_receive_count
        self._num_consumers = num_consumers
        self._batch_size = batch_size
        self._consumer_factory = consumer_factory
        self._thread_name_prefix = thread_name_prefix
        self._queue = queue
        self._wait_seconds = wait_seconds
        self._log = logger or logging.getLogger("ak.pipeline.consumer")
        self._exit_on_shutdown = exit_on_shutdown

    def run(self) -> None:
        """Block forever, consuming the queue with ``num_consumers`` threads."""
        if self._num_consumers < 1:
            raise ValueError(f"num_consumers must be >= 1, got {self._num_consumers}")
        queue_label = f"{self._queue.value} queue, " if self._queue else ""
        self._log.debug(f"ConsumerLoop starting: {queue_label}consumers: {self._num_consumers}")
        ThreadRunner.run(
            tasks=[
                ThreadRunner.Task(
                    execution_function=self._consumer_loop,
                    thread_name=f"{self._thread_name_prefix}-{i}",
                    stop_all_on_failure=True,
                    graceful=True,
                )
                for i in range(self._num_consumers)
            ],
            max_workers=self._num_consumers,
            exit_on_shutdown=self._exit_on_shutdown,
        )

    # Long fetch waits are sliced so the loop re-checks shutdown_event about once a second: a
    # signal-initiated drain must not stall for a full long-poll interval. A consumer whose long
    # polls are expensive to slice raises its own cap via
    # ``TransportConsumer.fetch_wait_slice_seconds`` (SQS bills every receive call, so it takes
    # a single 20 s wait and the slower drain).
    _MAX_FETCH_WAIT_SLICE_SECONDS = 1.0

    def _consumer_loop(self) -> None:
        """One consumer thread: fetch batches and process them until shutdown."""
        consumer = self._consumer_factory()
        slice_cap = consumer.fetch_wait_slice_seconds
        if slice_cap is None:
            slice_cap = self._MAX_FETCH_WAIT_SLICE_SECONDS
        fetch_wait = min(self._wait_seconds, slice_cap)
        try:
            while not ThreadRunner.shutdown_event.is_set():
                try:
                    messages = consumer.fetch(self._batch_size, fetch_wait)
                except Exception:
                    self._log.exception(f"Unexpected error in poll loop — retrying in {self._POLL_ERROR_BACKOFF_SECONDS} s")
                    time.sleep(self._POLL_ERROR_BACKOFF_SECONDS)
                    continue

                if messages:
                    self._log.debug(f"Processing batch of {len(messages)} message(s)")
                    for message in messages:
                        self._process_single(consumer, message)
        finally:
            consumer.close()

    def _process_single(self, consumer: TransportConsumer, message: QueueMessage) -> None:
        """Process one message with the receive-count / permanent-failure / ack semantics."""
        message_id = message.message_id or "<unknown>"
        self._log.debug(f"Processing message {message_id} (receive_count={message.receive_count})")
        try:
            if message.receive_count > self._max_receive_count:
                self._log.warning(f"Message {message_id} exceeded max_receive_count ({message.receive_count} > {self._max_receive_count})")
                self._on_permanent_failure(message)
                # Terminal disposition, not a plain ack: transports may dead-letter first
                # (the default implementation is exactly the previous ack).
                consumer.dead_letter(message)
                return

            underlying_fn = getattr(self._process, "__func__", self._process)
            if inspect.iscoroutinefunction(underlying_fn):
                asyncio.run(self._process(message))
            else:
                self._process(message)

            consumer.ack(message)
            self._log.debug(f"Processed and deleted message {message_id}")

        except Exception:
            self._log.exception(f"Failed to process message {message_id} — leaving in queue for visibility-timeout retry")
            self._safe_nack(consumer, message)

    def _safe_nack(self, consumer: TransportConsumer, message: QueueMessage) -> None:
        """Nack without letting a transport error take down the consumer thread."""
        try:
            consumer.nack(message)
        except Exception:
            self._log.exception(f"Failed to nack message {message.message_id}")
