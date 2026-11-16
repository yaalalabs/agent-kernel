"""Azure Service Bus queue transport (#887).

Two session-enabled queues give the SQS FIFO model on Azure: the session id is the message group,
the queue's duplicate detection drops a repeated ``message_id``, and ``delivery_count`` is the
receive count. Service Bus itself does not keep one message in flight per session (a session
receiver may take the next message before settling the first), so that part is the consumer's:
a session with an unsettled message is never polled.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from azure.identity import DefaultAzureCredential
from azure.servicebus import (
    NEXT_AVAILABLE_SESSION,
    AutoLockRenewer,
    ServiceBusClient,
    ServiceBusMessage,
    ServiceBusReceivedMessage,
    ServiceBusReceiver,
)
from azure.servicebus.exceptions import OperationTimeoutError, SessionLockLostError

from ...core.util.factory import AKConfigError
from ..envelope import QueueMessage, QueueName
from .base import QueueTransport, TransportConsumer

_log = logging.getLogger("ak.pipeline.transport.servicebus")

# Fetch slice: an idle consumer re-attaches one session-accept link per slice.
SERVICEBUS_MAX_WAIT_SECONDS = 20.0
# How long a held session, or another session once the fetch already has a message, is waited on.
SESSION_REUSE_WAIT_SECONDS = 0.5


@dataclass
class _HeldSession:
    """One accepted session: its receiver, when it was accepted, and its unsettled message if any."""

    receiver: ServiceBusReceiver
    accepted_at: float  # time.monotonic(), taken just before the accept
    in_flight: ServiceBusReceivedMessage | None = None


class ServiceBusTransportConsumer(TransportConsumer):
    """Session-locked consumer over one queue. Owns its client: SDK clients are not thread-safe."""

    fetch_wait_slice_seconds = SERVICEBUS_MAX_WAIT_SECONDS

    def __init__(self, client: ServiceBusClient, queue_name: str, ack_wait: float):
        self._client = client
        self._queue_name = queue_name
        self._ack_wait = ack_wait
        self._sessions: dict[str, _HeldSession] = {}
        self._renewer = AutoLockRenewer(max_lock_renewal_duration=ack_wait)

    def fetch(self, batch_size: int, wait_seconds: float) -> list[QueueMessage]:
        deadline = time.monotonic() + wait_seconds
        self._drop_lapsed_sessions()
        messages: list[QueueMessage] = []
        try:
            self._receive_into(messages, batch_size, deadline)
        except Exception:
            if not messages:
                raise
            # Received messages hold their session locks; dropping them would stall them until the lock lapses.
            _log.warning(f"Fetch on {self._queue_name} failed after {len(messages)} message(s); returning them", exc_info=True)
        return messages

    def _receive_into(self, messages: list[QueueMessage], batch_size: int, deadline: float) -> None:
        # Reuse first: back-to-back turns and delta chunks of one session skip a new accept.
        for session_id, held in list(self._sessions.items()):
            remaining = deadline - time.monotonic()
            if len(messages) >= batch_size or remaining <= 0:
                break
            if held.in_flight is not None:
                continue  # one in flight per session: the next message waits for this one's settle
            if time.monotonic() - held.accepted_at >= self._ack_wait:
                self._release(session_id)  # its renewal no longer covers a full ack_wait; re-accept fresh
                continue
            try:
                received = held.receiver.receive_messages(max_message_count=1, max_wait_time=min(SESSION_REUSE_WAIT_SECONDS, remaining))
            except Exception:
                self._release(session_id)
                raise
            if received:
                messages.append(self._hold(session_id, held, received[0]))
            else:
                self._release(session_id)

        while len(messages) < batch_size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # Once the batch has a message, return it promptly rather than wait out the long poll.
            wait = min(SESSION_REUSE_WAIT_SECONDS, remaining) if messages else remaining
            accepted_at = time.monotonic()
            receiver = self._client.get_queue_receiver(self._queue_name, session_id=NEXT_AVAILABLE_SESSION, max_wait_time=wait)
            try:
                received = receiver.receive_messages(max_message_count=1, max_wait_time=wait)
            except OperationTimeoutError:
                receiver.close()
                break  # no session with work became available
            except Exception:
                receiver.close()
                raise
            if not received:
                receiver.close()
                continue
            session_id = receiver.session.session_id
            held = _HeldSession(receiver=receiver, accepted_at=accepted_at)
            self._sessions[session_id] = held
            # One registration per accept. The SDK counts the ceiling from the accept, and a session is
            # reused only while younger than ack_wait, so 2 x ack_wait gives every message a full ack_wait.
            self._renewer.register(receiver, receiver.session, max_lock_renewal_duration=2 * self._ack_wait)
            messages.append(self._hold(session_id, held, received[0]))

    def ack(self, message: QueueMessage) -> None:
        held = self._held(message)
        try:
            held.receiver.complete_message(message.native)
        except Exception:
            self._release(message.group_id)
            raise
        held.in_flight = None  # the session stays held for reuse by the next fetch

    def nack(self, message: QueueMessage) -> None:
        held = self._held(message)
        try:
            held.receiver.abandon_message(message.native)
        finally:
            self._release(message.group_id)  # free the session for any consumer to redeliver

    def dead_letter(self, message: QueueMessage) -> None:
        """Move an exhausted message to the queue's dead-letter sub-queue. Never raises: the queue's
        ``max_delivery_count`` dead-letters it on the next delivery if this fails."""
        try:
            held = self._held(message)
            held.receiver.dead_letter_message(message.native, reason="max_receive_count exceeded")
            held.in_flight = None
            _log.warning(f"Dead-lettered message {message.message_id} on {self._queue_name} after {message.receive_count} deliveries")
        except Exception:
            _log.exception(f"Failed to dead-letter message {message.message_id} on {self._queue_name}")
            self._release(message.group_id)

    def close(self) -> None:
        for session_id in list(self._sessions):
            self._release(session_id)
        self._renewer.close()
        self._client.close()

    def _hold(self, session_id: str, held: _HeldSession, received: ServiceBusReceivedMessage) -> QueueMessage:
        held.in_flight = received
        return self._to_envelope(received, session_id)

    def _held(self, message: QueueMessage) -> _HeldSession:
        held = self._sessions.get(message.group_id)
        if held is None or held.in_flight is not message.native:
            raise SessionLockLostError(message=f"session {message.group_id} is no longer held by this consumer")
        return held

    def _drop_lapsed_sessions(self) -> None:
        now = datetime.now(timezone.utc)
        for session_id, held in list(self._sessions.items()):
            locked_until = held.receiver.session.locked_until_utc
            if locked_until is None or locked_until <= now:
                self._release(session_id)

    def _release(self, session_id: str | None) -> None:
        held = self._sessions.pop(session_id, None)
        if held is None:
            return
        try:
            held.receiver.close()
        except Exception:
            _log.debug(f"Failed to close the receiver for session {session_id} on {self._queue_name}", exc_info=True)

    @staticmethod
    def _to_envelope(received: ServiceBusReceivedMessage, session_id: str) -> QueueMessage:
        def text(value) -> str:
            return value.decode("utf-8") if isinstance(value, bytes) else str(value)

        return QueueMessage(
            body=b"".join(received.body).decode("utf-8"),
            attributes={text(name): text(value) for name, value in (received.application_properties or {}).items()},
            group_id=session_id,
            dedup_id=received.message_id,  # send() stores dedup_id here; the runner derives reply dedup ids from it
            # The SDK hands back the AMQP header count, which counts prior deliveries only.
            receive_count=(received.delivery_count or 0) + 1,
            message_id=str(received.sequence_number),
            native=received,
        )


class ServiceBusTransport(QueueTransport):
    """Azure Service Bus transport: two session-enabled queues, the SQS FIFO model on Azure.

    Queue URLs come from the factory (``execution.queues.input.url`` / ``output.url``) as
    ``https://<namespace>.servicebus.windows.net/<queue>``. Without a connection string the
    transport authenticates with ``DefaultAzureCredential`` (managed identity on Azure).
    """

    def __init__(self, input_url: str, output_url: str, ack_wait: float, connection_string: str | None = None, config_path: str = "execution.queues"):
        input_namespace, input_queue = self.parse_entity_url(input_url, f"{config_path}.input.url")
        output_namespace, output_queue = self.parse_entity_url(output_url, f"{config_path}.output.url")
        if input_namespace != output_namespace:
            raise AKConfigError(
                f"{config_path}.input.url and {config_path}.output.url must be on one Service Bus namespace "
                f"(got {input_namespace} and {output_namespace})"
            )
        self._namespace = input_namespace
        self._queue_names = {QueueName.INPUT: input_queue, QueueName.OUTPUT: output_queue}
        self._ack_wait = ack_wait
        self._connection_string = connection_string
        self._credential = None if connection_string else DefaultAzureCredential()
        self._send_lock = threading.Lock()
        self._send_client: ServiceBusClient | None = None
        self._senders: dict = {}

    def send(self, queue: QueueName, message: QueueMessage) -> None:
        service_bus_message = ServiceBusMessage(
            message.body,
            # The pipeline always sets both; the fallbacks keep an ungrouped message deliverable.
            session_id=message.group_id or str(uuid.uuid4()),
            message_id=message.dedup_id or str(uuid.uuid4()),
            application_properties=dict(message.attributes) or None,
        )
        # Senders are not thread-safe and send may be called from any thread.
        with self._send_lock:
            if self._send_client is None:
                self._send_client = self._new_client()
            sender = self._senders.get(queue)
            if sender is None:
                sender = self._senders[queue] = self._send_client.get_queue_sender(self._queue_names[queue])
            sender.send_messages(service_bus_message)

    def create_consumer(self, queue: QueueName) -> ServiceBusTransportConsumer:
        return ServiceBusTransportConsumer(self._new_client(), self._queue_names[queue], self._ack_wait)

    def _new_client(self) -> ServiceBusClient:
        if self._connection_string:
            return ServiceBusClient.from_connection_string(self._connection_string)
        return ServiceBusClient(self._namespace, self._credential)

    @staticmethod
    def parse_entity_url(url: str, field: str) -> tuple[str, str]:
        """Split ``https://<namespace>/<queue>`` (or ``sb://``) into (namespace host, queue name)."""
        parsed = urlparse(url)
        queue = parsed.path.strip("/")
        if parsed.scheme not in ("https", "sb") or not parsed.hostname or not queue or "/" in queue:
            raise AKConfigError(f"{field} must look like https://<namespace>.servicebus.windows.net/<queue>, got {url!r}")
        return parsed.hostname, queue
