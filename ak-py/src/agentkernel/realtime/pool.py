import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from concurrent.futures import Future
from contextlib import contextmanager
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from ..core.base import Agent as BaseAgent
from ..core.base import Session
from ..core.config import AKConfig
from ..core.event import AgentChanged, AudioDelta, InputTranscript, Interrupt, MessageEnd, StreamEvent, TextDelta
from ..core.hooks import StreamHalt
from ..core.model import AgentRequest, AgentRequestText, AgentRequestVoice, Principal, StreamChunk
from ..core.runtime import Runtime
from ..core.tool import ToolContext
from ..pipeline.envelope import (
    ATTR_INTEGRATION,
    ATTR_REALTIME,
    ATTR_REALTIME_END,
    ATTR_REQUEST_ID,
    ATTR_USER_ID,
    REPLY_CONTEXT_PREFIX,
    QueueMessage,
    QueueName,
)
from ..pipeline.integration_delivery import IntegrationDelivery
from ..pipeline.thread_runner import ThreadRunner
from ..pipeline.transport.base import QueueTransport, QueueTransportFactory
from .audio import EDGE_SAMPLE_RATE, PCM16Resampler
from .base import RealtimeRunner as BaseRealtimeRunner

if TYPE_CHECKING:  # typing only; the runners pass these in
    from ..core.chat_service import ChatService
    from ..core.model import BaseRunRequest


class RealtimeConnection:
    """One call's native realtime session, and the paced route its output takes to the output queue.

    Wraps the framework's ``RealtimeRunner`` (``self.runner``). Created and driven by
    :class:`RealtimeConnectionPool`; nothing else builds one.

    Semantics, in order:

    1. ``connect()`` runs on the pool loop. It queues the initial speaker and team first, so they reach the
       edge ahead of any model output, then opens the native session with ``ToolContext``,
       ``Session.current()`` and ``Agent.current()`` set (the SDK's own tool tasks inherit them; the session
       lock is not held, since a call would block every other run of the session). Once open the state is
       ``OPEN``, the ``[REALTIME CALL START]`` line is logged and the pacing task starts.
    2. Caller input arrives from consumer threads. ``append_audio`` and ``send_text`` schedule the send on the
       pool loop and wait, bounded by ``SEND_TIMEOUT_SECONDS``, so the input is normally acked once the model has it.
       On the loop the input first runs through the pre-hooks (see Hooks below), and what they leave is sent
       to the model. A send that fails or times out is logged and the input
       is still acked: the caller's audio keeps flowing, and one lost chunk or message does not fail the call.
    3. The runner reports events through ``handle_framework_event``. Audio, ``transcript_delta``, ``done``,
       ``agent_changed`` and ``input_transcript`` all ride one queue (``_output_queue``), so a control event
       cannot overtake the audio it belongs to. The pacing loop drains it: every event goes through the
       post-hooks first, and the audio that leaves is emitted at playback rate.
    4. A barge-in (``interrupt``, or ``speech_started`` while paced audio is still queued) drops unheard
       audio and transcript deltas but keeps control events and ``input_transcript``.
    5. An ``error`` event, an event the contract does not list, or a post-hook that halts the call fails the
       connection: the edge gets one terminal error chunk, the state moves to ``CLOSING`` and ``close()`` runs
       in the background.
    6. ``mark_closed()`` is how the pool (or a failure) says "this connection is dead": the state moves to
       ``CLOSING`` and the pool evicts it on the next lookup. The native session is still open until
       ``close()`` runs.
    7. ``close()`` claims the connection (state ``CLOSED``), cancels a connect still in flight, stops pacing,
       disconnects the runner, unpublishes the principal and clears the session's volatile cache (hook state ends
       with the call). A second call returns at once, so shutdown, eviction and failure can all close one
       connection. Logs ``[REALTIME CALL END]`` when it finishes.

    Hooks (run on the pool loop, with ``Session.current()`` and ``Agent.current()`` set):

    - Typed text goes through ``PreHook.on_run``. A hook that halts replies with one error chunk to the edge, as
      ``Runtime.stream()`` does, and the call continues.
    - Each audio chunk goes through ``PreHook.on_stream_input``. A failing audio hook drops that chunk, with no
      error chunk (one per chunk would flood the edge). The first failure of a connection is logged at ERROR,
      later ones at DEBUG.
    - Every output event goes through ``PostHook.on_stream_event`` before it is paced. A ``StreamHalt``, or a
      post-hook that fails, fails the call (step 5).
    - The ``requests`` that post-hooks receive is the last typed turn, as the pre-hooks left it: empty on an
      audio-only call.
    """

    # What each lifecycle state means, and who moves it:
    #   CONNECTING  built by the pool; the native session is not open yet.
    #   OPEN        connect() finished; the pacing task is running.
    #   CLOSING     mark_closed() was called: dead to the pool, but close() has not started.
    #   CLOSED      close() has taken the connection over (running or finished). Never left.
    class _State(Enum):
        CONNECTING = "connecting"
        OPEN = "open"
        CLOSING = "closing"
        CLOSED = "closed"

    _log = logging.getLogger("ak.realtime.connection")

    # Bound on a consumer thread's wait for a model send to complete before the input is acked.
    SEND_TIMEOUT_SECONDS = 10.0
    # Output backlog the pacing loop may hold. Audio arrives faster than it plays, so this must be deep enough
    # for a long model turn; a full queue makes the runner's callback wait, which is the back-pressure.
    OUTPUT_QUEUE_MAXSIZE = 1024

    # Close tasks started by ``close_in_background``: the loop keeps only a weak reference to a task.
    _close_tasks: ClassVar[set[asyncio.Task]] = set()

    def __init__(
        self,
        session_id: str,
        agent: BaseAgent,
        runtime: Runtime,
        session: Session,
        loop: asyncio.AbstractEventLoop,
        *,
        transport: QueueTransport,
        playback_lead_ms: int,
    ):
        """
        :param session_id: The AK session id, also the output queue group.
        :param agent: The agent the call starts with; it names the runner class (``realtime_runner_cls``).
        :param runtime: The runtime the call's identity is published on.
        :param session: The AK session the call is bound to.
        :param loop: The pool's event loop, which every native-session call runs on.
        :param transport: Where output chunks are sent (the output queue). Built once by the pool.
        :param playback_lead_ms: How much audio the edge holds ahead of playback. Built once by the pool.
        """
        self.session_id = session_id
        self.agent = agent
        self.runtime = runtime
        self.session = session
        self.loop = loop
        self._transport = transport
        self._playback_lead_ms = playback_lead_ms

        self.request_id: str | None = None
        self.user_id: str | None = None
        self.integration: str | None = None
        self.reply_context: dict = {}
        # The principal of the last input dispatched here, published on the session for the tool
        # calls the native session makes in reply (spec #603, section 8.4). None runs them anonymous.
        self.principal: Principal | None = None
        self._principal_published = False
        # Lifecycle. Moved from consumer threads (mark_closed) and from the loop (connect, close), so
        # every move happens under the lock.
        self._state = RealtimeConnection._State.CONNECTING
        self._state_lock = threading.Lock()
        # Why the connection closed, for the [REALTIME CALL END] line. The first reason given wins.
        self._close_reason: str | None = None
        # A session that produced output restarts the reconnect back-off count when it fails.
        self.produced_output = False
        self._output_queue: asyncio.Queue = asyncio.Queue(maxsize=self.OUTPUT_QUEUE_MAXSIZE)
        # Audio not yet emitted: while it is non-zero, the user starting to speak is a barge-in.
        self._queued_audio = 0
        # The pacing window: when it opened and how much audio it has emitted (milliseconds of playback).
        self._pace_start = 0.0
        self._pace_played_ms = 0.0
        # The message_id of the turn's last output event, which the MessageEnd that closes the turn carries.
        self._turn_message_id: str | None = None
        # The last text turn sent to the model (after pre-hooks): the `requests` argument post-hooks receive.
        self._last_turn: list[AgentRequest] = []
        # The first failing audio hook of a connection is logged at ERROR; later ones at DEBUG, since audio arrives at the chunk rate.
        self._input_failure_logged = False
        self._pacing_task: asyncio.Task | None = None
        self._startup_task: asyncio.Task | None = None
        # The edge was already sent this connection's terminal error, so a failed start must not send a second.
        self.failure_reported = False
        self.last_activity_at: float = time.time()

        if not getattr(self.agent, "realtime_runner_cls", None):
            raise ValueError(f"Agent {self.agent.name} has no realtime_runner_cls configured")

        self.runner: "BaseRealtimeRunner" = self.agent.realtime_runner_cls()

    # -- lifecycle ----------------------------------------------------------------------------------------

    @property
    def closed(self) -> bool:
        """True once the connection is dead: the pool evicts it and the next input reconnects. Read-only; see :meth:`mark_closed`."""
        return self._state in (RealtimeConnection._State.CLOSING, RealtimeConnection._State.CLOSED)

    def mark_closed(self, reason: str = "closed") -> None:
        """Mark the connection dead without closing it: ``closed`` turns True and the pool evicts it.

        Thread-safe. Idempotent, and a no-op once ``close()`` has taken the connection over. The native
        session stays open until ``close()`` runs; every caller that marks a connection closed also
        arranges that.

        :param reason: Why, for the ``[REALTIME CALL END]`` line. The first reason given wins.
        """
        with self._state_lock:
            if self._state is not RealtimeConnection._State.CLOSED:
                self._state = RealtimeConnection._State.CLOSING
            if self._close_reason is None:
                self._close_reason = reason

    async def connect(self) -> None:
        """Connect the runner and start pacing; the initial speaker and team are queued ahead of any output."""
        self._startup_task = asyncio.current_task()
        try:
            await self._connect()
        finally:
            self._startup_task = None

    async def _connect(self) -> None:
        if self.closed:
            return
        speaker = self.runner.initial_speaker(self.agent)
        if speaker is not None:
            await self._output_queue.put((BaseRealtimeRunner.Event.AGENT_CHANGED, {"agent": speaker, "agents": self.runner.team(self.agent)}))
        # Set once here: the SDK's tool tasks are created inside connect() and inherit these contextvars.
        # The session lock is not taken; holding it for a whole call would block every other run of the session.
        tool_context = ToolContext(self.runtime, self.agent, self.session, []).set()
        session_token = Session.current_session.set(self.session)
        try:
            with self.agent._activate():
                await self.runner.connect(self.session, self.agent, self.handle_framework_event)
        finally:
            Session.current_session.reset(session_token)
            tool_context.reset()
        if self.closed:
            # end_session() may have closed this connection while the native session was still opening:
            # close what it opened now, and leave no pacing task behind for a connection nobody reads.
            if self._state is not RealtimeConnection._State.CLOSED:
                await self.close()
            return
        self._pacing_task = asyncio.create_task(self._pacing_loop())
        with self._state_lock:
            # Not OPEN if another thread marked it closed since the check above: that mark must stand.
            opened = self._state is RealtimeConnection._State.CONNECTING
            if opened:
                self._state = RealtimeConnection._State.OPEN
        if opened:
            self._log.info(f"[REALTIME CALL START] session_id={self.session_id} agent={self.agent.name}")

    async def fail_to_connect(self, error: BaseException) -> None:
        """Send the edge one terminal error chunk for a failed connect, then close what it opened.

        :param error: What the connect raised (a timeout included).
        """
        self._log.error(f"Realtime session {self.session_id} could not start: {error!r}")
        try:
            await self._emit(StreamChunk(error=f"Realtime session could not start: {str(error) or type(error).__name__}", done=True))
        except Exception:
            self._log.exception(f"Realtime session {self.session_id}: could not report its failed start")
        finally:
            await self.close()

    async def close(self) -> None:
        """Stop pacing and disconnect the runner; a second call returns at once."""
        with self._state_lock:
            if self._state is RealtimeConnection._State.CLOSED:
                return
            self._state = RealtimeConnection._State.CLOSED
            if self._close_reason is None:
                self._close_reason = "closed"
        try:
            startup = self._startup_task
            if startup is not None and startup is not asyncio.current_task() and not startup.done():
                startup.cancel()
                [result] = await asyncio.gather(startup, return_exceptions=True)
                if isinstance(result, Exception):
                    self._log.error(f"Realtime session {self.session_id}: startup failed while closing: {result}")
            if self._pacing_task:
                self._pacing_task.cancel()
                self._pacing_task = None
            try:
                await self.runner.disconnect()
            finally:
                if self._principal_published:
                    self.session._unpublish_run()
                # Hook state kept in the volatile cache ends with the call, as it does when a Runtime run ends,
                # also when the native session fails to close: the session store hands the next call this same Session.
                self.session.get_volatile_cache()._clear_all()
        finally:
            self._log.info(f"[REALTIME CALL END] session_id={self.session_id} reason={self._close_reason}")

    def close_in_background(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule :meth:`close` on ``loop``; the task is held in ``_close_tasks`` since the loop keeps only a weak reference."""
        task = loop.create_task(self.close())
        RealtimeConnection._close_tasks.add(task)
        task.add_done_callback(self._close_finished)

    def _close_finished(self, task: "asyncio.Task") -> None:
        RealtimeConnection._close_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self._log.error(f"Realtime session {self.session_id}: failed to close: {task.exception()}")

    # -- identity, delivery context and hook scope ---------------------------------------------------------

    def publish_principal(self, principal: Principal | None) -> None:
        """Publish the principal of the input just dispatched, for the tool calls the model makes in reply.

        The framework's native session runs its own tools (#810), with no ``Runtime.run`` around a
        call, so the identity ``Runtime`` publishes for a turn is published on the session here, where
        ``ToolContext.principal`` and ``session.get_principal()`` read it, and the session's owner is
        recorded as on a turn (spec #603, section 8.4). It runs on the connection's loop, ahead of the
        input's audio or text, and only a changed principal is republished, since every audio chunk
        is an input.

        :param principal: The input's principal, or None when it named nobody (anonymous).
        """
        if self._principal_published and principal == self.principal:
            return
        self.principal = principal
        self._principal_published = True
        self.loop.call_soon_threadsafe(self.runtime._publish, self.agent, self.session, principal)

    def update_delivery_context(self, request_id: str | None, user_id: str | None, integration: str | None, reply_context: dict) -> None:
        """Record where this connection's output goes, for text input as well as audio.

        Called by ``RealtimeConnectionPool.dispatch`` before every input (voice or text), and once when the connection is created,
        so the output the model produces in reply is stamped with the latest return address.

        :param request_id: The request id stamped on the output chunks.
        :param user_id: The WebSocket routing marker the output is stamped with, if any (not an identity).
        :param integration: The messaging integration the output is delivered through, if any.
        :param reply_context: The integration's reply context (already stripped of its ``reply_`` prefix).
        """
        self.request_id = request_id
        self.user_id = user_id
        self.integration = integration
        self.reply_context = reply_context

    @contextmanager
    def _hook_context(self) -> Iterator[None]:
        """Set ``Session.current()`` and ``Agent.current()`` around a hook call.

        The pacing task and an input coroutine start without them: ``_connect`` resets them before it creates the pacing task.
        """
        token = Session.current_session.set(self.session)
        try:
            with self.agent._activate():
                yield
        finally:
            Session.current_session.reset(token)

    # -- input: edge -> model -----------------------------------------------------------------------------

    def append_audio(self, request: AgentRequestVoice) -> None:
        """Thread-safe: run one chunk of caller audio through the pre-hooks, then send what is left to the model."""
        self.last_activity_at = time.time()
        self._dispatch_send(self._process_audio(request), "append_audio")

    def send_text(self, request: AgentRequestText) -> None:
        """Thread-safe: run one typed caller message through the pre-hooks, then send what is left to the model."""
        self.last_activity_at = time.time()
        self._dispatch_send(self._process_text(request), "send_text")

    def _dispatch_send(self, coro, action: str) -> None:
        """Run a send on the pool loop, blocking (bounded by ``SEND_TIMEOUT_SECONDS``) so the input is normally acked once the model has it.

        A failed or timed-out send is logged and not raised, so the input is still acked. On the pool loop itself the send is
        scheduled instead, and a failure is logged.
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is self.loop:
            task = self.loop.create_task(coro)
            task.add_done_callback(lambda t: self._log_send_failure(t, action))
            return

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            future.result(timeout=self.SEND_TIMEOUT_SECONDS)
        except Exception:
            self._log.exception(f"Realtime session {self.session_id}: failed to {action}")

    async def _process_audio(self, request: AgentRequestVoice) -> None:
        """Run a chunk through ``on_stream_input``; audio goes to the model, text a hook made goes the typed-text way.

        A failing hook drops the chunk: an error chunk per audio chunk would flood the edge.
        """
        try:
            with self._hook_context():
                voice, text = await self.runtime.run_stream_input_hooks(self.agent, self.session, request)
        except Exception:
            if self._input_failure_logged:
                self._log.debug(f"Realtime session {self.session_id}: an input hook failed; chunk dropped", exc_info=True)
            else:
                self._input_failure_logged = True
                self._log.exception(f"Realtime session {self.session_id}: an input hook failed; chunk dropped (later failures are logged at DEBUG)")
            return
        for chunk in voice:
            await self._send_audio_to_model(chunk.audio_data)
        for item in text:
            await self._process_text(item)

    async def _send_audio_to_model(self, audio_data: str) -> None:
        """Convert edge-rate audio to the model's input rate and send it."""
        pcm16 = PCM16Resampler.resample(base64.b64decode(audio_data), EDGE_SAMPLE_RATE, self.runner.input_sample_rate)
        await self.runner.append_audio(base64.b64encode(pcm16).decode("utf-8"))

    async def _process_text(self, request: AgentRequestText) -> None:
        """Run one typed message (one turn) through the pre-hooks and send the resulting text to the model once.

        A hook that halts the turn, or fails, sends the edge one error chunk and the call continues.
        """
        try:
            with self._hook_context():
                result = await self.runtime.run_pre_hooks(self.agent, self.session, [request])
        except Exception:
            self._log.exception(f"Realtime session {self.session_id}: a pre-hook failed on a typed message")
            await self._emit(StreamChunk(error="Your message could not be processed.", done=True))
            return
        if not isinstance(result, list):
            await self._emit(StreamChunk(error=str(result), done=True))
            return
        self._last_turn = result
        prompts = [item.prompt for item in result if isinstance(item, AgentRequestText)]
        if len(prompts) < len(result):
            self._log.debug(f"Realtime session {self.session_id}: dropped {len(result) - len(prompts)} non-text request(s) a pre-hook returned")
        if prompts:
            await self.runner.send_text("\n".join(prompts))

    def _log_send_failure(self, task: "asyncio.Task", action: str) -> None:
        if not task.cancelled() and task.exception() is not None:
            self._log.error(f"Realtime session {self.session_id}: failed to {action}: {task.exception()}")

    # -- output: model -> edge ----------------------------------------------------------------------------

    async def handle_framework_event(self, event_type: str, data: dict) -> None:
        """Queue one runner event behind the audio it belongs to; an unknown event fails the connection.

        ``speech_started`` is a barge-in only while paced audio is still queued.

        :param event_type: One of the :class:`RealtimeRunner.Event` names (a plain string with the same value works).
        :param data: The event's payload.
        """
        Event = BaseRealtimeRunner.Event
        if self.closed:
            return
        self.last_activity_at = time.time()
        if event_type in (Event.AUDIO_DELTA, Event.TRANSCRIPT_DELTA, Event.DONE):
            self.produced_output = True
        if event_type == Event.AUDIO_DELTA:
            self._queued_audio += 1
            await self._output_queue.put((Event.AUDIO_DELTA, data))
        elif event_type == Event.INTERRUPT:
            await self._interrupt(data)
        elif event_type == Event.SPEECH_STARTED:
            if self._queued_audio > 0:
                await self._interrupt(data)
        elif event_type in (Event.DONE, Event.TRANSCRIPT_DELTA, Event.AGENT_CHANGED, Event.INPUT_TRANSCRIPT):
            await self._output_queue.put((event_type, data))
        elif event_type == Event.ERROR:
            await self._fail(data.get("message") or "realtime session error")
        elif event_type == "tool_call":
            # Not an Event member: the contract has no such event. Kept for its own message, because a runner
            # written for the old contract (the pool ran its tools) fails here and the cause should be obvious.
            await self._fail(
                f"Realtime runner {type(self.runner).__name__} reported a tool_call, which the realtime pool no longer runs: "
                "the framework's native session executes its own tools"
            )
        else:
            await self._fail(f"Realtime runner {type(self.runner).__name__} reported an unknown event '{event_type}'")

    async def _interrupt(self, data: dict) -> None:
        """Drop unheard audio and its transcript, then queue the interrupt ahead of the kept control events.

        Control events are kept: the edge resets its interrupted state on ``done``, and a handoff still holds.
        """
        Event = BaseRealtimeRunner.Event
        kept = []
        while True:
            try:
                item = self._output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item[0] not in (Event.AUDIO_DELTA, Event.TRANSCRIPT_DELTA):
                kept.append(item)
        self._queued_audio = 0
        await self._output_queue.put((Event.INTERRUPT, data))
        for item in kept:
            await self._output_queue.put(item)

    async def _pacing_loop(self) -> None:
        """Emit queued audio at playback rate; other events follow the audio queued before them.

        Every event goes through the post-hooks first. Pacing follows the audio that is actually emitted.
        """
        Event = BaseRealtimeRunner.Event
        while True:
            try:
                event_type, data = await self._output_queue.get()
                if event_type == Event.TRANSCRIPT_DELTA:
                    message_id = data.get("message_id") or ""
                    self._turn_message_id = message_id or self._turn_message_id
                    await self._emit_event(TextDelta(message_id=message_id, content=data["delta"]))
                    continue
                if event_type == Event.INPUT_TRANSCRIPT:
                    await self._emit_event(InputTranscript(message_id=data.get("message_id") or uuid.uuid4().hex, content=data["text"]))
                    continue
                if event_type != Event.AUDIO_DELTA:
                    if event_type == Event.DONE:
                        await self._emit_event(MessageEnd(message_id=self._turn_message_id or uuid.uuid4().hex))
                        self._turn_message_id = None
                        await self._emit(StreamChunk(done=True))
                    elif event_type == Event.INTERRUPT:
                        await self._emit_event(Interrupt())
                    elif event_type == Event.AGENT_CHANGED:
                        await self._emit_event(
                            AgentChanged(agent=data["agent"], previous_agent=data.get("previous_agent"), agents=data.get("agents"))
                        )
                    # A new pacing window, so a gap before the next audio is not paid back as a burst.
                    self._pace_played_ms = 0.0
                    continue

                self._queued_audio = max(0, self._queued_audio - 1)

                pcm16 = PCM16Resampler.resample(base64.b64decode(data["delta"]), self.runner.output_sample_rate, EDGE_SAMPLE_RATE)
                message_id = data.get("message_id") or ""
                self._turn_message_id = message_id or self._turn_message_id
                audio = AudioDelta(message_id=message_id, content=base64.b64encode(pcm16).decode("utf-8"))
                await self._emit_event(audio, len(pcm16))

            except asyncio.CancelledError:
                break
            except StreamHalt as halt:
                await self._fail(halt.reason)
                return
            except Exception:
                self._log.exception("Error in realtime pacing loop")

    async def _emit_event(self, event: StreamEvent, audio_bytes: int | None = None) -> list[StreamEvent]:
        """Run one output event through the post-hooks, emit each resulting event, and pace every audio event emitted.

        Pacing is applied to whatever audio leaves, whichever event released it: a hook that held audio and releases it on
        the turn end gets the same playback-speed delivery as audio passed straight through.

        :param event: The event the native session produced, at the edge's sample rate when it is audio.
        :param audio_bytes: Byte length of ``event``'s audio when it is an ``AudioDelta``, which spares a decode.
        :return: The events that were emitted (empty when a hook dropped it).
        :raises StreamHalt: When a hook ends the call; any other hook failure is logged and raised as one.
        """
        try:
            with self._hook_context():
                emitted = await self.runtime.run_stream_event_hooks(self.agent, self.session, self._last_turn, event)
        except StreamHalt:
            raise
        except Exception as e:
            self._log.exception(f"Realtime session {self.session_id}: a post-hook failed on a '{event.type}' event")
            raise StreamHalt("Realtime output hook failed") from e
        for out in emitted:
            if isinstance(out, AudioDelta) and self._pace_played_ms == 0.0:
                self._pace_start = time.time()
            await self._emit(StreamChunk(delta=out.content if isinstance(out, TextDelta) else None, event=out))
            if isinstance(out, AudioDelta):
                await self._pace(out, audio_bytes if out is event else None)
        return emitted

    async def _pace(self, audio: AudioDelta, known_bytes: int | None) -> None:
        """Wait until the audio just emitted is no more than ``playback_lead_ms`` ahead of real time."""
        size = known_bytes if known_bytes is not None else len(base64.b64decode(audio.content))
        self._pace_played_ms += (size / 2) / (EDGE_SAMPLE_RATE / 1000.0)
        elapsed_ms = (time.time() - self._pace_start) * 1000.0
        sleep_ms = (self._pace_played_ms - self._playback_lead_ms) - elapsed_ms
        if sleep_ms > 0:
            await asyncio.sleep(sleep_ms / 1000.0)

    async def _emit(self, chunk: StreamChunk) -> None:
        """Send a realtime output chunk to the output queue with the current delivery context."""
        attributes = {ATTR_REQUEST_ID: self.request_id or "unknown", ATTR_REALTIME: "true"}
        if self.user_id:
            attributes[ATTR_USER_ID] = self.user_id
        if self.integration:
            attributes[ATTR_INTEGRATION] = self.integration
        for key, value in (self.reply_context or {}).items():
            attributes[f"{REPLY_CONTEXT_PREFIX}{key}"] = value

        body = json.dumps(chunk.model_dump(exclude_none=True, mode="json"))
        message = QueueMessage(body=body, attributes=attributes, group_id=self.session_id, dedup_id=str(uuid.uuid4()))
        await asyncio.to_thread(self._transport.send, QueueName.OUTPUT, message)

    async def _fail(self, message: str) -> None:
        """Send the edge one terminal error chunk, mark the connection closed and close the runner."""
        self._log.error(f"Realtime session {self.session_id} failed: {message}")
        self.mark_closed("native session failed")
        if self._pacing_task:
            # Called from the pacing loop itself (a post-hook halted the call), cancelling would drop the chunk below.
            if self._pacing_task is not asyncio.current_task():
                self._pacing_task.cancel()
            self._pacing_task = None
        try:
            await self._emit(StreamChunk(error=message, done=True))
            # Only once the chunk is on the queue, so a failed send leaves the fallback in ``fail_to_connect`` available.
            self.failure_reported = True
        finally:
            # Called from inside the runner's listener, which cannot await its own shutdown.
            self.close_in_background(asyncio.get_running_loop())


class RealtimeConnectionPool:
    """Process-wide registry of realtime connections, one per session id, on one shared asyncio loop.

    Every consumer thread reaches a native session through the pool; the pool's own loop thread is the only
    one that talks to it. The pool decides when a call connects, when it is retried, when it ends and when it
    is evicted. See :mod:`agentkernel.realtime` for the whole call flow.

    Semantics, in order:

    1. ``initialize()`` returns the one process-wide pool, and warns once per realtime agent when the input
       guardrail is on (it checks typed text only, never caller audio). ``get_task()`` hands its loop to a ``ThreadRunner``
       task (``realtime-pool``); ``start()`` runs that loop until the process shuts down.
    2. ``dispatch()`` is the one path both realtime runners (pipeline and ECS) take, on a consumer thread, per
       input message. During shutdown the input is dropped. A message carrying ``ATTR_REALTIME_END`` ends the
       session (step 5). Otherwise it goes to the session's live connection; with none, it opens one (step 3),
       unless the session is backing off (step 4), in which case the input is dropped.
    3. Connect: ``get_or_create()`` registers a new connection under the lock, then connects it on the loop
       outside the lock, waiting up to ``CONNECT_TIMEOUT_SECONDS``. If the connect fails, times out or the
       call ended meanwhile, ``_discard_failed`` removes that connection's entry (a replacement registered
       meanwhile stays), records the failure, marks it closed and, unless the runner already did, sends the edge
       one terminal error chunk (``fail_to_connect``); the error then propagates to the caller.
    4. Failure and back-off: a connection that fails once open is marked closed. The next lookup evicts it and
       records the failure: the session's reconnect is refused for ``min(RECONNECT_MAX_SECONDS,
       RECONNECT_BASE_SECONDS * 2 ** (failures - 1))`` seconds, and input arriving meanwhile is dropped. A
       connection that had produced output restarts the count at one.
    5. ``end_session()`` closes the session's connection at once, because its edge ended. It forgets the
       session's failure record and does not block the session id: later input opens a new connection.
    6. Idle sweep: every ``SWEEP_INTERVAL_SECONDS`` the loop thread evicts and closes connections idle for more
       than ``IDLE_TIMEOUT_SECONDS``, and forgets failure records older than ``FAILURE_RECORD_TTL_SECONDS``.
    7. Shutdown: ``ThreadRunner.shutdown_event`` wakes the loop. ``start()`` then stops accepting connections,
       closes every connection (including one a consumer thread registered meanwhile), lets work still on the
       loop finish for ``SHUTDOWN_GRACE_SECONDS``, cancels the rest and closes the loop.
    """

    _log = logging.getLogger("ak.realtime.pool")

    # Connections idle for this long are evicted and closed by the sweep.
    IDLE_TIMEOUT_SECONDS = 300.0
    # How long a failure record (the back-off count) is kept after its retry time. Equal to the idle timeout today,
    # but a separate knob: a record that outlives its retry time only matters if the session reconnects within it.
    FAILURE_RECORD_TTL_SECONDS = 300.0
    # How often idle connections and stale failure records are swept.
    SWEEP_INTERVAL_SECONDS = 5.0
    # At shutdown, how long work still on the pool loop may finish before it is cancelled.
    SHUTDOWN_GRACE_SECONDS = 2.0
    # Reconnect back-off after a failed native session: BASE * 2 ** (failures - 1) seconds, capped at MAX.
    RECONNECT_BASE_SECONDS = 1.0
    RECONNECT_MAX_SECONDS = 30.0
    # How long a consumer thread waits for a new connection's native session to open. Longer than a healthy
    # connect (a websocket handshake), short enough that the input is retried while the caller still waits.
    CONNECT_TIMEOUT_SECONDS = 15.0
    # How long a consumer thread waits for the pool loop to start, when the first input arrives before it is up.
    LOOP_READY_TIMEOUT_SECONDS = 10.0

    _instance: Optional["RealtimeConnectionPool"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> Optional["RealtimeConnectionPool"]:
        """Return the process-wide pool, or None if not initialized."""
        return cls._instance

    @classmethod
    def initialize(cls) -> "RealtimeConnectionPool":
        """Return the process-wide pool, creating it on first use."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                cls._instance._warn_unchecked_audio()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Shut down the process-wide pool, closing every connection, and forget it so the next ``initialize()`` builds a new one.

        Meant for test isolation.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    def __init__(self, transport: QueueTransport | None = None, playback_lead_ms: int | None = None):
        """
        :param transport: Where every connection sends its output. Defaults to ``QueueTransportFactory.create()``.
        :param playback_lead_ms: How much audio the edge holds ahead of playback. Defaults to
            ``execution.realtime.playback_lead_ms``.
        """
        self._transport = transport or QueueTransportFactory.create()
        self._playback_lead_ms = playback_lead_ms if playback_lead_ms is not None else AKConfig.get().execution.realtime.playback_lead_ms
        self._connections: dict[str, RealtimeConnection] = {}
        # Per session: (consecutive failures, retry-at time).
        self._failures: dict[str, tuple[int, float]] = {}
        self._conn_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._stopping = threading.Event()
        # Set on the pool's loop when the process starts shutting down, so the loop wakes at once instead of polling.
        self._shutdown_wake: asyncio.Event | None = None

    def _warn_unchecked_audio(self) -> None:
        """Warn once per realtime agent when the input guardrail is on: it checks typed text only, never caller audio."""
        if not AKConfig.get().guardrail.input.enabled:
            return
        for name, agent in Runtime.current().agents().items():
            if getattr(agent, "realtime_runner_cls", None):
                self._log.warning(
                    f"Agent '{name}': guardrail.input is enabled, but on a realtime call it checks typed text only. "
                    "Caller audio reaches the model unchecked unless a pre-hook turns it into text."
                )

    # -- loop thread: start, sweep, shutdown --------------------------------------------------------------

    def get_task(self) -> ThreadRunner.Task:
        """Returns the ThreadRunner.Task that runs this pool's event loop."""
        return ThreadRunner.Task(
            execution_function=self.start,
            thread_name="realtime-pool",
            stop_all_on_failure=True,
            graceful=True,
        )

    def start(self) -> None:
        """Blocking entry point: runs the pool's event loop until shutdown."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._shutdown_wake = asyncio.Event()
        ThreadRunner.call_on_shutdown(self._wake_on_shutdown, name="realtime-pool-shutdown")
        self._loop_ready.set()
        try:
            self._loop.run_until_complete(self._wait_for_shutdown())
        finally:
            self._stopping.set()
            self._loop.run_until_complete(self._close_all())
            self._loop.run_until_complete(self._finish_remaining_tasks())
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def shutdown(self) -> None:
        """Close every connection from outside the loop thread (test isolation); the loop's own shutdown is :meth:`start`."""
        with self._conn_lock:
            self._failures.clear()
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._close_all(), self._loop)

    def _wake_on_shutdown(self) -> None:
        """Wake the pool's loop from the shutdown watcher thread."""
        loop, wake = self._loop, self._shutdown_wake
        if loop is None or wake is None:
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:
            pass  # the loop has closed: the pool already stopped

    async def _wait_for_shutdown(self) -> None:
        """Sweep every ``SWEEP_INTERVAL_SECONDS`` until the process shuts down; shutdown wakes it at once."""
        assert self._shutdown_wake is not None
        while not ThreadRunner.shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_wake.wait(), timeout=self.SWEEP_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                self._sweep(time.time())

    def _sweep(self, now: float) -> None:
        """Forget stale failure records and evict connections idle for longer than ``IDLE_TIMEOUT_SECONDS``."""
        with self._conn_lock:
            for session_id in [sid for sid, (_, retry_at) in self._failures.items() if now - retry_at >= self.FAILURE_RECORD_TTL_SECONDS]:
                del self._failures[session_id]
        # Closed and removed under one lock, so a lookup cannot count the eviction as a failure.
        idle: list[tuple[str, RealtimeConnection]] = []
        with self._conn_lock:
            for session_id, conn in list(self._connections.items()):
                if not conn.closed and (now - conn.last_activity_at) > self.IDLE_TIMEOUT_SECONDS:
                    conn.mark_closed("idle")
                    del self._connections[session_id]
                    idle.append((session_id, conn))

        for session_id, conn in idle:
            self._log.info(f"Realtime session {session_id} idle for > {self.IDLE_TIMEOUT_SECONDS}s; evicting.")
            conn.close_in_background(self._loop)

    async def _close_all(self) -> None:
        """Close every connection, including one a consumer thread registered while this ran."""
        while True:
            with self._conn_lock:
                if not self._connections:
                    return
                session_id, conn = self._connections.popitem()
            try:
                conn.mark_closed("shutdown")
                await conn.close()
            except Exception:
                self._log.exception(f"Failed to close connection for session {session_id}")

    async def _finish_remaining_tasks(self) -> None:
        """Let work still on the loop finish briefly, then cancel the rest before the loop closes."""
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=self.SHUTDOWN_GRACE_SECONDS)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    # -- consumer threads: lookup, connect, end ------------------------------------------------------------

    def get_connection(self, session_id: str) -> Optional["RealtimeConnection"]:
        """Return the session's live connection, or None; a closed one is evicted and counted as a failure."""
        stale = None
        with self._conn_lock:
            conn = self._connections.get(session_id)
            if conn is not None and conn.closed:
                del self._connections[session_id]
                self._note_failure(session_id, conn)
                stale = conn
                conn = None
        # During shutdown the pool closes every connection itself.
        if stale is not None and self._loop and not self._loop.is_closed() and not self._stopping.is_set():
            asyncio.run_coroutine_threadsafe(stale.close(), self._loop)
        return conn

    def get_or_create(
        self,
        session_id: str,
        agent: BaseAgent,
        runtime: Runtime,
        session: Session,
        *,
        request_id: str | None = None,
        user_id: str | None = None,
        integration: str | None = None,
        reply_context: dict | None = None,
    ) -> RealtimeConnection:
        """Get or create a session's connection. Thread-safe; the connect runs outside the lock.

        :param session_id: The AK session id; one connection per session id.
        :param agent: The agent the call starts with, used only when a connection is created here.
        :param runtime: The runtime the call's identity is published on, used only when a connection is created here.
        :param session: The AK session the call is bound to, used only when a connection is created here.
        :param request_id: The delivery context of a connection created here, set before it connects.
        :param user_id: See ``request_id``.
        :param integration: See ``request_id``.
        :param reply_context: See ``request_id``.
        :return: The session's open connection: the existing one, or a new one that has finished connecting.
        :raises RuntimeError: If the pool's loop is not ready in time, if the pool is shutting down, or if the new
            connection ends during startup. A connect that fails or times out re-raises its own error.
        """
        if not self._loop_ready.wait(timeout=self.LOOP_READY_TIMEOUT_SECONDS):
            raise RuntimeError("RealtimeConnectionPool event loop not ready")
        if self._stopping.is_set() or ThreadRunner.shutdown_event.is_set():
            raise RuntimeError("RealtimeConnectionPool is shutting down: no new connection is opened")

        with self._conn_lock:
            existing = self._connections.get(session_id)
            if existing is not None and not existing.closed:
                return existing
            conn = self._new_connection(session_id, agent, runtime, session)
            conn.update_delivery_context(request_id, user_id, integration, reply_context or {})
            self._connections[session_id] = conn

        future = asyncio.run_coroutine_threadsafe(conn.connect(), self._loop)
        try:
            future.result(timeout=self.CONNECT_TIMEOUT_SECONDS)
            if conn.closed:
                raise RuntimeError(f"Realtime session {session_id} ended during startup")
            return conn
        except Exception as e:
            self._discard_failed(session_id, conn, future, e)
            raise

    def _new_connection(self, session_id: str, agent: BaseAgent, runtime: Runtime, session: Session) -> RealtimeConnection:
        """Build a connection with the pool's shared transport and playback lead."""
        return RealtimeConnection(session_id, agent, runtime, session, self._loop, transport=self._transport, playback_lead_ms=self._playback_lead_ms)

    def _note_failure(self, session_id: str, conn: RealtimeConnection) -> None:
        """Record a failed connection and its retry time. The caller holds ``_conn_lock``."""
        count = 1 if conn.produced_output else self._failures.get(session_id, (0, 0.0))[0] + 1
        delay = min(self.RECONNECT_MAX_SECONDS, self.RECONNECT_BASE_SECONDS * 2 ** (count - 1))
        self._failures[session_id] = (count, time.time() + delay)
        self._log.warning(f"Realtime session {session_id}: native session failed ({count} in a row); not retrying for {delay:.0f}s")

    def _backing_off(self, session_id: str) -> bool:
        """True while a session's input is dropped after a failure."""
        with self._conn_lock:
            entry = self._failures.get(session_id)
            return entry is not None and time.time() < entry[1]

    def end_session(self, session_id: str) -> None:
        """Close a session's connection now, because its edge has ended."""
        with self._conn_lock:
            conn = self._connections.pop(session_id, None)
            self._failures.pop(session_id, None)
            if conn is not None:
                conn.mark_closed("ended by its edge")
        if conn is not None and self._loop and not self._loop.is_closed() and not self._stopping.is_set():
            future = asyncio.run_coroutine_threadsafe(conn.close(), self._loop)
            try:
                future.result(timeout=RealtimeConnection.SEND_TIMEOUT_SECONDS)
            except Exception:
                self._log.exception(f"Realtime session {session_id}: failed to close on end")
        self._log.info(f"Realtime session {session_id} ended by its edge")

    def _discard_failed(self, session_id: str, conn: RealtimeConnection, connect: "Future", error: BaseException) -> None:
        """Drop a connection whose connect failed or timed out, cancel it, and tell its edge.

        Only this connection's entry is removed; a replacement registered meanwhile stays.
        """
        with self._conn_lock:
            if self._connections.get(session_id) is not conn:
                return
            del self._connections[session_id]
            self._note_failure(session_id, conn)
        connect.cancel()
        conn.mark_closed("connect failed")
        # A runner that reported an error while connecting already sent the edge its terminal error, and is closing.
        if self._loop and not self._loop.is_closed() and not self._stopping.is_set() and not conn.failure_reported:
            asyncio.run_coroutine_threadsafe(conn.fail_to_connect(error), self._loop)

    def dispatch(
        self, body: "BaseRunRequest", request_id: str, user_id: str | None, attributes: Mapping[str, Any], chat_service: "ChatService"
    ) -> None:
        """Forward one realtime input message to its session's connection, creating it on first use.

        The one path both realtime runners (pipeline and ECS) take. Input is dropped during shutdown.

        :param body: The input message's run request; its principal becomes the connection's.
        :param request_id: The resolved request id, stamped on the output.
        :param user_id: The input's user id attribute, if any: the WebSocket routing marker the
            output is stamped with, not an identity (that is ``body.principal``).
        :param attributes: The input message's attributes, carrying the integration return address.
        :param chat_service: Resolves the agent and session when the connection is created.
        """
        if ThreadRunner.shutdown_event.is_set():
            self._log.debug(f"Shutting down: dropping realtime input for session {body.session_id}")
            return
        if attributes.get(ATTR_REALTIME_END):
            self.end_session(body.session_id)
            return

        delivery = {
            "request_id": request_id,
            "user_id": user_id,
            "integration": IntegrationDelivery.integration_of(attributes),
            "reply_context": IntegrationDelivery.reply_context(attributes),
        }
        conn = self.get_connection(body.session_id)
        if conn is None and self._backing_off(body.session_id):
            self._log.debug(f"Realtime session {body.session_id}: native session failed moments ago, dropping input until the retry time")
            return
        if conn is None:
            handler = chat_service.prepare_agent_handler(body.session_id, body.agent)
            conn = self.get_or_create(body.session_id, handler.service.agent, handler.service.runtime, handler.service.session, **delivery)

        conn.update_delivery_context(**delivery)
        conn.publish_principal(body.principal)
        for request in body.requests:
            if getattr(request, "type", None) == "voice":
                conn.append_audio(request)
            elif getattr(request, "type", None) == "text":
                conn.send_text(request)

    @staticmethod
    def send_permanent_failure(
        transport: QueueTransport, source_attributes: Mapping[str, Any], group_id: str | None, dedup_id: str | None, error: str
    ) -> None:
        """Send a terminal error chunk, marked realtime, for an input message that exhausted its retries.

        :param transport: The transport to send the output message on.
        :param source_attributes: The failed input message's attributes; user id and return address are forwarded.
        :param group_id: The session id, which is the output queue group.
        :param dedup_id: Unique id for this output message.
        :param error: The user-facing error text.
        """
        attributes = {ATTR_REALTIME: "true", ATTR_REQUEST_ID: source_attributes.get(ATTR_REQUEST_ID) or "unknown"}
        for key, value in source_attributes.items():
            if key == ATTR_USER_ID or IntegrationDelivery.is_routing_attribute(key):
                attributes[key] = value
        body = json.dumps(StreamChunk(error=error, done=True).model_dump(exclude_none=True, mode="json"))
        transport.send(QueueName.OUTPUT, QueueMessage(body=body, attributes=attributes, group_id=group_id, dedup_id=dedup_id))
