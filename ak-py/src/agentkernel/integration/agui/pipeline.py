"""
AG-UI on the queue pipeline (spec #524 §10, design §15).

The direct handler runs the agent inside its own SSE request, which is the shape the seven
messaging platforms and the thread handler were moved off: a slow model holds a connection, and
the run cannot be retried or scaled apart from the web tier.

AG-UI cannot use the adapter seam that fixed that, because it is a caller-waits surface: an
``OutboundAdapter`` pushes a finished reply to an address made of strings, and AG-UI's reply is
*n* typed events going back down a socket the caller is still holding — a file descriptor owned
by a live task in one process, which no queue attribute can carry.

So the direction inverts. A messaging adapter *pushes* from the runner; this *pulls* into the
process that never let go. The runner writes chunks to the response store under the run's
``request_id`` — and a ``request_id`` is a string, which fits a queue attribute perfectly.
"""

import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from ...auth.authoriser import Authoriser
from ...auth.handler import AuthValidator
from ...core.config import AKConfig
from ...core.model import BaseRunRequest, StreamChunk
from ...core.runtime import Runtime
from ...core.util.factory import AKConfigError
from ...pipeline.envelope import ATTR_AGUI
from ...pipeline.producer import RequestProducer
from ...pipeline.response_store.base import ResponseStore
from ...pipeline.response_store.factory import ResponseStoreFactory
from ...pipeline.transport.base import QueueTransport, QueueTransportFactory
from .handler import AGUIEdge, AGUIRequestHandler
from .mapping import AGUIMapper

#: Key the runner stamps on its state-snapshot chunk (``AgentRunner._send_agui_state``).
AGUI_STATE_CHUNK_KEY = "agui_state"


class AGUIPipelineRequestHandler(AGUIRequestHandler):
    """
    Queue-mode AG-UI: the queue-mode counterpart of AGUIRequestHandler, as
    ThreadRequestHandler is of AgentThreadRequestHandler. Mount it instead of the
    direct handler; mounting is what selects the topology.

        IOHandler.run(handlers=[AGUIPipelineRequestHandler(auth_validator=...)])

    The edge keeps the client's SSE connection and enqueues the run; the Agent
    Runner executes it (streaming on the message's marker, whatever
    execution.mode says) and fans each chunk out to the output queue; the
    Response Handler writes them to the response store; and this handler's
    generator — still holding the socket — drains the store, maps each chunk
    through AGUIMapper and encodes it out. The client sees the identical event
    stream and cannot tell which topology served it.

    It mounts through `handlers=[...]` rather than `request_handler=`: AG-UI owns
    `agui.prefix`, so unlike ThreadRequestHandler it collides with no pipeline
    route.

    Endpoints: the inherited AG-UI discovery and run routes (see AGUIRequestHandler).
    """
    requires_pipeline = True

    def __init__(
        self,
        authoriser: Optional[Authoriser] = None,
        auth_validator: Optional[AuthValidator] = None,
        transport: Optional[QueueTransport] = None,
        response_store: Optional[ResponseStore] = None,
    ):
        """
        :param authoriser: Authoriser for the AG-UI routes.
        :param auth_validator: Wrapped as an Authoriser when `authoriser` is omitted.
        :param transport: Queue transport to enqueue on; defaults to the configured one.
        :param response_store: Response store to drain; defaults to the configured one.
        :raises ValueError: From the base handler: missing `agui` extra, no authoriser or
                            validator, or a `default_agent` outside `agui.agents`.
        :raises AKConfigError: If the topology cannot deliver a reply — see :meth:`_check_topology`.
        """
        super().__init__(authoriser=authoriser, auth_validator=auth_validator)
        self._log = logging.getLogger("ak.integration.agui.pipeline")
        self._transport = transport or QueueTransportFactory.create()
        self._store = response_store or ResponseStoreFactory.create()
        self._check_topology()

    def _check_topology(self) -> None:
        """Reject a topology whose reply can never reach the client, at construction.

        Both failures are silent at runtime and worse than a crash, which is why they are checked
        here rather than discovered mid-stream (the posture of Decision Q2):

        - a response store that cannot stream chunks has nowhere to put the runner's output, so
          the client would hold an SSE connection open until its budget expired;
        - `session.type: in_memory` on a broker transport means the runner loads a session this
          process never shared, so the client's inbound `state` and `forwardedProps` silently
          never reach the tools that read them. It is also the accidental default.

        :raises AKConfigError: When either holds.
        """
        if not self._store.supports_chunk_streaming():
            raise AKConfigError(
                f"queue-mode AG-UI needs a chunk-streaming response store, and "
                f"{type(self._store).__name__} is not one: configure execution.response_store.type as "
                f"in_memory (single process), redis or valkey — or mount AGUIRequestHandler on RESTAPI.run "
                f"to run AG-UI in-process instead"
            )

        config = AKConfig.get()
        if QueueTransportFactory.resolve_type() != "in_memory" and config.session.type == "in_memory":
            raise AKConfigError(
                "queue-mode AG-UI needs a shared session store: the agent runs in another process, so with "
                "session.type 'in_memory' the client's AG-UI state and forwardedProps never reach it. "
                "Configure session.type as redis, valkey, dynamodb, cosmosdb or firestore"
            )

    async def _run(self, agent_name: str, request: Request) -> StreamingResponse:
        """Resolve the run, enqueue it, and hand back the stream that drains the reply.

        The socket stays with this replica; only the run travels. Everything that can still be an
        HTTP status happened in `_prepare`, so once the response begins the only way to report a
        failure is a `RunError` event.

        :param agent_name: Agent to run.
        :param request: Incoming request carrying the RunAgentInput body.
        :return: A streaming response of encoded AG-UI events.
        :raises HTTPException: See :meth:`AGUIRequestHandler._prepare`.
        """
        edge = await self._prepare(agent_name, request)

        # The runner loads this session in another process, so the client's state has to be
        # persisted here — the direct handler never needs to, because it runs on this object.
        await asyncio.to_thread(Runtime.current().sessions().store, edge.session)

        # A fresh id, not run_input.run_id: the client supplies that, and a client reusing one
        # would collide with a live run in the response store.
        request_id = str(uuid.uuid4())
        body = BaseRunRequest(
            # Legal empty: ChatService._validate requires a prompt only when `requests` is None,
            # and AG-UI always supplies a prebuilt list.
            prompt="",
            agent=edge.agent.name,
            session_id=edge.run_input.thread_id,
            user_id=edge.user_id,
            requests=edge.requests,
        )
        self._log.info(f"[AGUI ENQUEUE] request_id={request_id}, session_id={edge.run_input.thread_id}, agent={edge.agent.name}")
        await asyncio.to_thread(
            RequestProducer(self._transport).enqueue,
            body,
            request_id,
            {ATTR_AGUI: "1"},
            edge.run_input.thread_id,
            request_id,
        )

        stream = self._events_from_store(edge, request_id)
        return StreamingResponse(stream, media_type=edge.encoder.get_content_type())

    async def _events_from_store(self, edge: AGUIEdge, request_id: str) -> AsyncGenerator[str, None]:
        """Yield the run's encoded AG-UI events, sourced from the response store.

        The queue-mode counterpart of `AGUIRequestHandler._events`, and it keeps the same
        contract: `RunStarted` first, then the run's events, then **exactly one** of
        `RunFinished` or `RunError`. A client waits on that terminal event, so every failure
        path here ends in one — an error chunk from the runner, the permanent-failure chunk the
        Response Handler writes, a store timeout, or an unexpected exception.

        :param edge: The resolved run context, for its encoder and run ids.
        :param request_id: The key the runner's chunks are stored under.
        :return: An async generator of encoded SSE payloads.
        """
        from ag_ui.core import RunErrorEvent, RunFinishedEvent, RunStartedEvent, StateSnapshotEvent

        yield edge.encoder.encode(
            RunStartedEvent(thread_id=edge.run_input.thread_id, run_id=edge.run_input.run_id, parent_run_id=edge.run_input.parent_run_id)
        )

        error: Optional[str] = None
        chunks = self._store.stream(request_id)
        try:
            while True:
                # stream() is a *synchronous* blocking iterator: awaiting it on the event loop
                # would freeze every other request on this replica, so each step runs in a
                # worker thread — the same bridge RequestHandler._sse_stream uses.
                record = await asyncio.to_thread(next, chunks, None)
                if record is None:
                    break
                if record.get("error"):
                    error = record["error"]
                    break
                if AGUI_STATE_CHUNK_KEY in record:
                    # The runner only sends this when the run actually changed the state, so a
                    # turn that touches nothing re-syncs nothing.
                    yield edge.encoder.encode(StateSnapshotEvent(snapshot=record[AGUI_STATE_CHUNK_KEY]))
                    continue
                for encoded in self._encode_chunk(edge, record):
                    yield encoded
        except TimeoutError as e:
            # The store's own message: it names only the request_id and the wait budget.
            yield edge.encoder.encode(RunErrorEvent(message=str(e)))
            return
        except Exception as e:
            self._log.exception(f"AG-UI queue-mode run failed for agent '{edge.agent.name}', request_id={request_id}")
            yield edge.encoder.encode(RunErrorEvent(message=str(e)))
            return
        finally:
            # Deterministic release, including when the client disconnects mid-stream: the
            # sentinel unblocks a reader parked on the store and drops the chunk state.
            self._store.close_stream(request_id)

        if error is not None:
            yield edge.encoder.encode(RunErrorEvent(message=error))
            return

        yield edge.encoder.encode(RunFinishedEvent(thread_id=edge.run_input.thread_id, run_id=edge.run_input.run_id))

    def _encode_chunk(self, edge: AGUIEdge, record: dict) -> list:
        """Map one stored `StreamChunk` record to its encoded AG-UI events.

        `StreamEvent` is a `type`-discriminated union of models carrying only `str`/`int`/`bool`
        (`core/event.py`), so the typed event survives the queue hop intact and `AGUIMapper` sees
        exactly what the direct path sees.

        A record with no `event` yields nothing: AG-UI's content comes from the typed events, so a
        bare `delta` is redundant and the terminal `done` is represented by `RunFinished`.

        :param edge: The resolved run context, for its encoder.
        :param record: One chunk as stored by the Response Handler.
        :return: Encoded payloads, in order; empty when the chunk has no AG-UI equivalent.
        """
        try:
            chunk = StreamChunk.model_validate(record)
        except Exception:
            self._log.warning(f"Discarding an unparsable AG-UI chunk: {json.dumps(record)[:200]}")
            return []
        if chunk.event is None:
            return []
        agui_event = AGUIMapper.to_agui(chunk.event)
        return [] if agui_event is None else [edge.encoder.encode(agui_event)]
