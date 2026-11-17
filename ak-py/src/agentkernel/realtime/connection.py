import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from typing import ClassVar

from ..core.base import Agent as BaseAgent
from ..core.base import Session
from ..core.event import AgentChanged, AudioDelta, InputTranscript, Interrupt, MessageEnd, StreamEvent, TextDelta
from ..core.hooks import StreamHalt
from ..core.model import AgentRequest, AgentRequestText, AgentRequestVoice, Principal, StreamChunk
from ..core.runtime import Runtime
from ..core.session.serde import BinarySerde
from ..core.tool import ToolContext
from ..pipeline.envelope import (
    ATTR_INTEGRATION,
    ATTR_REALTIME,
    ATTR_REQUEST_ID,
    ATTR_USER_ID,
    REPLY_CONTEXT_PREFIX,
    QueueMessage,
    QueueName,
)
from ..pipeline.transport.base import QueueTransport
from .audio import EDGE_SAMPLE_RATE, PCM16Resampler
from .base import RealtimeRunner as BaseRealtimeRunner


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
       post-hooks first, and the audio that leaves is emitted at playback rate. When a turn ends (``done``),
       the session is saved in the background (see "session store" below), so a call that fails later loses
       only the turn in progress.
    4. A barge-in (``interrupt``, or ``speech_started`` while paced audio is still queued) drops unheard
       audio and transcript deltas but keeps control events and ``input_transcript``.
    5. An ``error`` event, an event the contract does not list, or a post-hook that halts the call fails the
       connection: the edge gets one terminal error chunk, the state moves to ``CLOSING`` and ``close()`` runs
       in the background.
    6. ``mark_closed()`` is how the pool (or a failure) says "this connection is dead": the state moves to
       ``CLOSING`` and the pool evicts it on the next lookup. The native session is still open until
       ``close()`` runs.
    7. ``close()`` claims the connection (state ``CLOSED``), cancels a connect still in flight, stops pacing,
       then, in this order: stops input (running pre-hooks are cancelled, new input is dropped), disconnects
       the runner, stores the final session after any turn write still running (a failed call is not stored) and ends
       the run: the principal is unpublished and the volatile cache cleared (hook state ends with the call).
       A second call returns at once, so shutdown, eviction and failure can all close one connection.
       ``close_done`` is set and ``[REALTIME CALL END]`` is logged when it finishes.

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
        # An interrupt is queued and not yet emitted: audio a hook releases meanwhile is not played over it.
        self._interrupt_pending = False
        # A hook is releasing held audio: the user starting to speak is a barge-in, as with queued audio.
        self._releasing_audio = False
        # Saves the session after each finished turn and at the end; a failed call stores nothing more.
        # The call failed (a native error, a halt, a failed connect): its session is not stored again, so the last
        # finished turn is what the next call starts from.
        self._failed = False
        # The newest session write. Each write waits for the one before it, so turns land in order and the final one last.
        self._last_write: asyncio.Task | None = None
        # Input (pre-hook) tasks still running. Close stops them and refuses new ones before it disconnects and stores,
        # so no hook can change the session or send to the model after the call's session was saved.
        self._input_tasks: set[asyncio.Task] = set()
        self._input_closed = False
        # Set when close has finished. A new call for this session waits for it before it loads the session.
        self.close_done = threading.Event()
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
        try:
            with self._hook_context():
                await self.runner.connect(self.session, self.agent, self.handle_framework_event)
        finally:
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
        self._failed = True
        try:
            await self._emit(StreamChunk(error=f"Realtime session could not start: {str(error) or type(error).__name__}", done=True))
        except Exception:
            self._log.exception(f"Realtime session {self.session_id}: could not report its failed start")
        finally:
            await self.close()

    async def close(self) -> None:
        """Stop input and pacing, disconnect the runner and store the session; a second call returns at once.

        ``close_done`` is set when the whole close has finished, whatever way it ended.
        """
        # Before anything else, so input that arrives while the close is running is dropped.
        self._input_closed = True
        with self._state_lock:
            if self._state is RealtimeConnection._State.CLOSED:
                return
            self._state = RealtimeConnection._State.CLOSED
            if self._close_reason is None:
                self._close_reason = "closed"
        try:
            await self._close()
        finally:
            self.close_done.set()
            self._log.info(f"[REALTIME CALL END] session_id={self.session_id} reason={self._close_reason}")

    async def _close(self) -> None:
        """The close itself, in order: cancel a connect, stop pacing, stop input, disconnect, wait for the turn writer, store, end the run."""
        startup = self._startup_task
        if startup is not None and startup is not asyncio.current_task() and not startup.done():
            startup.cancel()
            [result] = await asyncio.gather(startup, return_exceptions=True)
            if isinstance(result, Exception):
                self._log.error(f"Realtime session {self.session_id}: startup failed while closing: {result}")
        if self._pacing_task:
            self._pacing_task.cancel()
            self._pacing_task = None
        # Before the disconnect and the store: a pre-hook that is still running must not write to the session afterwards.
        await self._stop_input()
        try:
            await self.runner.disconnect()
        finally:
            try:
                # Save the session only after the runner has disconnected, because ADK writes its own
                # data while disconnecting. Never save a call that failed.
                if self._failed:
                    self._log.debug(f"Realtime session {self.session_id}: session not stored, the call failed")
                    # A turn write still running must finish before the next call loads the session, or it could overwrite it.
                    if self._last_write is not None:
                        await asyncio.gather(self._last_write, return_exceptions=True)
                else:
                    await self._write_session(self._last_write, lambda: self.session)
            finally:
                # The call's identity and the hook state kept in the volatile cache end with the call, as when a
                # Runtime run ends, also when the native session fails to close: the session store hands the next
                # call this same Session.
                if self._principal_published:
                    self.session._unpublish_run()
                self.session.get_volatile_cache()._clear_all()

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
        """Set ``Session.current()`` and ``Agent.current()`` around a hook call or the connect, without the session lock.

        ``Runtime.run()`` holds the lock for one run; a call lasts minutes, so it would block every other run of the session.
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

        coro = self._track_input(coro)
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

    async def _track_input(self, coro) -> None:
        """Run one input coroutine so ``close`` can find it and stop it, and drop it when the call is already closing.

        :param coro: The input coroutine (``_process_audio`` or ``_process_text``).
        """
        if self._input_closed:
            coro.close()
            return
        task = asyncio.current_task()
        self._input_tasks.add(task)
        try:
            await coro
        except asyncio.CancelledError:
            # Cancelled by close: end quietly, so the thread waiting on this input is not told it failed.
            if not self._input_closed:
                raise
        finally:
            self._input_tasks.discard(task)

    async def _stop_input(self) -> None:
        """Refuse new input and cancel the input tasks that are still running, then wait for them to end."""
        self._input_closed = True
        running = [task for task in self._input_tasks if task is not asyncio.current_task()]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

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
            if self._queued_audio > 0 or self._releasing_audio:
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
        self._interrupt_pending = True
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
                        self._save_turn()
                    elif event_type == Event.INTERRUPT:
                        self._interrupt_pending = False
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
        the turn end gets the same playback-speed delivery as audio passed straight through. An interrupt that arrives
        meanwhile drops the audio not yet emitted, as it drops queued audio.

        :param event: The event the native session produced, at the edge's sample rate when it is audio.
        :param audio_bytes: Byte length of ``event``'s audio when it is an ``AudioDelta``, which spares a decode.
        :return: The events that were emitted (empty when a hook dropped it).
        :raises StreamHalt: When a hook ends the call; any other hook failure is logged and raised as one.
        """
        # A hook may change the audio in place and return the same event: its known length then no longer applies.
        content_before = event.content if isinstance(event, AudioDelta) else None
        try:
            with self._hook_context():
                emitted = await self.runtime.run_stream_event_hooks(self.agent, self.session, self._last_turn, event)
        except StreamHalt:
            raise
        except Exception as e:
            self._log.exception(f"Realtime session {self.session_id}: a post-hook failed on a '{event.type}' event")
            raise StreamHalt("Realtime output hook failed") from e
        self._releasing_audio = any(isinstance(out, AudioDelta) and out is not event for out in emitted)
        try:
            for out in emitted:
                if isinstance(out, AudioDelta):
                    if self._interrupt_pending:
                        continue
                    if self._pace_played_ms == 0.0:
                        self._pace_start = time.time()
                await self._emit(StreamChunk(delta=out.content if isinstance(out, TextDelta) else None, event=out))
                if isinstance(out, AudioDelta):
                    unchanged = out is event and out.content is content_before
                    await self._pace(out, audio_bytes if unchanged else None)
        finally:
            self._releasing_audio = False
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
        self._failed = True
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

    # -- session store: saved after each turn and at the end -------------------------------------------------

    def _save_turn(self) -> None:
        """Save the session after a finished turn, so a call that fails later loses only the turn in progress.

        The session is copied here, on the pool loop where every change to it happens (ADK or a hook cannot change it
        mid-copy), then written on a worker thread. Nothing is saved for a failed or closing call.
        """
        if self._failed or self._state is RealtimeConnection._State.CLOSED:
            return
        try:
            snapshot = {key: BinarySerde.dumps(value) for key, value in self.session.get_all(volatile=False)}
        except Exception:
            self._log.exception(f"Realtime session {self.session_id}: copying the session at the end of a turn failed")
            return
        self._last_write = asyncio.create_task(self._write_session(self._last_write, lambda: self._rebuild(snapshot)))

    def _rebuild(self, snapshot: dict[str, bytes]) -> Session:
        """Build the session a turn's copy stands for. Runs on the worker thread: nothing else holds this object."""
        session = Session(self.session.id)
        for key, payload in snapshot.items():
            session.set(key, BinarySerde.loads(payload))
        return session

    async def _write_session(self, previous: asyncio.Task | None, session_of) -> None:
        """Store a session on a worker thread, after ``previous`` (the write before it) has finished.

        Every call shares the pool loop and a store can take several network round trips, so the write never runs on
        it. A failure is logged, never raised, so the call still ends.

        :param previous: The write that must land first, or None.
        :param session_of: Returns the session to store; called on the worker thread.
        """
        if previous is not None:
            await asyncio.gather(previous, return_exceptions=True)
        try:
            await asyncio.to_thread(lambda: self.runtime.sessions().store(session_of()))
            self._log.debug(f"Realtime session {self.session_id}: session stored")
        except Exception:
            self._log.exception(f"Realtime session {self.session_id}: storing the session failed")
