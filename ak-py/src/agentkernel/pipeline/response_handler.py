import json
import logging
from typing import Optional

from ..core.config import AKConfig
from ..core.model import ExecutionMode, StreamChunk
from ..core.util.factory import AKConfigError
from .consumer import ConsumerLoop
from .envelope import ATTR_REQUEST_ID, ATTR_STATUS_CODE, ATTR_USER_ID, QueueMessage, QueueName
from .response_store.base import ResponseStore
from .response_store.factory import ResponseStoreFactory
from .transport.base import QueueTransport, QueueTransportFactory
from .ws.base import WebSocketHandlerABC


class ResponseHandler:
    """Pipeline Response Handler (spec #495 §8): consumes the output queue and delivers replies:
    response store in REST modes, local chunk stream for the REST-entered in-process STREAM
    path, WebSocket push for ASYNC/STREAM. Push targets come from the shared connection store
    (wherever the user's sockets are right now), delivered to the owning gateway pod: in-process
    on the ``in_memory`` transport, pod-to-pod HTTP otherwise.

    The generalization of ECSOutputConsumer; response-store records additionally carry the
    ``status_code`` forwarded by the Agent Runner.
    """

    _log = logging.getLogger("ak.pipeline.response_handler")

    def __init__(
        self,
        transport: Optional[QueueTransport] = None,
        response_store: Optional[ResponseStore] = None,
        ws_handler: Optional[WebSocketHandlerABC] = None,
    ):
        self._transport = transport or QueueTransportFactory.create()
        self._response_store = response_store
        self._ws_handler = ws_handler

    def _get_store(self) -> ResponseStore:
        if self._response_store is None:
            self._response_store = ResponseStoreFactory.create()
        return self._response_store

    def _get_ws_handler(self) -> WebSocketHandlerABC:
        if self._ws_handler is None:
            from .ws.push import PodPushWebSocketHandler

            self._ws_handler = PodPushWebSocketHandler()
        return self._ws_handler

    def process(self, message: QueueMessage) -> None:
        """Deliver one output message according to the execution mode."""
        mode = AKConfig.get().execution.mode
        if mode == ExecutionMode.STREAM:
            # No USER_ID attribute means the request entered over REST (spec §2 invariant): its
            # chunks are drained by the Request Handler's SSE generator from the chunk-streaming
            # store. WS-entered requests always carry the authenticated user id.
            if not message.attributes.get(ATTR_USER_ID):
                self._store_chunk(message)
                return
            self._broadcast(message, WebSocketHandlerABC.MessageType.STREAM_CHUNK)
            return
        if mode == ExecutionMode.ASYNC:
            self._broadcast(message, WebSocketHandlerABC.MessageType.CHAT_RESPONSE)
            return
        self._store_response(message)

    def on_permanent_failure(self, message: QueueMessage) -> None:
        """Deliver an error for an output message that exhausted its retries, so the waiting
        client never hangs. Catches own exceptions."""
        max_receive_count = AKConfig.get().execution.queues.output.max_receive_count
        self._log.error(f"Permanent failure for output message {message.message_id} after {max_receive_count} retries")
        try:
            request_id = message.attributes.get(ATTR_REQUEST_ID)
            error_text = f"Failed to process message after {max_receive_count} retries"
            mode = AKConfig.get().execution.mode

            if mode == ExecutionMode.STREAM:
                error_chunk = StreamChunk(error=error_text, done=True).model_dump(exclude_none=True)
                if message.group_id:
                    error_chunk["session_id"] = message.group_id
                if not message.attributes.get(ATTR_USER_ID):
                    if request_id:
                        store = self._get_store()
                        if store.supports_chunk_streaming():
                            store.add_chunk(request_id, error_chunk)
                        else:
                            self._log.warning("Cannot deliver permanent-failure stream chunk: response store does not support chunk streaming")
                    return
                self._broadcast_error(message, error_chunk, WebSocketHandlerABC.MessageType.STREAM_CHUNK)
                return
            if mode == ExecutionMode.ASYNC:
                error_payload = {"error": error_text, "request_id": request_id}
                if message.group_id:
                    error_payload["session_id"] = message.group_id
                self._broadcast_error(message, error_payload, WebSocketHandlerABC.MessageType.SYSTEM_RESPONSE)
                return

            if not request_id:
                self._log.warning("Cannot store permanent-failure response: request_id missing")
                return
            error_payload = {"error": error_text, "request_id": request_id}
            if message.group_id:
                error_payload["session_id"] = message.group_id
            self._get_store().add_message({"session_id": message.group_id, "request_id": request_id, "status_code": 500, "body": error_payload})
            self._log.info(f"Stored permanent-failure error: request_id={request_id}")
        except Exception:
            self._log.exception("Failed to handle permanent-failure output message")

    def start(self, exit_on_shutdown: bool = True) -> None:
        """Run the blocking output-queue consumer loop.

        :param exit_on_shutdown: True for a standalone container main (drain then exit the
            process); IOHandler passes False so its outer runner coordinates the exit after
            every pipeline loop has finished its in-flight work.
        """
        queues = AKConfig.get().execution.queues
        self._transport.check_consumer_capacity(QueueName.OUTPUT, queues.output.no_of_consumers)
        ConsumerLoop(
            process=self.process,
            on_permanent_failure=self.on_permanent_failure,
            max_receive_count=queues.output.max_receive_count,
            num_consumers=queues.output.no_of_consumers,
            batch_size=queues.batch_size or 1,
            consumer_factory=lambda: self._transport.create_consumer(QueueName.OUTPUT),
            thread_name_prefix="response-handler",
            queue=QueueName.OUTPUT,
            logger=self._log,
            exit_on_shutdown=exit_on_shutdown,
        ).run()

    # -- delivery paths ----------------------------------------------------------------------

    def _store_response(self, message: QueueMessage) -> None:
        request_id = message.attributes.get(ATTR_REQUEST_ID)
        if not request_id:
            raise ValueError("request_id is required in queue message attributes")

        body = json.loads(message.body) if message.body else {}
        session_id = body.get("session_id") if isinstance(body, dict) else None
        record = {
            "session_id": session_id or message.group_id,
            "request_id": request_id,
            "status_code": int(message.attributes.get(ATTR_STATUS_CODE, "200")),
            "body": body,
        }
        self._get_store().add_message(record)
        self._log.info(f"[OUTPUT DONE] Stored response: request_id={request_id}, status_code={record['status_code']}")

    def _store_chunk(self, message: QueueMessage) -> None:
        request_id = message.attributes.get(ATTR_REQUEST_ID)
        if not request_id:
            raise ValueError("request_id is required in queue message attributes")
        store = self._get_store()
        if not store.supports_chunk_streaming():
            raise AKConfigError("local STREAM delivery requires a chunk-streaming response store (in_memory, or a BYO store with the capability)")
        store.add_chunk(request_id, json.loads(message.body))

    def _broadcast(self, message: QueueMessage, message_type: WebSocketHandlerABC.MessageType) -> None:
        """Push an output message to the user's current WebSocket connections.

        The connection store resolves where the user's sockets are; this method knows only the
        user. Raising on a missing attribute or a failed delivery is deliberate: the
        ConsumerLoop retries the message up to ``max_receive_count`` and then hands it to
        ``on_permanent_failure``, so a briefly unreachable gateway gets its retries and a gone
        client is dropped after a bounded number of attempts.
        """
        user_id = message.attributes.get(ATTR_USER_ID)
        if not user_id:
            raise ValueError("user_id is required in queue message attributes for WebSocket delivery")

        body = json.loads(message.body) if message.body else {}
        if not isinstance(body, dict):
            body = {"response": body}

        self._get_ws_handler().broadcast(message=body, user_id=user_id, message_type=message_type)
        self._log.info(f"[OUTPUT DONE] Broadcasted {message_type.value} via WebSocket: user_id={user_id}")

    def _broadcast_error(self, message: QueueMessage, error_message: dict, message_type: WebSocketHandlerABC.MessageType) -> None:
        """Best-effort WebSocket delivery of a permanent-failure error (never hang the client silently)."""
        user_id = message.attributes.get(ATTR_USER_ID)
        if not user_id:
            self._log.warning(f"Cannot broadcast permanent-failure {message_type.value}: user_id missing")
            return
        self._get_ws_handler().broadcast(message=error_message, user_id=user_id, message_type=message_type)
        self._log.info(f"Broadcasted permanent-failure {message_type.value} via WebSocket: user_id={user_id}")
