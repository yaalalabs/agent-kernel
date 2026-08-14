import json
import logging
from typing import Optional

from ..core.config import AKConfig
from ..core.model import ExecutionMode, StreamChunk
from ..core.util.factory import AKConfigError
from .consumer import ConsumerLoop
from .envelope import ATTR_ENDPOINT_URL, ATTR_REQUEST_ID, ATTR_STATUS_CODE, QueueMessage, QueueName
from .response_store.base import ResponseStore
from .response_store.handler import ResponseDBHandler
from .response_store.in_memory import InMemoryResponseStore
from .transport.base import QueueTransport, QueueTransportFactory

# ENDPOINT_URL sentinel for in-process delivery (single-process topology).
LOCAL_ENDPOINT = "local"


class ResponseHandler:
    """Pipeline Response Handler (spec #495 §8): consumes the output queue and delivers replies:
    response store in REST modes, local chunk stream for in-process STREAM, WebSocket push for
    multi-process ASYNC/STREAM (ships with the WS delivery iteration).

    The generalization of ECSOutputConsumer; response-store records additionally carry the
    ``status_code`` forwarded by the Agent Runner.
    """

    _log = logging.getLogger("ak.pipeline.response_handler")

    def __init__(self, transport: Optional[QueueTransport] = None, response_store: Optional[ResponseStore] = None):
        self._transport = transport or QueueTransportFactory.create()
        self._response_store = response_store

    def _get_store(self) -> ResponseStore:
        if self._response_store is None:
            response_store_config = AKConfig.get().execution.response_store
            unset = response_store_config is None or response_store_config.type in (None, "in_memory")
            if unset and QueueTransportFactory.resolve_type() == "in_memory":
                self._response_store = InMemoryResponseStore()
            else:
                self._response_store = ResponseDBHandler().get_store()
        return self._response_store

    def process(self, message: QueueMessage) -> None:
        """Deliver one output message according to the execution mode."""
        mode = AKConfig.get().execution.mode
        if mode == ExecutionMode.STREAM:
            endpoint_url = message.attributes.get(ATTR_ENDPOINT_URL)
            if not endpoint_url or endpoint_url == LOCAL_ENDPOINT:
                self._store_chunk(message)
                return
            self._broadcast(message)
            return
        if mode == ExecutionMode.ASYNC:
            self._broadcast(message)
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
                endpoint_url = message.attributes.get(ATTR_ENDPOINT_URL)
                if not endpoint_url or endpoint_url == LOCAL_ENDPOINT:
                    if request_id:
                        error_chunk = StreamChunk(error=error_text, done=True).model_dump(exclude_none=True)
                        if message.group_id:
                            error_chunk["session_id"] = message.group_id
                        store = self._get_store()
                        if isinstance(store, InMemoryResponseStore):
                            store.add_chunk(request_id, error_chunk)
                    return
                self._log.warning("Cannot deliver permanent-failure stream chunk: WebSocket delivery not wired yet")
                return
            if mode == ExecutionMode.ASYNC:
                self._log.warning("Cannot deliver permanent-failure response: WebSocket delivery not wired yet")
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
        if not isinstance(store, InMemoryResponseStore):
            raise AKConfigError("local STREAM delivery requires the in_memory response store")
        store.add_chunk(request_id, json.loads(message.body))

    def _broadcast(self, message: QueueMessage) -> None:
        raise AKConfigError("WebSocket delivery over the pipeline ships in a later #495 iteration")
