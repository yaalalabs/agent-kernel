"""Google Cloud Pub/Sub queue transport (spec #886 §1).

Pub/Sub gives per-key ordering (ordering keys), durability and a server-side dead-letter policy,
but less than the pipeline contract needs (``docs/specs/886-gcp-queue-mode/research``):

- **No exact delivery count.** ``delivery_attempt`` is approximate and can reset, so receive
  counts come from a :class:`BookkeepingStore`, as on Kafka.
- **No publish-side deduplication.** A publisher retry arrives with a new message id, so dedup is
  a consume-side claim on the envelope's ``dedup_id``, as on Kafka.
- **A pull can return several messages for one ordering key**, and Pub/Sub sends a key's next
  batch only once the outstanding one is acked or has lapsed. The consumer holds the batch and
  serves it one message at a time, which keeps one message in flight per session.
- **Redelivering a message redelivers every later message for its key, acknowledged ones
  included.** Acknowledged messages are therefore remembered for the dedup window, and a
  redelivered copy is acknowledged again without running.
- **Unary pull does not extend leases.** A :class:`_LeaseKeeper` thread per consumer renews the
  ack deadline of every fetched, unsettled message until ``ack_wait``; a turn that outlives it is
  redelivered, as on NATS.

The whole envelope travels in the message data, because Pub/Sub caps attributes at 100 per
message and 1024 bytes per value, while the ``reply_`` context alone may be 8192 bytes.
"""

import base64
import binascii
import json
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import google.auth
from google.api_core import exceptions as google_exceptions
from google.cloud import pubsub_v1

from ...core.util.factory import AKConfigError
from ..envelope import QueueMessage, QueueName
from .base import QueueTransport, TransportConsumer
from .bookkeeping import BookkeepingStore, BookkeepingStoreFactory

_log = logging.getLogger("ak.pipeline.transport.pubsub")

# Ack deadline set on every renewal. Six times the refresh interval, so five missed renewals in a
# row still leave the lease intact.
LEASE_EXTENSION_SECONDS = 60
# How often a consumer's lease keeper renews the deadlines of the messages it holds.
LEASE_REFRESH_SECONDS = 10
# The subscription's own ack deadline (Pub/Sub's minimum). The transport renews leases itself, so
# this only covers the moment between a pull response and the first renewal, and a message lost
# in transit to a cancelled pull, which comes back after this long.
SUBSCRIPTION_ACK_DEADLINE_SECONDS = 10
# Pub/Sub's own default for max_delivery_attempts, used when the factory supplies none.
DEFAULT_MAX_DELIVERY_ATTEMPTS = 5
# Floor on a pull's client deadline: a zero or negative gRPC deadline fails before it is sent.
MIN_PULL_TIMEOUT_SECONDS = 0.05
# Attribute added to a message copied to a dead-letter topic.
ERROR_ATTRIBUTE = "ak-error"
# The error attribute of a message that is not an Agent Kernel envelope.
QUARANTINE_REASON = "not an Agent Kernel envelope"


class PubSubEnvelopeCodec:
    """Encodes a :class:`QueueMessage` to Pub/Sub message data and attributes, and back.

    The data is the JSON object ``{"body", "attributes", "dedup_id", "group_id"}``. ``group_id`` also
    travels as the ordering key, which is what orders delivery; the copy in the data keeps the
    envelope whole where the ordering key does not arrive (the emulator's push requests omit it).
    The only Pub/Sub attribute is a version marker, which lets a future encoding be detected and
    lets operators filter Agent Kernel traffic.
    """

    ENVELOPE_ATTRIBUTE = "ak-envelope"
    ENVELOPE_VERSION = "1"

    @classmethod
    def encode(cls, message: QueueMessage) -> tuple[bytes, dict[str, str]]:
        """
        :param message: The envelope to send.
        :return: The Pub/Sub message data and attributes.
        """
        payload = {"body": message.body, "attributes": dict(message.attributes), "dedup_id": message.dedup_id, "group_id": message.group_id}
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        return data, {cls.ENVELOPE_ATTRIBUTE: cls.ENVELOPE_VERSION}

    @classmethod
    def decode(cls, data: bytes, attributes: Mapping[str, str], ordering_key: str, message_id: str) -> QueueMessage:
        """
        :param data: The Pub/Sub message data.
        :param attributes: The Pub/Sub message attributes.
        :param ordering_key: The Pub/Sub ordering key (``""`` when the message had none).
        :param message_id: The Pub/Sub message id.
        :return: The envelope, with ``receive_count`` left for the consumer to set.
        :raises ValueError: If the message is not an Agent Kernel envelope.
        """
        if attributes.get(cls.ENVELOPE_ATTRIBUTE) != cls.ENVELOPE_VERSION:
            raise ValueError(f"missing {cls.ENVELOPE_ATTRIBUTE}={cls.ENVELOPE_VERSION} attribute")
        try:
            payload = json.loads(bytes(data).decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"message data is not an envelope: {e}") from e

        if not isinstance(payload, dict):
            raise ValueError("message data is not a JSON object")
        body, envelope_attributes, dedup_id = payload.get("body"), payload.get("attributes"), payload.get("dedup_id")
        group_id = payload.get("group_id")
        if not isinstance(body, str):
            raise ValueError("envelope body is not a string")
        if not isinstance(envelope_attributes, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in envelope_attributes.items()):
            raise ValueError("envelope attributes are not a string map")
        if dedup_id is not None and not isinstance(dedup_id, str):
            raise ValueError("envelope dedup_id is not a string")
        if group_id is not None and not isinstance(group_id, str):
            raise ValueError("envelope group_id is not a string")

        return QueueMessage(
            body=body,
            attributes=envelope_attributes,
            group_id=ordering_key or group_id or None,
            dedup_id=dedup_id,
            message_id=message_id,
        )


@dataclass(frozen=True, eq=False)
class _Received:
    """One pulled message, as the consumer tracks it. Identity, not value, decides equality."""

    ack_id: str
    message_id: str
    ordering_key: str
    data: bytes
    attributes: dict[str, str] = field(default_factory=dict)
    envelope: QueueMessage | None = None  # None when the message could not be decoded


class _LeaseKeeper:
    """Renews the ack deadlines of a consumer's unsettled messages until ``ack_wait`` has passed.

    Unary pull leaves lease management to the caller. One daemon thread per consumer renews every
    leased message each ``LEASE_REFRESH_SECONDS``; once a message has been held for ``ack_wait`` it
    is no longer renewed, its lease lapses and Pub/Sub redelivers it. The registry is the only
    state shared with the consumer thread, so it is the only state behind a lock.
    """

    def __init__(
        self,
        subscriber: Any,
        subscription: str,
        ack_wait: float,
        request_timeout: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        """
        :param subscriber: The consumer's ``SubscriberClient``.
        :param subscription: Full subscription path.
        :param ack_wait: Seconds after which a message is no longer renewed.
        :param request_timeout: Timeout of each renewal call.
        :param clock: Monotonic clock; injectable for tests.
        """
        self._subscriber = subscriber
        self._subscription = subscription
        self._ack_wait = ack_wait
        self._request_timeout = request_timeout
        self._clock = clock
        self._leases: dict[str, float] = {}  # ack_id -> fetched_at
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def deadline_for(remaining: float) -> int:
        """The deadline to set for a lease with ``remaining`` seconds left: whole seconds, 1 to 60."""
        return max(1, math.ceil(min(LEASE_EXTENSION_SECONDS, remaining)))

    def start(self) -> None:
        """Start the renewal thread."""
        name = self._subscription.rsplit("/", 1)[-1]
        self._thread = threading.Thread(target=self._run, name=f"pubsub-lease-{name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop renewing. The thread exits at its next wake-up; nothing waits for it."""
        self._stopped.set()

    def add(self, ack_ids: list[str]) -> None:
        """Start leasing ``ack_ids``, counting ``ack_wait`` from now."""
        now = self._clock()
        with self._lock:
            for ack_id in ack_ids:
                self._leases[ack_id] = now

    def remove(self, ack_ids: list[str]) -> None:
        """Stop leasing ``ack_ids`` (the messages were settled or dropped)."""
        with self._lock:
            for ack_id in ack_ids:
                self._leases.pop(ack_id, None)

    def leased(self) -> set[str]:
        """The ack ids currently leased."""
        with self._lock:
            return set(self._leases)

    def tick(self) -> None:
        """One renewal pass: renew every lease with time left, drop the ones past ``ack_wait``."""
        now = self._clock()
        by_deadline: dict[int, list[str]] = {}
        with self._lock:
            for ack_id, fetched_at in list(self._leases.items()):
                remaining = self._ack_wait - (now - fetched_at)
                if remaining <= 0:
                    # Let the lease lapse: Pub/Sub redelivers the message, as NATS does past ack_wait.
                    del self._leases[ack_id]
                    continue
                by_deadline.setdefault(self.deadline_for(remaining), []).append(ack_id)

        for deadline, ack_ids in by_deadline.items():
            try:
                self._subscriber.modify_ack_deadline(
                    request={"subscription": self._subscription, "ack_ids": ack_ids, "ack_deadline_seconds": deadline},
                    timeout=self._request_timeout,
                )
            except Exception:
                # The lease still has up to LEASE_EXTENSION_SECONDS left; the next tick retries.
                _log.warning(f"Failed to renew {len(ack_ids)} lease(s) on {self._subscription}; retrying next tick", exc_info=True)

    def _run(self) -> None:
        # The module constant is read on every wait, so tests can lengthen it.
        while not self._stopped.wait(LEASE_REFRESH_SECONDS):
            self.tick()


class _DeliveryLedger:
    """Decides whether a delivery on one subscription runs, and with what ``receive_count``.

    Shared by the pull consumer and the push receiver. Pub/Sub's delivery count is approximate and
    it redelivers acknowledged messages (an ordering-key cascade, or an ack lost in transit), so
    exact counts, deduplication on ``dedup_id`` and the memory of acknowledged messages live in the
    bookkeeping store, keyed by the full subscription path.
    """

    def __init__(self, bookkeeping: BookkeepingStore, subscription: str):
        """
        :param bookkeeping: Receive counts, dedup claims and acked-message memory.
        :param subscription: Full subscription path; scopes every key.
        """
        self._bookkeeping = bookkeeping
        self._subscription = subscription

    def admit(self, message_id: str, dedup_id: str | None) -> int | None:
        """Count this delivery and return its ``receive_count``, or None if it must not run.

        None means the message already ran (it was acknowledged within the dedup window) or another
        message with the same ``dedup_id`` claimed it first: the caller acknowledges it without
        running it. Bookkeeping errors propagate, so the delivery is retried later.
        """
        key = self._key(message_id)
        if self._bookkeeping.was_acked(key):
            _log.info(f"Dropped redelivery of acknowledged message {message_id} on {self._subscription}")
            return None
        # Scoped to the subscription, like Kafka scopes it to the topic: a reply carries its
        # request's dedup id, so a global key would drop every reply.
        if dedup_id and not self._bookkeeping.claim_dedup(f"{self._subscription}:{dedup_id}", owner=message_id):
            _log.info(f"Dropped duplicate message {message_id} (dedup_id={dedup_id})")
            return None
        return self._bookkeeping.incr_attempts(key)

    def remember_ack(self, message_id: str) -> None:
        """Remember that the message was acknowledged. Logs failures instead of raising."""
        try:
            self._bookkeeping.mark_acked(self._key(message_id))
        except Exception:
            _log.exception(f"Failed to remember the acknowledgement of message {message_id} on {self._subscription}")

    def forget_attempts(self, message_id: str) -> None:
        """Drop the message's attempt count (it reached a terminal state). Logs failures instead of raising."""
        try:
            self._bookkeeping.clear_attempts(self._key(message_id))
        except Exception:
            _log.exception(f"Failed to clear the attempt count of message {message_id} on {self._subscription}")

    def _key(self, message_id: str) -> str:
        return f"{self._subscription}:{message_id}"


class _DeadLetterCopier:
    """Copies a message's original data and attributes to a dead-letter topic, with the reason."""

    def __init__(self, publisher: Any, dlq_topic: str, request_timeout: float):
        """
        :param publisher: The transport's shared ``PublisherClient``.
        :param dlq_topic: Full path of the dead-letter topic.
        :param request_timeout: How long to wait for Pub/Sub to confirm the copy.
        """
        self._publisher = publisher
        self.dlq_topic = dlq_topic
        self._request_timeout = request_timeout

    def copy(self, message_id: str, data: bytes, attributes: Mapping[str, str], reason: str) -> bool:
        """Publish the copy, with ``reason`` in the error attribute. Logs and returns False on failure."""
        try:
            self._publisher.publish(self.dlq_topic, data, **{**attributes, ERROR_ATTRIBUTE: reason}).result(timeout=self._request_timeout)
            return True
        except Exception:
            _log.exception(
                f"Failed to copy message {message_id} to dead-letter topic {self.dlq_topic}: the original is acknowledged, "
                "so this copy is lost. Check that the dead-letter topic exists and this service may publish to it."
            )
            return False


class PubSubTransportConsumer(TransportConsumer):
    """Consumer over one Pub/Sub subscription. One instance (and one ``SubscriberClient``) per
    consumer thread, as the transport contract requires.

    State is owned by the consumer thread, except the lease registry inside :class:`_LeaseKeeper`.
    """

    def __init__(
        self,
        subscriber: Any,
        subscription: str,
        dlq_topic: str,
        publisher: Any,
        bookkeeping: BookkeepingStore,
        ack_wait: float,
        request_timeout: float,
        lease_keeper: _LeaseKeeper | None = None,
    ):
        """
        :param subscriber: A ``SubscriberClient`` owned by this consumer (closed by :meth:`close`).
        :param subscription: Full subscription path.
        :param dlq_topic: Full path of the dead-letter topic for this subscription's queue.
        :param publisher: The transport's shared ``PublisherClient``.
        :param bookkeeping: Receive counts, dedup claims and acked-message memory.
        :param ack_wait: Seconds a fetched message stays leased.
        :param request_timeout: Timeout of each Pub/Sub call.
        :param lease_keeper: Override for tests; built and started here when omitted.
        """
        self._subscriber = subscriber
        self._subscription = subscription
        self._ledger = _DeliveryLedger(bookkeeping, subscription)
        self._dead_letters = _DeadLetterCopier(publisher, dlq_topic, request_timeout)
        self._ack_wait = ack_wait
        self._request_timeout = request_timeout
        # Pulled but not yet served, per ordering key; keyless messages sit under "".
        self._held: dict[str, deque[_Received]] = {}
        # The one served, unsettled message per non-empty ordering key.
        self._in_flight: dict[str, _Received] = {}
        self._leases = lease_keeper or _LeaseKeeper(subscriber, subscription, ack_wait, request_timeout)
        if lease_keeper is None:
            self._leases.start()

    def fetch(self, batch_size: int, wait_seconds: float) -> list[QueueMessage]:
        batch = self._serve(batch_size)
        if batch:
            return batch

        received = self._pull(batch_size, wait_seconds)
        if received:
            self._lease_new(received)
            self._hold(received)
        return self._serve(batch_size)

    def ack(self, message: QueueMessage) -> None:
        """Acknowledge a processed message. Never raises: processing already succeeded."""
        item: _Received = message.native
        try:
            self._acknowledge(item)
        finally:
            if item.ordering_key and self._in_flight.get(item.ordering_key) is item:
                del self._in_flight[item.ordering_key]
            self._ledger.forget_attempts(item.message_id)

    def nack(self, message: QueueMessage) -> None:
        """Return the message, and every held message of its ordering key, for redelivery.

        The held messages go back too: serving them after a nacked predecessor would break the
        key's order, and Pub/Sub redelivers the whole key in order anyway. Local state is cleared
        before the call, so it is clean whatever the call does; a failed call propagates to the
        consumer loop, and the messages return when their deadlines pass.
        """
        item: _Received = message.native
        released = [item]
        if item.ordering_key:
            if self._in_flight.get(item.ordering_key) is item:
                del self._in_flight[item.ordering_key]
            released.extend(self._held.pop(item.ordering_key, ()))

        ack_ids = [released_item.ack_id for released_item in released]
        self._leases.remove(ack_ids)
        # A deadline of 0 releases the messages now; the subscription's retry policy sets the delay.
        self._modify_ack_deadline(ack_ids, 0)

    def dead_letter(self, message: QueueMessage) -> None:
        """Copy a permanently failed message to the dead-letter topic, then acknowledge it.

        The original is acknowledged either way (Kafka parity): the permanent-failure hook has
        already answered the caller, and a message left unacknowledged would loop forever.
        """
        item: _Received = message.native
        reason = f"exceeded max_receive_count after {message.receive_count} deliveries"
        if self._dead_letters.copy(item.message_id, item.data, item.attributes, reason):
            _log.warning(f"Routed message {item.message_id} to dead-letter topic {self._dead_letters.dlq_topic}")
        self.ack(message)

    def close(self) -> None:
        """Stop renewing leases, release every unsettled message, and close the client."""
        self._leases.stop()
        pending = [item.ack_id for queue in self._held.values() for item in queue]
        pending += [item.ack_id for item in self._in_flight.values()]
        self._held.clear()
        self._in_flight.clear()
        if pending:
            try:
                # Released now, another consumer gets them at once instead of after the lease.
                self._modify_ack_deadline(pending, 0)
            except Exception:
                _log.debug(f"Failed to release {len(pending)} message(s) on {self._subscription}", exc_info=True)
        try:
            self._subscriber.close()
        except Exception:
            _log.debug(f"Failed to close the subscriber for {self._subscription}", exc_info=True)

    # -- internals ---------------------------------------------------------------------------

    def _pull(self, batch_size: int, wait_seconds: float) -> list[_Received]:
        """One unary pull. An empty wait ends in ``DeadlineExceeded``, which is not an error."""
        try:
            response = self._subscriber.pull(
                request={"subscription": self._subscription, "max_messages": max(batch_size, 1)},
                timeout=max(wait_seconds, MIN_PULL_TIMEOUT_SECONDS),
                retry=None,
            )
        except google_exceptions.DeadlineExceeded:
            return []
        return [self._to_received(received_message) for received_message in response.received_messages]

    @staticmethod
    def _to_received(received_message: Any) -> _Received:
        message = received_message.message
        attributes = dict(message.attributes)
        try:
            envelope = PubSubEnvelopeCodec.decode(message.data, attributes, message.ordering_key, message.message_id)
        except ValueError as e:
            _log.debug(f"Message {message.message_id} is not an Agent Kernel envelope: {e}")
            envelope = None
        return _Received(
            ack_id=received_message.ack_id,
            message_id=message.message_id,
            ordering_key=message.ordering_key,
            data=bytes(message.data),
            attributes=attributes,
            envelope=envelope,
        )

    def _lease_new(self, received: list[_Received]) -> None:
        """Set the first deadline now, so ``ack_wait`` holds even below the subscription's deadline."""
        ack_ids = [item.ack_id for item in received]
        self._leases.add(ack_ids)
        try:
            self._modify_ack_deadline(ack_ids, _LeaseKeeper.deadline_for(self._ack_wait))
        except Exception:
            _log.warning(
                f"Failed to set the first lease of {len(ack_ids)} message(s) on {self._subscription}; the lease keeper retries", exc_info=True
            )

    def _hold(self, received: list[_Received]) -> None:
        """Queue pulled messages per ordering key, superseding stale state for the keys they carry.

        Pub/Sub sends a key's messages only once the previous batch for that key was acked or
        lapsed, so anything this consumer still holds or has in flight for such a key is stale:
        it is dropped without a server call (its lease has already lapsed or been settled).
        """
        for key in {item.ordering_key for item in received if item.ordering_key}:
            stale = list(self._held.pop(key, ()))
            if key in self._in_flight:
                stale.append(self._in_flight.pop(key))
            if stale:
                self._leases.remove([item.ack_id for item in stale])
                _log.info(f"Ordering key {key} was redelivered on {self._subscription}: dropped {len(stale)} stale message(s)")
        for item in received:
            self._held.setdefault(item.ordering_key, deque()).append(item)

    def _serve(self, batch_size: int) -> list[QueueMessage]:
        """Hand out up to ``batch_size`` held messages: one per ordering key, any number keyless."""
        batch: list[QueueMessage] = []
        for key in list(self._held):
            if len(batch) >= batch_size:
                break
            queue = self._held[key]
            while queue and len(batch) < batch_size and not (key and key in self._in_flight):
                item = queue.popleft()
                try:
                    message = self._admit(item)
                except Exception:
                    queue.appendleft(item)  # bookkeeping is unreachable: keep the message for the next fetch
                    raise
                if message is not None:
                    batch.append(message)
            if not queue:
                del self._held[key]
        return batch

    def _admit(self, item: _Received) -> QueueMessage | None:
        """Turn a held message into a served one, or settle it without running. None when settled."""
        if item.envelope is None:
            self._quarantine(item)
            return None

        receive_count = self._ledger.admit(item.message_id, item.envelope.dedup_id)
        if receive_count is None:
            self._acknowledge(item)  # already ran, or a duplicate
            return None
        if item.ordering_key:
            self._in_flight[item.ordering_key] = item
        return item.envelope.model_copy(update={"receive_count": receive_count, "native": item})

    def _acknowledge(self, item: _Received) -> None:
        """Remember the ack, then send it. Logs failures instead of raising.

        The memory is written first: if the ack is lost, the redelivery is recognised and dropped.
        """
        self._ledger.remember_ack(item.message_id)
        try:
            self._subscriber.acknowledge(request={"subscription": self._subscription, "ack_ids": [item.ack_id]}, timeout=self._request_timeout)
        except Exception:
            _log.exception(
                f"Failed to acknowledge message {item.message_id} on {self._subscription}: a redelivery will be dropped as already acknowledged"
            )
        finally:
            self._leases.remove([item.ack_id])

    def _quarantine(self, item: _Received) -> None:
        """Copy a message that is not an Agent Kernel envelope to the dead-letter topic and ack it."""
        _log.error(f"Message {item.message_id} on {self._subscription} is not an Agent Kernel envelope; copying it to {self._dead_letters.dlq_topic}")
        self._dead_letters.copy(item.message_id, item.data, item.attributes, QUARANTINE_REASON)
        self._acknowledge(item)

    def _modify_ack_deadline(self, ack_ids: list[str], seconds: int) -> None:
        self._subscriber.modify_ack_deadline(
            request={"subscription": self._subscription, "ack_ids": ack_ids, "ack_deadline_seconds": seconds},
            timeout=self._request_timeout,
        )


class PubSubPushReceiver:
    """Runs one Pub/Sub push delivery with the consumer loop's semantics (spec #886 §1.9).

    With a push subscription, Pub/Sub sends each message to an HTTP endpoint and reads the response
    status as the acknowledgement, so there is nothing to fetch, lease or hold: Pub/Sub itself keeps
    one message outstanding per ordering key. What carries over from the pull consumer is the
    delivery bookkeeping (:class:`_DeliveryLedger`) and the permanent-failure path, so a request
    runs the same whether it was pulled or pushed.

    Pub/Sub waits at most the subscription's ack deadline (600 seconds at most) for the response.
    A run that takes longer is redelivered while it is still going, and so runs a second time: the
    accepted cost of push (spec #886 §7).
    """

    ACK = 204
    NACK = 500
    BAD_REQUEST = 400

    def __init__(
        self,
        process: Callable[[QueueMessage], None],
        on_permanent_failure: Callable[[QueueMessage], None],
        max_receive_count: int,
        bookkeeping: BookkeepingStore,
        dead_letters: _DeadLetterCopier,
    ):
        """
        :param process: Runs one message; raising requests redelivery (the ``ConsumerLoop`` contract).
        :param on_permanent_failure: Runs when a message exceeds ``max_receive_count``.
        :param max_receive_count: Deliveries after which a message is permanently failed.
        :param bookkeeping: Receive counts, dedup claims and acked-message memory.
        :param dead_letters: Copies permanently failed and foreign messages to the dead-letter topic.
        """
        self._process = process
        self._on_permanent_failure = on_permanent_failure
        self._max_receive_count = max_receive_count
        self._bookkeeping = bookkeeping
        self._dead_letters = dead_letters

    def handle(self, body: Mapping[str, Any]) -> int:
        """Handle one push request body and return the HTTP status to answer with.

        :param body: The push request's JSON body (``message`` and ``subscription``).
        :return: ``ACK`` to acknowledge, ``NACK`` for redelivery, ``BAD_REQUEST`` for a body that is
            not a Pub/Sub push delivery.
        """
        delivery = self._parse(body)
        if delivery is None:
            return self.BAD_REQUEST
        subscription, message_id, ordering_key, data, attributes = delivery
        ledger = _DeliveryLedger(self._bookkeeping, subscription)

        try:
            envelope = PubSubEnvelopeCodec.decode(data, attributes, ordering_key, message_id)
        except ValueError:
            _log.error(f"Message {message_id} on {subscription} is not an Agent Kernel envelope; copying it to {self._dead_letters.dlq_topic}")
            self._dead_letters.copy(message_id, data, attributes, QUARANTINE_REASON)
            ledger.remember_ack(message_id)
            return self.ACK

        receive_count = ledger.admit(message_id, envelope.dedup_id)
        if receive_count is None:
            ledger.remember_ack(message_id)
            return self.ACK
        message = envelope.model_copy(update={"receive_count": receive_count})

        try:
            if receive_count > self._max_receive_count:
                _log.warning(f"Message {message_id} exceeded max_receive_count ({receive_count} > {self._max_receive_count})")
                self._on_permanent_failure(message)
                reason = f"exceeded max_receive_count after {receive_count} deliveries"
                if self._dead_letters.copy(message_id, data, attributes, reason):
                    _log.warning(f"Routed message {message_id} to dead-letter topic {self._dead_letters.dlq_topic}")
            else:
                self._process(message)
        except Exception:
            _log.exception(f"Failed to process message {message_id} on {subscription}: answering with a nack for redelivery")
            return self.NACK

        ledger.remember_ack(message_id)
        ledger.forget_attempts(message_id)
        return self.ACK

    @staticmethod
    def _parse(body: Mapping[str, Any]) -> tuple[str, str, str, bytes, dict[str, str]] | None:
        """The delivery's subscription, message id, ordering key, data and attributes, or None if malformed."""
        message = body.get("message") if isinstance(body, Mapping) else None
        subscription = body.get("subscription") if isinstance(body, Mapping) else None
        if not isinstance(message, Mapping) or not isinstance(subscription, str) or not subscription:
            _log.warning("Rejected a push request that is not a Pub/Sub delivery (no message or subscription)")
            return None
        message_id = message.get("messageId") or message.get("message_id")
        attributes = message.get("attributes") or {}
        if not isinstance(message_id, str) or not message_id or not isinstance(attributes, Mapping):
            _log.warning(f"Rejected a push request on {subscription} without a message id or with malformed attributes")
            return None
        try:
            data = base64.b64decode(message.get("data") or "", validate=True)
        except (binascii.Error, TypeError, ValueError):
            _log.warning(f"Rejected push delivery {message_id} on {subscription}: its data is not base64")
            return None
        ordering_key = message.get("orderingKey") or message.get("ordering_key") or ""
        return subscription, message_id, str(ordering_key), data, {str(k): str(v) for k, v in attributes.items()}


class PubSubTransport(QueueTransport):
    """Google Cloud Pub/Sub queue transport: the pipeline's broker on GCP.

    The publisher is process-wide (one ``PublisherClient``, which owns its own threads and
    channel); consumers own their ``SubscriberClient`` per the contract. Topics and subscriptions
    are created (``auto_provision``) or verified once per process, mirroring the NATS transport.
    """

    _publisher: Any = None
    _publisher_lock = threading.Lock()
    _default_project: str | None = None
    _default_project_lock = threading.Lock()
    # Objects whose provisioning has completed, plus one lock per object so concurrent callers
    # queue up instead of racing (see _ensure_once).
    _provisioned: set = set()
    _provision_locks: dict[str, threading.Lock] = {}
    _provisioned_lock = threading.Lock()

    def __init__(
        self,
        project_id: str | None,
        input_topic: str,
        input_subscription: str,
        output_topic: str,
        output_subscription: str,
        dlq_suffix: str = "-dlq",
        ack_wait: float = 300.0,
        request_timeout: float = 10.0,
        auto_provision: bool = False,
        max_delivery_attempts: dict[QueueName, int] | None = None,
        bookkeeping: BookkeepingStore | None = None,
        config_path: str = "execution.queues",
        feature: str = "execution.queues.type: pubsub",
    ):
        """
        :param project_id: Project owning the topics and subscriptions; None uses the ADC project.
        :param input_topic: Short name of the topic carrying chat requests.
        :param input_subscription: Short name of the subscription the agent runner pulls.
        :param output_topic: Short name of the topic carrying replies.
        :param output_subscription: Short name of the subscription the response handler pulls.
        :param dlq_suffix: Appended to a topic name for its dead-letter topic.
        :param ack_wait: Seconds a fetched message stays leased.
        :param request_timeout: Timeout of each Pub/Sub call.
        :param auto_provision: Create missing topics and subscriptions (emulator and dev only).
        :param max_delivery_attempts: Server dead-letter backstop per queue, used when provisioning.
        :param bookkeeping: Override for tests; built from configuration on first consumer otherwise.
        :param config_path: The queues block this transport came from, named in errors.
        :param feature: Config path quoted in a missing-extra error from the bookkeeping factory.
        """
        self._project_id = project_id
        self._topics = {QueueName.INPUT: input_topic, QueueName.OUTPUT: output_topic}
        self._subscriptions = {QueueName.INPUT: input_subscription, QueueName.OUTPUT: output_subscription}
        self._dlq_suffix = dlq_suffix
        self._ack_wait = ack_wait
        self._request_timeout = request_timeout
        self._auto_provision = auto_provision
        self._max_delivery_attempts = max_delivery_attempts or {}
        self._bookkeeping = bookkeeping
        self._bookkeeping_lock = threading.Lock()
        self._config_path = config_path
        self._feature = feature

    # -- send side ---------------------------------------------------------------------------

    def send(self, queue: QueueName, message: QueueMessage) -> Any:
        """Publish the envelope and wait for Pub/Sub to confirm it.

        A failure raises rather than dropping the message silently. With ordering enabled, the
        client pauses an ordering key after a failed publish and refuses every later publish for it,
        so the key is resumed before the error propagates.
        """
        self._ensure_topic(queue)
        topic = self._topic_path(self._topics[queue])
        data, attributes = PubSubEnvelopeCodec.encode(message)
        ordering_key = message.group_id or ""
        publisher = self._get_publisher()
        try:
            message_id = publisher.publish(topic, data, ordering_key=ordering_key, **attributes).result(timeout=self._request_timeout)
        except Exception:
            if ordering_key:
                try:
                    publisher.resume_publish(topic, ordering_key)
                except Exception:
                    _log.debug(f"Failed to resume ordering key {ordering_key} on {topic}", exc_info=True)
            raise
        return {"MessageId": message_id}

    # -- receive side ------------------------------------------------------------------------

    def create_consumer(self, queue: QueueName) -> PubSubTransportConsumer:
        self._ensure_subscription(queue)
        return PubSubTransportConsumer(
            subscriber=pubsub_v1.SubscriberClient(),
            subscription=self._subscription_path(self._subscriptions[queue]),
            dlq_topic=self._dlq_topic_path(queue),
            publisher=self._get_publisher(),
            bookkeeping=self._get_bookkeeping(),
            ack_wait=self._ack_wait,
            request_timeout=self._request_timeout,
        )

    def create_push_receiver(
        self,
        queue: QueueName,
        process: Callable[[QueueMessage], None],
        on_permanent_failure: Callable[[QueueMessage], None],
        max_receive_count: int,
    ) -> PubSubPushReceiver:
        """A receiver for ``queue``'s push deliveries, the push counterpart of :meth:`create_consumer`.

        Nothing is verified or provisioned: the push subscription calls this service, so Terraform
        (or whoever created it) already wired the queue to it.
        """
        return PubSubPushReceiver(
            process=process,
            on_permanent_failure=on_permanent_failure,
            max_receive_count=max_receive_count,
            bookkeeping=self._get_bookkeeping(),
            dead_letters=_DeadLetterCopier(self._get_publisher(), self._dlq_topic_path(queue), self._request_timeout),
        )

    # -- provisioning ------------------------------------------------------------------------

    def _ensure_topic(self, queue: QueueName) -> None:
        """Make sure a send to ``queue`` is delivered, once per process.

        Verifying needs only the topic. Provisioning creates the whole queue (subscription and
        dead-letter topic included), because Pub/Sub drops a message published to a topic that has
        no subscription yet: a request sent before the first consumer started would vanish.
        """
        if self._auto_provision:
            self._ensure_subscription(queue)
        else:
            topic = self._topic_path(self._topics[queue])
            self._ensure_once(f"topic:{topic}", lambda: self._verify_topic(topic))

    def _ensure_subscription(self, queue: QueueName) -> None:
        """Create or verify the subscription and its dead-letter topic, once per process.

        The receive side never publishes to the queue topic, so it does not verify it.
        """
        subscription = self._subscription_path(self._subscriptions[queue])
        if self._auto_provision:
            self._ensure_once(f"subscription:{subscription}", lambda: self._provision_subscription(queue))
        else:
            self._ensure_once(f"subscription:{subscription}", lambda: self._verify_subscription(queue))

    def _ensure_once(self, cache_key: str, work: Callable[[], None]) -> None:
        """Run ``work`` once per process per object, recording it only after it succeeded."""
        cls = type(self)
        with cls._provisioned_lock:
            if cache_key in cls._provisioned:
                return
            lock = cls._provision_locks.setdefault(cache_key, threading.Lock())
        with lock:
            if cache_key in cls._provisioned:
                return  # another thread finished the work while this one waited for the lock
            work()
            with cls._provisioned_lock:
                cls._provisioned.add(cache_key)

    def _verify_topic(self, topic: str) -> None:
        try:
            self._get_publisher().get_topic(request={"topic": topic}, timeout=self._request_timeout)
        except google_exceptions.NotFound as e:
            raise AKConfigError(
                f"Pub/Sub topic '{topic}' does not exist. Create it (the ak-gcp pubsub Terraform module) or set "
                f"{self._config_path}.pubsub.auto_provision: true to have Agent Kernel create it at startup."
            ) from e

    def _verify_subscription(self, queue: QueueName) -> None:
        subscription = self._subscription_path(self._subscriptions[queue])
        with pubsub_v1.SubscriberClient() as admin:
            try:
                existing = admin.get_subscription(request={"subscription": subscription}, timeout=self._request_timeout)
            except google_exceptions.NotFound as e:
                raise AKConfigError(
                    f"Pub/Sub subscription '{subscription}' does not exist. Create it (the ak-gcp pubsub Terraform module) or "
                    f"set {self._config_path}.pubsub.auto_provision: true to have Agent Kernel create it at startup."
                ) from e
        if not existing.enable_message_ordering:
            raise AKConfigError(
                f"Pub/Sub subscription '{subscription}' does not have message ordering enabled, so a session's turns could run "
                "concurrently or out of order. Ordering cannot be changed on an existing subscription: recreate it with "
                "enable_message_ordering = true."
            )
        self._verify_topic(self._dlq_topic_path(queue))

    def _provision_subscription(self, queue: QueueName) -> None:
        topic = self._topic_path(self._topics[queue])
        dlq_topic = self._dlq_topic_path(queue)
        subscription = self._subscription_path(self._subscriptions[queue])
        self._create_topic(topic)
        self._create_topic(dlq_topic)
        with pubsub_v1.SubscriberClient() as admin:
            self._create_subscription(
                admin,
                {
                    "name": subscription,
                    "topic": topic,
                    "enable_message_ordering": True,
                    "ack_deadline_seconds": SUBSCRIPTION_ACK_DEADLINE_SECONDS,
                    "dead_letter_policy": {
                        "dead_letter_topic": dlq_topic,
                        "max_delivery_attempts": self._max_delivery_attempts.get(queue, DEFAULT_MAX_DELIVERY_ATTEMPTS),
                    },
                },
            )
            # Pub/Sub drops messages published to a topic with no subscription, so the dead-letter
            # topic gets one: it is where the copies are inspected.
            self._create_subscription(admin, {"name": self._subscription_path(self._short_name(dlq_topic)), "topic": dlq_topic})
        _log.info(f"Provisioned Pub/Sub subscription {subscription} on {topic} (dead-letter topic {dlq_topic})")

    def _create_topic(self, topic: str) -> None:
        try:
            self._get_publisher().create_topic(request={"name": topic}, timeout=self._request_timeout)
            _log.info(f"Created Pub/Sub topic {topic}")
        except google_exceptions.AlreadyExists:
            pass

    def _create_subscription(self, admin: Any, request: dict[str, Any]) -> None:
        try:
            admin.create_subscription(request=request, timeout=self._request_timeout)
        except google_exceptions.AlreadyExists:
            pass

    # -- clients, paths, bookkeeping ---------------------------------------------------------

    @classmethod
    def _get_publisher(cls) -> Any:
        with cls._publisher_lock:
            if cls._publisher is None:
                cls._publisher = pubsub_v1.PublisherClient(
                    publisher_options=pubsub_v1.types.PublisherOptions(enable_message_ordering=True),
                    # send() waits for every publish, so batching would only add its latency.
                    batch_settings=pubsub_v1.types.BatchSettings(max_messages=1),
                )
            return cls._publisher

    def _get_bookkeeping(self) -> BookkeepingStore:
        """The bookkeeping store, built on first use: the send side never needs one."""
        with self._bookkeeping_lock:
            if self._bookkeeping is None:
                self._bookkeeping = BookkeepingStoreFactory.create(feature=self._feature)
            return self._bookkeeping

    def _project(self) -> str:
        if self._project_id:
            return self._project_id
        cls = type(self)
        with cls._default_project_lock:
            if cls._default_project is None:
                try:
                    _, project = google.auth.default()
                except Exception as e:
                    raise AKConfigError(
                        f"the pubsub transport could not determine a GCP project: set {self._config_path}.pubsub.project_id ({e})"
                    ) from e
                if not project:
                    raise AKConfigError(f"the pubsub transport could not determine a GCP project: set {self._config_path}.pubsub.project_id")
                cls._default_project = project
            return cls._default_project

    def _topic_path(self, name: str) -> str:
        return f"projects/{self._project()}/topics/{name}"

    def _subscription_path(self, name: str) -> str:
        return f"projects/{self._project()}/subscriptions/{name}"

    def _dlq_topic_path(self, queue: QueueName) -> str:
        return self._topic_path(f"{self._topics[queue]}{self._dlq_suffix}")

    @staticmethod
    def _short_name(path: str) -> str:
        return path.rsplit("/", 1)[-1]

    @classmethod
    def reset(cls) -> None:
        """Drop the process-wide publisher, project and provisioning caches. Test isolation only."""
        with cls._publisher_lock:
            cls._publisher = None
        with cls._default_project_lock:
            cls._default_project = None
        with cls._provisioned_lock:
            cls._provisioned.clear()
            cls._provision_locks.clear()
