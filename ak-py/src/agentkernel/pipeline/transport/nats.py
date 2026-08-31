"""NATS JetStream queue transport (spec #495 §7).

JetStream maps onto the pipeline's queue semantics more closely than any other broker here: the
server itself provides the visibility timeout (``ack_wait``), the exact delivery count
(``num_delivered``), a server-enforced delivery ceiling (``max_deliver``), publish-time
deduplication (``Nats-Msg-Id`` plus the stream's duplicate window), and a terminal disposition
(``term()``). Unlike Kafka, none of that has to be rebuilt, so this transport needs no bookkeeping
store.

Two things do need care:

- **The client is asyncio-only.** The pipeline's consumers are threads, so every client coroutine
  is dispatched onto one shared event loop running on a daemon thread (:class:`_NatsLoop`), the
  pattern the NATS maintainers recommend for thread-based consumers. One connection multiplexes
  every thread in the process.
- **Per-session ordering is the DIY part.** JetStream has no equivalent of an SQS message group,
  so sessions are hashed to a fixed number of partition subjects, each served by its own durable
  consumer with ``max_ack_pending=1``. That gives one in-flight message per partition, ordered,
  with partitions running in parallel: the same shape as the Kafka transport, except the server
  enforces it rather than the client buffering to achieve it.
"""

import asyncio
import logging
import random
import threading
import time
import zlib
from typing import Any, Dict, List, Optional

import nats
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js.api import ConsumerConfig, RetentionPolicy, StreamConfig
from nats.js.errors import NotFoundError

from ...core.util.factory import AKConfigError
from ..envelope import QueueMessage, QueueName
from .base import QueueTransport, TransportConsumer

_log = logging.getLogger("ak.pipeline.transport.nats")

# JetStream's own deduplication header.
MSG_ID_HEADER = "Nats-Msg-Id"
# The session id travels as a header as well as a subject token: subject tokens cannot contain
# dots, so the header is the authoritative value and the token is for routing and observability.
GROUP_ID_HEADER = "Ak-Group-Id"

# Floor on a single partition's fetch wait. Cycling many partitions with a tiny timeout each would
# spend more time on round trips than on waiting for work.
MIN_PARTITION_FETCH_SECONDS = 0.05


class _NatsLoop:
    """One asyncio event loop on a daemon thread, shared by every thread in the process.

    ``nats-py`` has no synchronous API, and the pipeline's consumers are threads. Rather than each
    thread owning a loop (and therefore a connection), coroutines are submitted to this single loop
    and waited on with a timeout, which is the pattern the NATS maintainers publish for exactly
    this situation.
    """

    _loop: Optional[asyncio.AbstractEventLoop] = None
    _thread: Optional[threading.Thread] = None
    _lock = threading.Lock()

    @classmethod
    def loop(cls) -> asyncio.AbstractEventLoop:
        with cls._lock:
            if cls._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(target=loop.run_forever, name="nats-event-loop", daemon=True)
                thread.start()
                cls._loop, cls._thread = loop, thread
            return cls._loop

    @classmethod
    def run(cls, coro, timeout: float) -> Any:
        """Run a coroutine on the shared loop and wait for its result.

        :raises TimeoutError: if the coroutine does not finish within ``timeout``. The coroutine is
            cancelled so a stalled call cannot leak work onto the loop.
        """
        future = asyncio.run_coroutine_threadsafe(coro, cls.loop())
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise

    @classmethod
    def reset(cls) -> None:
        """Stop the loop thread. Test isolation only."""
        with cls._lock:
            if cls._loop is not None:
                cls._loop.call_soon_threadsafe(cls._loop.stop)
            cls._loop, cls._thread = None, None


class NatsTransportConsumer(TransportConsumer):
    """Consumer over one stream's partition consumers. One instance per consumer thread.

    A fetch cycles the partition subscriptions rather than watching one queue, because work is
    spread across partitions and each partition allows a single in-flight message. The cursor
    advances across calls and starts at a random offset per instance, so threads and replicas
    neither converge on the same partition nor starve any of them.
    """

    def __init__(self, subscriptions: Dict[int, Any], request_timeout: float, retry_backoff: float, stream: str):
        self._subscriptions = subscriptions
        self._request_timeout = request_timeout
        self._retry_backoff = retry_backoff
        self._stream = stream
        self._partitions = sorted(subscriptions)
        self._cursor = random.randrange(len(self._partitions)) if self._partitions else 0

    def fetch(self, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        if not self._partitions:
            return []

        idle_wait = max(wait_seconds / len(self._partitions), MIN_PARTITION_FETCH_SECONDS)
        deadline = time.monotonic() + wait_seconds
        messages: List[QueueMessage] = []

        for _ in range(len(self._partitions)):
            if len(messages) >= batch_size or time.monotonic() >= deadline:
                break
            partition = self._partitions[self._cursor % len(self._partitions)]
            self._cursor += 1
            # Once the batch holds something, the remaining partitions are only a top-up and get
            # the floor wait rather than their full slice. A pull always burns its whole timeout,
            # so waiting them out would hold the messages already in hand for the rest of the
            # fetch window: that is added latency on every message, and their server-side ack_wait
            # is already ticking, so a short ack_wait can make a message redeliverable before the
            # caller ever sees it and break the one-in-flight guarantee.
            partition_wait = MIN_PARTITION_FETCH_SECONDS if messages else idle_wait
            messages.extend(self._fetch_partition(partition, batch_size - len(messages), partition_wait))
        return messages

    def ack(self, message: QueueMessage) -> None:
        _NatsLoop.run(message.native.ack(), self._request_timeout)

    def nack(self, message: QueueMessage) -> None:
        """Return the message for redelivery after the configured delay.

        The server owns the redelivery, so unlike Kafka there is nothing to hold locally and the
        consumer thread does not sleep out the backoff.
        """
        _NatsLoop.run(message.native.nak(delay=self._retry_backoff), self._request_timeout)

    def dead_letter(self, message: QueueMessage) -> None:
        """Terminate delivery of a message that exhausted its retries.

        ``term()`` is JetStream's terminal disposition: it stops redelivery and removes the message
        from the work-queue stream, which a plain ack would also do but without recording intent.
        The server's ``max_deliver`` is the backstop if this never runs. The component's
        permanent-failure hook has already delivered the error to the caller, so no dead-letter
        stream is needed to avoid losing the response.
        """
        try:
            _NatsLoop.run(message.native.term(), self._request_timeout)
            _log.warning(f"Terminated message {message.message_id} on stream {self._stream} after {message.receive_count} deliveries")
        except Exception:
            # A failed term leaves the server to stop redelivery at max_deliver, so the message
            # cannot loop forever; log and move on rather than blocking the consumer.
            _log.exception(f"Failed to terminate message {message.message_id} on stream {self._stream}")

    def close(self) -> None:
        for partition, subscription in self._subscriptions.items():
            try:
                _NatsLoop.run(subscription.unsubscribe(), self._request_timeout)
            except Exception:
                _log.debug(f"Failed to unsubscribe partition {partition} of {self._stream}", exc_info=True)
        self._subscriptions = {}
        self._partitions = []

    # -- internals ---------------------------------------------------------------------------

    def _fetch_partition(self, partition: int, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        subscription = self._subscriptions[partition]
        try:
            raw = _NatsLoop.run(subscription.fetch(batch=max(batch_size, 1), timeout=wait_seconds), wait_seconds + self._request_timeout)
        except (NatsTimeoutError, TimeoutError):
            return []  # an idle partition, which is the common case when work is sparse
        return [self._to_envelope(message) for message in raw]

    @staticmethod
    def _to_envelope(message: Any) -> QueueMessage:
        headers = dict(message.headers or {})
        dedup_id = headers.pop(MSG_ID_HEADER, None)
        group_id = headers.pop(GROUP_ID_HEADER, None)
        metadata = message.metadata
        return QueueMessage(
            body=message.data.decode() if isinstance(message.data, (bytes, bytearray)) else (message.data or ""),
            attributes=headers,
            group_id=group_id,
            dedup_id=dedup_id,
            # num_delivered is 1 on the first delivery, matching the envelope's contract exactly.
            receive_count=metadata.num_delivered,
            message_id=f"{metadata.stream}:{metadata.sequence.stream}",
            native=message,
        )


class NatsTransport(QueueTransport):
    """JetStream-backed queue transport: the recommended on-prem broker for the pipeline.

    Streams and partition consumers are provisioned once per process (when ``auto_provision`` is
    on) or verified and reported as missing (when it is off, which is the production posture).
    """

    _connections: Dict[str, Any] = {}
    _connections_lock = threading.Lock()
    # Streams whose provisioning has *completed*, plus one lock per stream so concurrent callers
    # for the same stream queue up instead of racing (see _ensure_provisioned).
    _provisioned: set = set()
    _provision_locks: Dict[str, threading.Lock] = {}
    _provisioned_lock = threading.Lock()

    def __init__(
        self,
        url: str,
        input_stream: str,
        input_subject_prefix: str,
        output_stream: str,
        output_subject_prefix: str,
        partitions: int = 32,
        ack_wait: float = 300.0,
        retry_backoff: float = 2.0,
        duplicate_window: float = 300.0,
        max_age: float = 86400.0,
        request_timeout: float = 10.0,
        auto_provision: bool = False,
        max_deliver: Optional[Dict[QueueName, int]] = None,
    ):
        if partitions < 1:
            raise AKConfigError(f"execution.queues.nats.partitions must be >= 1, got {partitions}")
        self._url = url
        self._streams = {QueueName.INPUT: input_stream, QueueName.OUTPUT: output_stream}
        self._prefixes = {QueueName.INPUT: input_subject_prefix, QueueName.OUTPUT: output_subject_prefix}
        self._partitions = partitions
        self._ack_wait = ack_wait
        self._retry_backoff = retry_backoff
        self._duplicate_window = duplicate_window
        self._max_age = max_age
        self._request_timeout = request_timeout
        self._auto_provision = auto_provision
        # Server-side delivery ceiling per queue: one more than the loop's own limit, so the client
        # hook runs on the last delivery and the server is only the backstop behind it.
        self._max_deliver = max_deliver or {}

    # -- send side ---------------------------------------------------------------------------

    def send(self, queue: QueueName, message: QueueMessage) -> Any:
        """Publish to the session's partition subject and wait for the stream's acknowledgement."""
        self._ensure_provisioned(queue)

        headers = {name: str(value) for name, value in message.attributes.items()}
        if message.dedup_id:
            headers[MSG_ID_HEADER] = message.dedup_id
        if message.group_id:
            headers[GROUP_ID_HEADER] = message.group_id

        subject = self.subject_for(queue, message.group_id)
        ack = _NatsLoop.run(
            self._jetstream().publish(subject, message.body.encode(), headers=headers or None),
            self._request_timeout,
        )
        # A duplicate is not an error: the stream's window rejected a repeat of a dedup id, which
        # is the behaviour the pipeline asks for.
        if getattr(ack, "duplicate", False):
            _log.info(f"Stream {self._streams[queue]} dropped a duplicate publish (dedup_id={message.dedup_id})")
        return {"MessageId": f"{self._streams[queue]}:{getattr(ack, 'seq', '')}"}

    def subject_for(self, queue: QueueName, group_id: Optional[str]) -> str:
        """The partition subject a session's messages travel on."""
        partition = self.partition_for(group_id)
        return f"{self._prefixes[queue]}.{partition}.{_subject_token(group_id)}"

    def partition_for(self, group_id: Optional[str]) -> int:
        """Map a session to a partition with a hash that is stable across processes.

        Deliberately not Python's ``hash()``: string hashing is salted per interpreter, so two pods
        would disagree about a session's partition and its ordering guarantee would evaporate.
        """
        if not group_id:
            return 0
        return zlib.crc32(group_id.encode()) % self._partitions

    # -- receive side ------------------------------------------------------------------------

    def create_consumer(self, queue: QueueName) -> NatsTransportConsumer:
        self._ensure_provisioned(queue)
        stream = self._streams[queue]
        subscriptions = {
            partition: _NatsLoop.run(
                self._jetstream().pull_subscribe_bind(durable=self._durable_name(stream, partition), stream=stream),
                self._request_timeout,
            )
            for partition in range(self._partitions)
        }
        return NatsTransportConsumer(
            subscriptions=subscriptions,
            request_timeout=self._request_timeout,
            retry_backoff=self._retry_backoff,
            stream=stream,
        )

    def check_consumer_capacity(self, queue: QueueName, num_consumers: int) -> None:
        """Warn when partitions cannot keep the configured consumers busy.

        Each partition consumer allows one in-flight message, so the partition count is the ceiling
        on concurrent work no matter how many threads or replicas are polling.
        """
        if self._partitions < num_consumers:
            _log.warning(
                f"Stream {self._streams[queue]} has {self._partitions} partition(s) but {num_consumers} consumer(s) are "
                f"configured for it: only {self._partitions} message(s) can be in flight at once, because each "
                "partition consumer allows one. Raise execution.queues.nats.partitions or lower "
                f"execution.queues.{queue.value}.no_of_consumers (note that changing partitions re-maps sessions)."
            )
        else:
            _log.info(f"Stream {self._streams[queue]}: {self._partitions} partition(s) for {num_consumers} configured consumer(s)")

    # -- provisioning ------------------------------------------------------------------------

    def _ensure_provisioned(self, queue: QueueName) -> None:
        """Create or verify the stream and its partition consumers, once per process per stream.

        The stream is recorded as provisioned only after the work has actually finished, and callers
        for the same stream queue behind one lock. Both matter because a pipeline component starts
        several consumer threads at once: if a thread could see the record while another was still
        creating the objects, it would race ahead to ``pull_subscribe_bind`` and die on a consumer
        that does not exist yet. Locking per stream rather than globally lets the input and output
        streams provision concurrently.
        """
        stream = self._streams[queue]
        cache_key = f"{self._url}:{stream}"
        with self._provisioned_lock:
            if cache_key in self._provisioned:
                return
            provision_lock = self._provision_locks.setdefault(cache_key, threading.Lock())

        with provision_lock:
            if cache_key in self._provisioned:
                return  # another thread finished the work while this one waited for the lock

            if self._auto_provision:
                self._provision(queue, stream)
            else:
                self._verify(queue, stream)

            # Only now: a failure leaves the stream unrecorded so the next call retries instead of
            # skipping and failing somewhere less obvious.
            with self._provisioned_lock:
                self._provisioned.add(cache_key)

    def _provision(self, queue: QueueName, stream: str) -> None:
        jetstream = self._jetstream()
        subjects = [f"{self._prefixes[queue]}.>"]
        try:
            _NatsLoop.run(jetstream.stream_info(stream), self._request_timeout)
        except NotFoundError:
            _log.info(f"Creating JetStream stream {stream} for subjects {subjects}")
            _NatsLoop.run(
                jetstream.add_stream(
                    StreamConfig(
                        name=stream,
                        subjects=subjects,
                        # Work-queue retention is the closest match to SQS: a terminal ack removes
                        # the message. max_age is the safety net, since an unconsumed work-queue
                        # message is otherwise kept forever.
                        retention=RetentionPolicy.WORK_QUEUE,
                        duplicate_window=self._duplicate_window,
                        max_age=self._max_age,
                    )
                ),
                self._request_timeout,
            )

        for partition in range(self._partitions):
            durable = self._durable_name(stream, partition)
            try:
                _NatsLoop.run(jetstream.consumer_info(stream, durable), self._request_timeout)
            except NotFoundError:
                _NatsLoop.run(jetstream.add_consumer(stream, config=self._consumer_config(queue, partition)), self._request_timeout)
        _log.info(f"Stream {stream} provisioned with {self._partitions} partition consumer(s)")

    def _verify(self, queue: QueueName, stream: str) -> None:
        jetstream = self._jetstream()
        try:
            _NatsLoop.run(jetstream.stream_info(stream), self._request_timeout)
        except NotFoundError as e:
            raise AKConfigError(
                f"JetStream stream '{stream}' does not exist. Create it (a NACK Stream CR, or the nats CLI) or set "
                "execution.queues.nats.auto_provision: true to have Agent Kernel create it at startup."
            ) from e

        missing = []
        for partition in range(self._partitions):
            durable = self._durable_name(stream, partition)
            try:
                _NatsLoop.run(jetstream.consumer_info(stream, durable), self._request_timeout)
            except NotFoundError:
                missing.append(durable)
        if missing:
            raise AKConfigError(
                f"JetStream stream '{stream}' is missing {len(missing)} of {self._partitions} partition consumer(s), "
                f"starting with '{missing[0]}'. Create them (NACK Consumer CRs) or set "
                "execution.queues.nats.auto_provision: true. Each consumer filters "
                f"'{self._prefixes[queue]}.<partition>.>' with max_ack_pending=1."
            )

    def _consumer_config(self, queue: QueueName, partition: int) -> ConsumerConfig:
        return ConsumerConfig(
            durable_name=self._durable_name(self._streams[queue], partition),
            # Non-overlapping filters are a hard requirement on a work-queue stream.
            filter_subject=f"{self._prefixes[queue]}.{partition}.>",
            ack_wait=self._ack_wait,
            # Defaults to the loop's default max_receive_count (3) plus one when the caller did not
            # supply a ceiling, so the server never cuts delivery short of the client's own limit.
            max_deliver=self._max_deliver.get(queue, 4),
            # The whole point of partitioning: one message at a time per partition keeps a
            # session's turns ordered while other partitions run in parallel.
            max_ack_pending=1,
        )

    @staticmethod
    def _durable_name(stream: str, partition: int) -> str:
        return f"{stream}-p{partition}"

    # -- connection --------------------------------------------------------------------------

    def _jetstream(self) -> Any:
        return self._client().jetstream()

    def _client(self) -> Any:
        with self._connections_lock:
            client = self._connections.get(self._url)
            if client is None or not getattr(client, "is_connected", False):
                _log.info(f"Connecting to NATS at {self._url}")
                client = _NatsLoop.run(nats.connect(servers=self._server_list()), self._request_timeout)
                self._connections[self._url] = client
            return client

    def _server_list(self) -> List[str]:
        """Split the configured URL into servers, tolerating spaces around the commas.

        ``url`` is documented as comma-separated for a cluster, and writing it with spaces after the
        commas is natural; an untrimmed entry would be handed to the client verbatim and fail to
        connect.
        """
        return [server.strip() for server in self._url.split(",") if server.strip()]

    @classmethod
    def reset(cls) -> None:
        """Drop the process-wide connection cache and provisioning latch. Test isolation only."""
        with cls._connections_lock:
            cls._connections.clear()
        with cls._provisioned_lock:
            cls._provisioned.clear()
            cls._provision_locks.clear()


def _subject_token(group_id: Optional[str]) -> str:
    """Make a session id safe as a single subject token (no dots, spaces, or wildcards)."""
    if not group_id:
        return "_"
    return "".join("_" if character in ".* >\t" else character for character in group_id)
