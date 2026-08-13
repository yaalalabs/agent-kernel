import json
import logging
from typing import Optional

from ..core.chat_service import ChatService
from ..core.config import AKConfig
from ..core.model import BaseRunRequest, ExecutionMode, StreamChunk
from ..core.util.factory import AKConfigError
from .consumer import ConsumerLoop
from .envelope import ATTR_ENDPOINT_URL, ATTR_REQUEST_ID, ATTR_STATUS_CODE, ATTR_USER_ID, QueueMessage, QueueName
from .transport.base import QueueTransport, QueueTransportFactory

# Attributes forwarded from an input message to its output message(s).
_FORWARDED_ATTRIBUTES = (ATTR_REQUEST_ID, ATTR_USER_ID, ATTR_ENDPOINT_URL)


class AgentRunner:
    """Pipeline Agent Runner (spec #495 §8): consumes the input queue, executes via the
    ChatService execution layer, and forwards the reply to the output queue.

    The generalization of ECSAgentRunner: transport-agnostic and instance-based. The
    ``run()`` classmethod is the two-process container entry point; ``start()`` runs the
    blocking consumer loop on an already-constructed instance.
    """

    _log = logging.getLogger("ak.pipeline.agent_runner")

    def __init__(self, transport: Optional[QueueTransport] = None, chat_service: Optional[ChatService] = None):
        self._transport = transport or QueueTransportFactory.create()
        self._chat_service = chat_service or ChatService()

    def process(self, message: QueueMessage) -> None:
        """Handle one input message: run the agent and forward the reply (with its status)."""
        body = BaseRunRequest.model_validate(json.loads(message.body))
        request_id = self._require_request_id(message)

        self._log.info(f"[AGENT START] request_id={request_id}, session_id={body.session_id}, agent={body.agent}")

        # ChatService(rest_api_mode=False) returns (status_code, response_dict); unlike ECS,
        # the status travels to the output message as the STATUS_CODE attribute (spec §12.6).
        status_code, agent_response = self._chat_service.process_chat_request(req=body)
        self._send_to_output(message, agent_response, status_code)

        self._log.info(f"[AGENT DONE] request_id={request_id}, status_code={status_code}")

    def on_permanent_failure(self, message: QueueMessage) -> None:
        """Surface an input message that exhausted its retries as an error reply. Catches own exceptions."""
        self._log.error(f"Permanent failure for message {message.message_id}")
        try:
            max_receive_count = AKConfig.get().execution.queues.input.max_receive_count
            error_body = {"error": f"Failed to process message after {max_receive_count} retries"}
            self._send_to_output(message, error_body, 500)
        except Exception:
            self._log.exception("Failed to send permanent-failure error to output queue")

    def start(self, exit_on_shutdown: bool = True) -> None:
        """Run the blocking input-queue consumer loop (the container main loop).

        :param exit_on_shutdown: True for a standalone container main (drain then exit the
            process); IOHandler passes False so its outer runner coordinates the exit after
            every pipeline loop has finished its in-flight work.
        """
        queues = AKConfig.get().execution.queues
        ConsumerLoop(
            process=self.process,
            on_permanent_failure=self.on_permanent_failure,
            max_receive_count=queues.input.max_receive_count,
            num_consumers=queues.input.no_of_consumers,
            batch_size=queues.batch_size or 1,
            consumer_factory=lambda: self._transport.create_consumer(QueueName.INPUT),
            thread_name_prefix="agent-runner",
            queue=QueueName.INPUT,
            logger=self._log,
            exit_on_shutdown=exit_on_shutdown,
        ).run()

    @classmethod
    def run(cls) -> None:
        """Two-process container entry point. Dispatches to StreamAgentRunner in STREAM mode."""
        if QueueTransportFactory.resolve_type() == "in_memory":
            raise AKConfigError("the in_memory transport runs in-process: start IOHandler (single-process topology) instead of AgentRunner")
        # cls check avoids redirect loops when StreamAgentRunner.run() is reached via inheritance.
        if cls is AgentRunner and AKConfig.get().execution.mode == ExecutionMode.STREAM:
            return StreamAgentRunner.run()
        cls().start()

    # -- shared plumbing --------------------------------------------------------------------

    @staticmethod
    def _require_request_id(message: QueueMessage) -> str:
        request_id = message.attributes.get(ATTR_REQUEST_ID)
        if not request_id:
            raise ValueError("request_id is required in queue message attributes")
        return request_id

    def _send_to_output(self, source: QueueMessage, response_body, status_code: Optional[int] = None, dedup_suffix: Optional[str] = None) -> None:
        attributes = {key: value for key, value in source.attributes.items() if key in _FORWARDED_ATTRIBUTES}
        if status_code is not None:
            attributes[ATTR_STATUS_CODE] = str(status_code)

        dedup_id = source.dedup_id
        if dedup_id and dedup_suffix:
            dedup_id = f"{dedup_id}-{dedup_suffix}"

        group_id = source.group_id
        if group_id is None and isinstance(response_body, dict):
            group_id = response_body.get("session_id")

        self._transport.send(
            QueueName.OUTPUT,
            QueueMessage(body=json.dumps(response_body), attributes=attributes, group_id=group_id, dedup_id=dedup_id),
        )


class StreamAgentRunner(AgentRunner):
    """STREAM-mode sibling: fans out each streamed chunk as its own output message (spec #495 §8).

    ENDPOINT_URL is required on broker transports (the reply is pushed over a WebSocket); the
    in_memory transport delivers chunks to the local response store instead, so no endpoint is
    needed (relaxation of the ECS requirement).
    """

    _log = logging.getLogger("ak.pipeline.stream_agent_runner")

    def process(self, message: QueueMessage) -> None:
        body = BaseRunRequest.model_validate(json.loads(message.body))
        request_id = self._require_request_id(message)
        if not message.attributes.get(ATTR_ENDPOINT_URL) and QueueTransportFactory.resolve_type() != "in_memory":
            raise ValueError("endpoint_url is required in queue message attributes for STREAM mode")

        self._log.info(f"[STREAM AGENT START] request_id={request_id} (receive_count={message.receive_count})")

        chunk_count = 0
        for raw_chunk in self._chat_service.process_stream_chat_sync(req=body):
            # Retry attempts get distinct chunk dedup ids so a redelivery's chunks never collide.
            self._send_to_output(message, json.loads(raw_chunk), status_code=None, dedup_suffix=f"{message.receive_count}-{chunk_count}")
            chunk_count += 1

        self._log.info(f"[STREAM AGENT DONE] request_id={request_id}, chunks={chunk_count}")

    def on_permanent_failure(self, message: QueueMessage) -> None:
        self._log.error(f"Permanent failure for message {message.message_id}")
        try:
            max_receive_count = AKConfig.get().execution.queues.input.max_receive_count
            error_chunk = StreamChunk(error=f"Failed to process message after {max_receive_count} retries", done=True).model_dump(exclude_none=True)
            if message.group_id:
                error_chunk["session_id"] = message.group_id
            self._send_to_output(message, error_chunk, status_code=None, dedup_suffix=f"{message.receive_count}-error")
        except Exception:
            self._log.exception("Failed to send permanent-failure stream chunk to output queue")
