"""Queue-mode AG-UI: run the agent on the pipeline instead of inside the SSE request (spec #710)."""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Optional
from uuid import uuid4

from fastapi import Request
from fastapi.responses import StreamingResponse

from ...auth.authoriser import Authoriser
from ...auth.handler import AuthValidator
from ...core.config import AKConfig
from ...core.model import StreamChunk
from ...core.multimodal.storage import AttachmentStorageManager
from ...core.util.factory import AKConfigError
from ...pipeline.envelope import ATTR_AGUI
from ...pipeline.producer import RequestProducer
from ...pipeline.response_store.factory import ResponseStoreFactory
from ...pipeline.transport.base import QueueTransportFactory
from .handler import AGUIRequestHandler
from .mapping import AGUIMapper
from .run_input import AGUIRunEnvelope, AGUIRunRequest

# The key the runner uses for its end-of-run state snapshot, which is not a StreamChunk.
AGUI_STATE_CHUNK_KEY = "agui_state"

ATTACHMENTS_DISABLED_ERROR = (
    "This AG-UI request carries an attachment, but multimodal support is disabled. "
    "Set multimodal.enabled: true, or send the request without attachments."
)
SESSION_CACHE_ERROR = (
    "multimodal.storage_type 'session_cache' keeps attachment bytes inside the session copy of the "
    "process that wrote them, so the agent runner cannot resolve them. Use in_memory, redis or dynamodb."
)


class AGUIPipelineRequestHandler(AGUIRequestHandler):
    """AG-UI served over the queue pipeline, as a sibling of the direct handler.

    Same routes, same protocol, same events: what changes is where the agent runs. The edge keeps
    the caller's SSE socket, enqueues the run, and drains the reply back out of the response store
    that the Response Handler writes into. The direct ``AGUIRequestHandler`` is unchanged and
    remains supported for deployments that want no queue; mounting this class is what selects the
    queue path, and it is what ``examples/api/agui`` ships with.

    Mount through ``IOHandler.run(handlers=[AGUIPipelineRequestHandler(...)])``. ``requires_pipeline``
    refuses a bare ``RESTAPI.run`` app, where the enqueued run would reach no runner and the caller
    would wait out the response-store budget for an answer nobody was producing.
    """

    requires_pipeline = True

    def __init__(self, authoriser: Optional[Authoriser] = None, auth_validator: Optional[AuthValidator] = None):
        """
        :param authoriser: Authoriser for the AG-UI routes.
        :param auth_validator: Wrapped as an Authoriser when `authoriser` is omitted.
        :raises ValueError: Everything AGUIRequestHandler rejects (missing extra, no authoriser).
        :raises AKConfigError: If the configured stores cannot serve a run from another process.
        """
        super().__init__(authoriser, auth_validator)
        self._log = logging.getLogger("ak.integration.agui.pipeline")
        self._validate_topology()
        self._store = ResponseStoreFactory.create()
        self._producer = RequestProducer()

    @staticmethod
    def _validate_topology() -> None:
        """Refuse a configuration whose pieces cannot reach each other, before the first request.

        The attachment check is the least obvious of the three: the edge offloads attachment bytes
        before enqueueing (see ``_run``) and ``MultimodalPreHook`` resolves the reference in the
        runner, so an unshared store hands the runner an id it cannot look up — a per-request
        failure with nothing wrong at startup.

        :raises AKConfigError: If the response store cannot stream chunks, or any of the response,
                               session and attachment stores is process-local while the agent runs
                               in another process.
        """
        store = ResponseStoreFactory.create()
        transport = QueueTransportFactory.resolve_type()

        if not store.supports_chunk_streaming():
            raise AKConfigError(
                f"AG-UI queue mode needs a chunk-streaming response store: '{type(store).__name__}' cannot stream "
                f"chunks; configure execution.response_store.type as redis or valkey"
            )
        if transport != "in_memory" and not store.shared:
            raise AKConfigError(
                f"response store '{type(store).__name__}' is process-local but the queue transport is '{transport}', "
                f"so the agent runs in another process; configure execution.response_store.type as redis or valkey"
            )
        # The session holds the conversation. A broker means a fleet of runners, so turn 2 can land
        # on a different one than turn 1 and read an empty dict; a restart empties it too. A single
        # replica happens to work, until it is scaled or redeployed, which is why this reads the
        # transport rather than a replica count.
        if transport != "in_memory" and AKConfig.get().session.type.lower() == "in_memory":
            raise AKConfigError(
                f"session store 'in_memory' is single-process only, but the queue transport is '{transport}'; "
                f"configure session.type as redis, valkey, dynamodb, cosmosdb or firestore"
            )
        if AKConfig.get().multimodal.enabled and transport != "in_memory" and not AttachmentStorageManager.store_is_shared():
            raise AKConfigError(
                f"multimodal.storage_type '{AKConfig.get().multimodal.storage_type}' keeps attachments in the process "
                f"that wrote them, but the queue transport is '{transport}', so the agent runs in another one: an "
                f"AG-UI attachment offloaded at the edge would be unresolvable in the runner. Use redis or dynamodb, "
                f"or run the single-process in_memory transport"
            )

    async def _run(self, agent_name: str, request: Request) -> StreamingResponse:
        """Enqueue the run and hand back the event stream the store will fill.

        The edge half is the direct handler's verbatim (``_resolve_run_inputs``), so the 404/400
        contract cannot drift between the two. It writes no session: the runner owns that lifecycle,
        and the client's inbound values travel on the body instead (spec #710 §5-6).

        :param agent_name: Agent to run.
        :param request: Incoming request carrying the RunAgentInput body.
        :return: A streaming response of encoded AG-UI events.
        :raises HTTPException: 400/404 from resolution, parsing, the envelope budget or attachments.
        """
        from ag_ui.encoder import EventEncoder

        user_id, agent, run_input, requests = await self._resolve_run_inputs(agent_name, request)
        envelope = AGUIRunEnvelope.build(run_input)
        envelope.reject_if_oversized()
        self._warn_if_unreadable(agent, run_input)

        # Bytes must not ride the queue: brokers cap a message far below api.max_file_size.
        requests, _ = AttachmentStorageManager.offload(
            run_input.thread_id,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )

        request_id = uuid4().hex
        # Offload the sync send so it doesn't block the event loop, as the REST handler does.
        await asyncio.to_thread(
            self._producer.enqueue,
            AGUIRunRequest(session_id=run_input.thread_id, agent=agent.name, user_id=user_id, requests=requests, agui=envelope),
            request_id=request_id,
            attributes={ATTR_AGUI: "1"},
            group_id=run_input.thread_id,
        )
        self._log.info(f"[AGUI ENQUEUED] request_id={request_id}, thread_id={run_input.thread_id}, agent={agent.name}")

        encoder = EventEncoder(accept=request.headers.get("accept"))  # type: ignore[arg-type]
        return StreamingResponse(self._events_from_store(encoder, request_id, run_input), media_type=encoder.get_content_type())

    async def _events_from_store(self, encoder: Any, request_id: str, run_input: Any) -> AsyncGenerator[str, None]:
        """Yield the run's encoded AG-UI events, drained from the response store.

        The protocol bracket is the direct handler's: `RunStarted` first, exactly one of
        `RunFinished` or `RunError` last, so a client never waits on a terminal event that does not
        come. The HTTP status is already sent by the time this runs, so every failure — a timeout,
        a runner that gave up, a dead store — is reported as `RunError` rather than raised.

        The runner's state snapshot arrives as a chunk rather than a StreamChunk event, because
        only the runner can compute it (a cached session store hands the edge back its own copy).

        :param encoder: The SDK's EventEncoder, matched to the request's Accept header.
        :param request_id: The enqueued run's id, which is also its chunk stream's key.
        :param run_input: The parsed RunAgentInput, for thread and run ids.
        :return: An async generator of encoded SSE payloads.
        """
        from ag_ui.core import RunErrorEvent, RunFinishedEvent, RunStartedEvent, StateSnapshotEvent

        yield encoder.encode(RunStartedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id, parent_run_id=run_input.parent_run_id))

        chunks = self._store.stream(request_id)
        error: Optional[str] = None
        try:
            while True:
                # The store's stream is a blocking iterator; a worker thread keeps the event loop free.
                chunk = await asyncio.to_thread(next, chunks, None)
                if chunk is None:
                    break
                if AGUI_STATE_CHUNK_KEY in chunk:
                    yield encoder.encode(StateSnapshotEvent(snapshot=chunk[AGUI_STATE_CHUNK_KEY]))
                    continue
                payload = StreamChunk.model_validate(chunk)
                if payload.error:
                    error = payload.error
                    continue
                if payload.event is None:
                    continue
                agui_event = AGUIMapper.to_agui(payload.event)
                if agui_event is not None:
                    yield encoder.encode(agui_event)
        except TimeoutError:
            self._log.warning(f"AG-UI stream timed out for request_id={request_id}", exc_info=True)
            yield encoder.encode(RunErrorEvent(message="The run produced no response in time"))
            return
        except Exception:
            self._log.exception(f"AG-UI stream delivery failed for request_id={request_id}")
            yield encoder.encode(RunErrorEvent(message="The run could not be delivered"))
            return
        finally:
            # Offloaded like the enqueue: blocking on a redis-like store, and this runs on the
            # event loop. The await still completes under the cancellation a disconnect raises.
            await asyncio.to_thread(self._store.close_stream, request_id)

        if error is not None:
            yield encoder.encode(RunErrorEvent(message=error))
            return

        yield encoder.encode(RunFinishedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id))
