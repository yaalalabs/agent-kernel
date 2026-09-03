import json
import logging
from typing import Optional

from ..core.chat_service import ChatService
from ..core.config import AKConfig
from ..core.model import BaseRunRequest, ExecutionMode, StreamChunk
from ..core.util.factory import AKConfigError
from .consumer import ConsumerLoop
from .envelope import (
    ATTR_AGUI,
    ATTR_ENDPOINT_URL,
    ATTR_INTEGRATION,
    ATTR_REQUEST_ID,
    ATTR_STATUS_CODE,
    ATTR_THREAD,
    ATTR_USER_ID,
    REPLY_CONTEXT_PREFIX,
    QueueMessage,
    QueueName,
)
from .thread_runner import ThreadRunner
from .transport.base import QueueTransport, QueueTransportFactory

# Attributes forwarded from an input message to its output message(s). ENDPOINT_URL is part of
# the SQS/ECS wire format only (the pipeline neither stamps nor reads it, spec #495 §2): it is
# forwarded so ECS-entered messages keep their return address through a pipeline runner.
_FORWARDED_ATTRIBUTES = (ATTR_REQUEST_ID, ATTR_USER_ID, ATTR_ENDPOINT_URL, ATTR_INTEGRATION, ATTR_AGUI)


def _is_forwarded(key: str) -> bool:
    """Whether an input attribute travels on to the output message."""
    return key in _FORWARDED_ATTRIBUTES or key.startswith(REPLY_CONTEXT_PREFIX)


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
        """Handle one input message: run the agent and forward the reply (with its status).

        A message carrying ``ATTR_AGUI`` is streamed instead, whatever ``execution.mode`` says
        (spec #524 §5): AG-UI is a stream-only surface — it rejects any agent whose runner cannot
        stream — but ``IOHandler`` only constructs ``StreamAgentRunner`` when the mode is
        ``stream``, so an app serving AG-UI alongside plain REST would otherwise run its AG-UI
        traffic through the non-streamed path and produce one lump reply with no typed events.
        The marker, not a process-wide switch, decides.
        """
        if message.attributes.get(ATTR_AGUI):
            return self._process_stream(message)
        return self._process_nonstream(message)

    def _process_nonstream(self, message: QueueMessage) -> None:
        """Run the agent and forward one reply. The default path, and the integration path."""
        body = BaseRunRequest.model_validate(json.loads(message.body))
        request_id = self._resolve_request_metadata(message, body)

        self._log.info(f"[AGENT START] request_id={request_id}, session_id={body.session_id}, agent={body.agent}")

        # ChatService(rest_api_mode=False) returns (status_code, response_dict); unlike ECS,
        # the status travels to the output message as the STATUS_CODE attribute (spec §12.6).
        status_code, agent_response = self._chat_service.process_chat_request(req=body, requests=body.requests)
        self._send_to_output(message, agent_response, status_code)
        self._record_thread_reply(message, body, status_code, agent_response.get("result") if isinstance(agent_response, dict) else agent_response)

        self._log.info(f"[AGENT DONE] request_id={request_id}, status_code={status_code}")

    def _process_stream(self, message: QueueMessage) -> None:
        """Run the agent and fan each streamed chunk out as its own output message.

        Reached two ways: ``StreamAgentRunner.process`` for every non-integration message when
        ``execution.mode`` is ``stream``, and ``AgentRunner.process`` for an ``ATTR_AGUI`` message
        under any mode.

        :param message: The input message to run.
        """
        body = BaseRunRequest.model_validate(json.loads(message.body))
        request_id = self._resolve_request_metadata(message, body)
        is_agui = bool(message.attributes.get(ATTR_AGUI))
        if not is_agui and not message.attributes.get(ATTR_USER_ID) and QueueTransportFactory.resolve_type() != "in_memory":
            raise ValueError("user_id is required in queue message attributes for STREAM mode over a broker transport")

        self._log.info(f"[STREAM AGENT START] request_id={request_id} (receive_count={message.receive_count})")

        state_before = self._agui_state_before(message, body) if is_agui else None

        chunk_count = 0
        deltas: list[str] = []
        error_seen = False
        for raw_chunk in self._chat_service.process_stream_chat_sync(req=body, requests=body.requests):
            chunk = json.loads(raw_chunk)
            if chunk.get("error"):
                error_seen = True
            if chunk.get("delta"):
                deltas.append(chunk["delta"])
            self._send_to_output(message, chunk, status_code=None, dedup_suffix=f"{message.receive_count}-{chunk_count}")
            chunk_count += 1

        if not error_seen and deltas:
            self._record_thread_reply(message, body, 200, "".join(deltas))
        if is_agui and not error_seen:
            self._send_agui_state(message, body, state_before, chunk_count)

        self._log.info(f"[STREAM AGENT DONE] request_id={request_id}, chunks={chunk_count}")

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
        self._transport.check_consumer_capacity(QueueName.INPUT, queues.input.no_of_consumers)
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
        # A standalone runner container is usually PID 1: without these handlers SIGTERM never
        # arrives and pod/task stop hangs until SIGKILL instead of draining in-flight runs.
        ThreadRunner.install_shutdown_signal_handlers(cls._log)
        cls().start()

    # -- AG-UI shared state (spec #524 §5, design §15.5) ------------------------------------

    @classmethod
    def _agui_state_before(cls, message: QueueMessage, body: BaseRunRequest) -> Optional[dict]:
        """Snapshot the AG-UI shared state before the run, in this process.

        The comparison lives here and not at the edge because ``SessionStore.load`` returns the
        process-local cached copy when it has one (``core/session/redis.py:39-43``): the edge
        already loaded and cached this session to write the client's inbound state onto it, so an
        edge-side ``state_after`` would compare that cached object against its own snapshot and
        conclude nothing ever changed — silently dropping every ``StateSnapshot``. This process
        holds one session lifecycle and can tell the difference.

        Imported lazily and locally for the same reason as ``_record_thread_reply``: AG-UI is an
        ``integration`` capability, and a module-scope import would make every runner process pay
        for it.

        :param message: The input message, for error context only.
        :param body: The validated request body; supplies the session id.
        :return: A deep copy of the state, or None when there is none or it cannot be read.
        """
        try:
            from ..core.runtime import Runtime
            from ..integration.agui.state import AGUIState

            session = Runtime.current().sessions().load(body.session_id)
            return AGUIState.snapshot_state(session)
        except Exception:
            cls._log.exception(f"Could not snapshot AG-UI state for message {message.message_id}; no StateSnapshot will be emitted")
            return None

    def _send_agui_state(self, message: QueueMessage, body: BaseRunRequest, state_before: Optional[dict], chunk_count: int) -> None:
        """Emit one extra output chunk carrying the AG-UI state, but only if the run changed it.

        The edge turns this chunk into a ``StateSnapshotEvent``. Nothing is sent when the state is
        unchanged, so a turn that touches nothing re-syncs nothing — the rule the direct handler
        already applies (``integration/agui/handler.py:282-284``).

        Failures are logged, never raised: the reply chunks are already on the output queue, so
        retrying the message would run the agent a second time to fix bookkeeping.

        :param message: The input message the chunks were sent for.
        :param body: The validated request body; supplies the session id.
        :param state_before: The snapshot taken before the run.
        :param chunk_count: Number of chunks already sent, for a distinct dedup suffix.
        """
        try:
            from ..core.runtime import Runtime
            from ..integration.agui.state import AGUIState

            session = Runtime.current().sessions().load(body.session_id)
            state_after = AGUIState.read_state(session)
            if state_after == state_before:
                return
            self._send_to_output(
                message,
                {"agui_state": state_after},
                status_code=None,
                dedup_suffix=f"{message.receive_count}-{chunk_count}-state",
            )
            self._log.debug(f"Sent AG-UI state snapshot for session_id={body.session_id}")
        except Exception:
            self._log.exception(f"Failed to send AG-UI state snapshot for message {message.message_id}")

    # -- shared plumbing --------------------------------------------------------------------

    @classmethod
    def _record_thread_reply(cls, message: QueueMessage, body: BaseRunRequest, status_code: int, result) -> None:
        """Append the assistant message to the conversation thread this request belongs to.

        The other half of the split: ``ThreadRecorder.pre_run`` ran at the edge (the thread
        handler, before the request was enqueued), so only the reply is left, and only this
        process has it. The ``thread`` attribute is what says the edge recorded a user message
        for this request — without it a plain queue request would grow a thread nothing asked
        for.

        Called **after** ``_send_to_output`` deliberately. Recording first would duplicate the
        assistant message whenever the send then failed and the message was redelivered; this
        order trades that for losing a recording if the process dies in between, which is the
        safer direction (the caller still got its answer).

        Imported lazily and locally for the same reason as
        ``ResponseHandler._outbound_adapter``: threads are an ``integration`` capability, and a
        module-scope import would make every runner process — including ones with no thread
        block configured — pay for the thread stores.

        :param message: The input message, carrying the ``thread`` marker.
        :param body: The validated request body; supplies the session the thread is keyed by.
        :param status_code: The status the run produced; a failure records nothing.
        :param result: The agent's reply, recorded via ``str()``.
        """
        if not message.attributes.get(ATTR_THREAD) or status_code >= 400 or result in (None, ""):
            return
        try:
            from ..integration.thread.manager import ConversationThreadManager
            from ..integration.thread.recorder import ThreadRecorder

            manager = ConversationThreadManager.get()
            if manager is None:
                cls._log.warning(
                    "Input message is marked for thread recording but this process has no 'thread' "
                    "config block: the user message was recorded at the edge and the reply is lost. "
                    "Give the agent-runner process the same thread configuration as the API process."
                )
                return
            ThreadRecorder(manager).post_run(body, result)
        except Exception:
            cls._log.exception(f"Failed to record the assistant message for session_id={body.session_id}")

    @staticmethod
    def _resolve_request_metadata(message: QueueMessage, body: BaseRunRequest) -> str:
        """Resolve the message's request_id, preferring the attribute over the body.

        Scheduled triggers carry their metadata in the body instead of message attributes (the
        one delivery contract every schedule provider can honor), so the body is the fallback.
        A body-resolved id is injected back into the attributes because the output side forwards
        request_id/user_id from there (``_send_to_output``, ``ResponseHandler._store_response``).

        :param message: The input message; its attributes are updated on the body-fallback path.
        :param body: The already-validated request body (``extra="allow"``, so a trigger's
            request_id arrives as an extra attribute).
        :return: The resolved request id.
        :raises ValueError: If neither the attributes nor the body carry a request_id.
        """
        request_id = message.attributes.get(ATTR_REQUEST_ID)
        if request_id:
            return request_id

        request_id = getattr(body, "request_id", None)
        if not request_id:
            raise ValueError("request_id is required in queue message attributes or body")

        message.attributes[ATTR_REQUEST_ID] = request_id
        if body.user_id:
            message.attributes.setdefault(ATTR_USER_ID, body.user_id)
        return request_id

    def _send_to_output(self, source: QueueMessage, response_body, status_code: Optional[int] = None, dedup_suffix: Optional[str] = None) -> None:
        attributes = {key: value for key, value in source.attributes.items() if _is_forwarded(key)}
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

    On broker transports the chunks are pushed over WebSocket, so the USER_ID attribute (the
    WS-entered marker, spec #495 §2) is required; the in_memory transport also serves
    REST-entered chunks from the local response store over SSE, where no user is needed.
    """

    _log = logging.getLogger("ak.pipeline.stream_agent_runner")

    def process(self, message: QueueMessage) -> None:
        if message.attributes.get(ATTR_INTEGRATION):
            return self._process_nonstream(message)
        return self._process_stream(message)

    def on_permanent_failure(self, message: QueueMessage) -> None:
        if message.attributes.get(ATTR_INTEGRATION):
            return AgentRunner.on_permanent_failure(self, message)

        self._log.error(f"Permanent failure for message {message.message_id}")
        try:
            max_receive_count = AKConfig.get().execution.queues.input.max_receive_count
            error_chunk = StreamChunk(error=f"Failed to process message after {max_receive_count} retries", done=True).model_dump(exclude_none=True)
            if message.group_id:
                error_chunk["session_id"] = message.group_id
            self._send_to_output(message, error_chunk, status_code=None, dedup_suffix=f"{message.receive_count}-error")
        except Exception:
            self._log.exception("Failed to send permanent-failure stream chunk to output queue")
