import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Optional

from ..core.base import Agent as BaseAgent
from ..core.base import Session
from ..core.config import AKConfig
from ..core.event import AgentChanged, AudioDelta, Interrupt, TextDelta
from ..core.hooks import RealtimeEvent
from ..core.model import StreamChunk
from ..core.realtime import EDGE_SAMPLE_RATE, PCM16Resampler
from ..core.realtime import RealtimeRunner as BaseRealtimeRunner
from ..core.runtime import Runtime
from ..core.tool import ToolContext
from .envelope import ATTR_INTEGRATION, ATTR_REALTIME, ATTR_REQUEST_ID, ATTR_USER_ID, REPLY_CONTEXT_PREFIX, QueueMessage, QueueName
from .integration_delivery import IntegrationDelivery
from .thread_runner import ThreadRunner
from .transport.base import QueueTransport, QueueTransportFactory

if TYPE_CHECKING:  # typing only; the runners pass these in
    from ..core.chat_service import ChatService
    from ..core.model import BaseRunRequest

_log = logging.getLogger("ak.pipeline.realtime_pool")

# Bound on a consumer thread's wait for a model send to complete before the input is acked.
_SEND_TIMEOUT_SECONDS = 10.0
# Connections idle for this long are evicted and closed by the pool's background thread.
_IDLE_TIMEOUT_SECONDS = 300.0
# How often the pool's loop looks for idle and failed connections to evict.
_SWEEP_SECONDS = 5.0
# At shutdown, how long work still running on the pool loop (a socket close, a tool call) may
# finish before it is cancelled.
_SHUTDOWN_GRACE_SECONDS = 2.0
# When a connection closes, how long its realtime hooks may take over the events still waiting for them.
_HOOK_DRAIN_SECONDS = 2.0
# How often the pool's loop looks for a quiet moment to say what applications posted into their calls.
_POST_POLL_SECONDS = 0.25
# A response whose ``done`` never arrives stops counting as under way once the model has generated
# nothing for this long, so a lost ``done`` cannot hold a call busy for good.
_UNFINISHED_RESPONSE_SECONDS = 15.0
# The pool's loop paces every call's audio; a stall this long is logged, since every call waited behind it.
_LOOP_LAG_WARNING_SECONDS = 1.0


class RealtimeConnection:
    """A persistent realtime WebSocket connection for one session.

    Wraps a framework-specific realtime runner (e.g. ``OpenAIRealtimeRunner``) and handles
    queue emission for output events (audio deltas, tool calls, etc.).  Lives in the pipeline
    layer so the framework adapter never imports pipeline types — the adapter talks to the
    model socket and calls a callback; this class stamps queue attributes and emits.
    """

    def __init__(self, session_id: str, agent: BaseAgent, runtime: Runtime, session: Session, loop: asyncio.AbstractEventLoop):
        self.session_id = session_id
        self.agent = agent
        self.runtime = runtime
        self.session = session
        self.loop = loop
        # Audio kept ahead of playback at the edge; a higher value absorbs the per-chunk latency
        # and jitter of a store-and-forward broker.
        self._playback_lead_ms = AKConfig.get().execution.realtime.playback_lead_ms

        self.request_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.integration: Optional[str] = None
        self.reply_context: dict = {}
        # Set once the model socket has failed or been closed. The pool evicts a closed
        # connection so the next chunk reconnects instead of writing to a dead socket.
        self.closed = False
        # One transport for the connection's lifetime: a realtime turn emits tens of chunks a
        # second, and building a transport (and its client) per chunk is pure overhead.
        self._transport = QueueTransportFactory.create()
        # Audio + terminal/control events are paced here, once for every framework adapter.
        self._audio_queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        # Audio deltas in ``_audio_queue`` not yet emitted: the agent audio the user has still to
        # hear, which is what makes a user starting to speak a barge-in.
        self._queued_audio = 0
        self._pacing_task: Optional[asyncio.Task] = None
        # Set by the first close(): a failed socket (``closed``) is closed later by the pool, and
        # shutdown and eviction may both reach the same connection, so the adapter is disconnected
        # once.
        self._disconnecting = False
        self.last_activity_at: float = time.time()
        # Turn state, for code that talks into the call (possibly from another thread) to tell a
        # quiet call from a busy one; ``last_activity_at`` cannot, as every caller audio frame moves it.
        self._tools_in_flight = 0
        # From the model's first audio or transcript of a response until its ``done`` (or a barge-in):
        # the model may pause mid-answer, and its paced audio can run out before the rest arrives.
        self._response_open = False
        self._last_model_output_at: Optional[float] = None
        self._last_model_generated_at: Optional[float] = None
        self._last_agent_change_at: Optional[float] = None
        self._last_tool_result_at: Optional[float] = None
        self._last_caller_speech_at: Optional[float] = None
        self._last_edge_text_at: Optional[float] = None
        # When the adapter last replaced a lost model socket by replaying the conversation into a new one:
        # the model owes a reply to what it was seeded with.
        self._last_reconnect_at: Optional[float] = None
        self._caller_speaking = False
        # From the adapter reporting a lost model socket (``done`` with status ``reconnecting``) until it
        # reports ``reconnected`` (or fails): text sent meanwhile would wait for a socket, then interrupt the
        # recovered agent, so nothing is posted into the call.
        self._recovering = False
        # When the model socket finished connecting; ``None`` until then. Nothing is posted into a
        # connection (``RealtimeOutbox``) before it, as the adapter has no socket to send to yet.
        self._connected_at: Optional[float] = None
        # The agent's realtime hooks see the call's events one at a time, in order, on a task of
        # their own, off the audio path (``_serve_hooks``); no queue when the agent has no hooks.
        self._hook_events: Optional[asyncio.Queue] = None
        self._hook_task: Optional[asyncio.Task] = None
        self._closed_reported = False
        # The agent whose words are reaching the edge, and those words since its turn began, for the
        # hooks' ``agent_said``.
        self._speaker = agent.name
        self._said: list[str] = []

        if not getattr(self.agent, "realtime_runner_cls", None):
            raise ValueError(f"Agent {self.agent.name} has no realtime_runner_cls configured")

        self.adapter: "BaseRealtimeRunner" = self.agent.realtime_runner_cls()

    @property
    def is_responding(self) -> bool:
        """Whether the model is mid-response: a response it has started and not ended, output not yet
        emitted to the edge, or a tool call still running.

        A response is open from its first audio or transcript until the adapter reports its ``done``
        (or the caller barges in), so a pause in the middle of an answer, with the paced audio run
        out, is not taken for its end; one whose ``done`` never comes stops counting once the model
        has generated nothing for ``_UNFINISHED_RESPONSE_SECONDS``. A tool call counts until its
        result is sent, which for a handoff on ADK includes opening the next agent's socket. The
        model generating before its first output is not visible here, so code deciding the call is
        quiet also checks that the model has answered whatever it was last given
        (``last_caller_speech_at``, ``last_edge_text_at``, ``last_tool_result_at``, compared with
        ``last_model_generated_at``). Safe to read from any thread.
        """
        return self._audio_queue.qsize() > 0 or self._tools_in_flight > 0 or self._response_unfinished()

    def _response_unfinished(self) -> bool:
        generated = self._last_model_generated_at
        return self._response_open and generated is not None and time.time() - generated < _UNFINISHED_RESPONSE_SECONDS

    @property
    def last_model_output_at(self) -> Optional[float]:
        """Epoch seconds when the model's audio or transcript last left for the edge; ``None`` before that.

        Only output counts. Control events do not (an ``interrupt`` is the caller's doing, and a
        ``done`` or ``agent_changed`` follows output that already counted), and neither does a
        finished tool call: its result is input the model has still to answer, see
        :attr:`last_tool_result_at`.
        """
        return self._last_model_output_at

    @property
    def last_model_generated_at(self) -> Optional[float]:
        """Epoch seconds when the adapter last reported model audio or transcript; ``None`` before that.

        The model's own time, not the caller's: output is generated faster than it is spoken and
        paced to the edge, so this runs ahead of :attr:`last_model_output_at`. Compared with
        :attr:`last_agent_change_at` it tells whether the agent now answering has said anything
        yet, at the moment it calls a tool (a handoff, say), while its words may still be queued.
        """
        return self._last_model_generated_at

    @property
    def last_agent_change_at(self) -> Optional[float]:
        """Epoch seconds when the adapter last reported a handoff to another agent (``agent_changed``); ``None`` before that.

        In the model's own time, like :attr:`last_model_generated_at`: what is generated after it
        is the new agent's.
        """
        return self._last_agent_change_at

    @property
    def last_tool_result_at(self) -> Optional[float]:
        """Epoch seconds when a tool call's result was last sent to the model; ``None`` before that.

        A result makes the model respond, so until ``last_model_output_at`` is later than this, a
        reply is still owed. For a handoff on ADK the result seeds the next agent's socket, so this
        marks the new agent's turn to speak.
        """
        return self._last_tool_result_at

    @property
    def last_edge_text_at(self) -> Optional[float]:
        """Epoch seconds when text from the edge last reached the model; ``None`` before that.

        Text the caller typed, or a prompt the edge sends on their behalf (such as the LiveKit
        gateway's greeting when a microphone connects); not text an application sends itself with
        :meth:`send_text`. Like the caller's speech, it is input the model has still to answer
        until ``last_model_output_at`` is later.
        """
        return self._last_edge_text_at

    @property
    def last_caller_speech_at(self) -> Optional[float]:
        """Epoch seconds when the caller was last heard speaking; ``None`` before that.

        It moves when the caller starts speaking (``speech_started`` or ``interrupt``), each time the
        adapter hears them still speaking (``speech_heard``), and when they stop (``speech_stopped``),
        so a long answer keeps it current on an adapter that reports any of the last two.
        """
        return self._last_caller_speech_at

    @property
    def is_caller_speaking(self) -> bool:
        """Whether the caller is speaking now, from the start of their speech until the adapter reports it stopped.

        Known only on an adapter that reports the end of speech (``reports_speech_stopped``, such as
        OpenAI's server voice activity detection); always ``False`` on one that cannot (Gemini Live),
        where ``last_caller_speech_at`` moving shows the caller still talking. Safe to read from any thread.
        """
        return self._caller_speaking

    def update_delivery_context(self, request_id: Optional[str], user_id: Optional[str], integration: Optional[str], reply_context: dict) -> None:
        """Called before pushing audio to ensure callbacks route output to the right place."""
        self.request_id = request_id
        self.user_id = user_id
        self.integration = integration
        self.reply_context = reply_context

    async def connect(self) -> None:
        """Connect the framework adapter, bind its callback, and start pacing its output.

        The agent the conversation starts with is queued ahead of everything else, with the adapter's
        team (every agent it can hand off to), so an edge knows who is speaking before the first
        output and can show the whole team; it is told again after a reconnect, which starts the
        native conversation over at this agent.

        The agent's realtime hooks are told the call is ``connected`` before any other event of it.
        """
        await self._audio_queue.put(("agent_changed", {"agent": self.agent.name, "agents": self.adapter.team(self.agent)}))
        await self.adapter.connect(self.session, self.agent, self.handle_framework_event)
        if getattr(self.agent, "realtime_hooks", None):
            self._hook_events = asyncio.Queue()
            self._hook_task = asyncio.create_task(self._serve_hooks())
        self._observe("connected", agent=self.agent.name)
        self._connected_at = time.time()
        self._pacing_task = asyncio.create_task(self._pacing_loop())

    async def handle_framework_event(self, event_type: str, data: dict) -> None:
        """Queue one adapter event for emission.

        Audio, its transcript and the control events (``done``, ``interrupt``, ``agent_changed``)
        go through ``_audio_queue`` so the pacing loop emits them in the order the model produced
        them, at playback rate. The transcript rides with its audio rather than ahead of it: after
        a handoff the new agent's words would otherwise reach the edge while the previous agent's
        audio is still playing, and be attributed to that agent. A tool call runs on the loop. The
        adapters only report events in order — pacing is shared here for every framework.

        ``interrupt`` is a barge-in the adapter saw while the model was responding. ``speech_started``
        is the user starting to speak outside a response: the model has finished generating, but
        paced audio may still be queued here, so it is a barge-in only while that audio remains;
        otherwise it is the ordinary start of the user's turn. Either way it, and ``interrupt``, mark
        when the caller last spoke, as do ``speech_heard`` (still speaking) and ``speech_stopped``.
        Audio and transcript mark when the model last generated output, and ``agent_changed`` when
        the conversation last moved to another agent, both as the adapter reports them.
        ``caller_transcript`` goes straight to the agent's realtime hooks, as ``caller_said``.
        """
        self.last_activity_at = time.time()
        if event_type in ("interrupt", "speech_started", "speech_heard", "speech_stopped"):
            self._last_caller_speech_at = self.last_activity_at
        if event_type in ("interrupt", "speech_started"):
            self._caller_speaking = self.adapter.reports_speech_stopped
        elif event_type in ("speech_stopped", "audio_delta"):
            # The model answering also ends the caller's speech, should a stop never arrive.
            self._caller_speaking = False
        if event_type in ("audio_delta", "transcript_delta"):
            self._last_model_generated_at = self.last_activity_at
            self._response_open = True
        elif event_type == "agent_changed":
            self._last_agent_change_at = self.last_activity_at
        elif event_type in ("done", "interrupt", "speech_started"):
            # The response ended, or the caller spoke over it or after it.
            self._response_open = False
        if event_type == "done" and data.get("status") == "reconnecting":
            self._recovering = True
        elif event_type == "reconnected":
            self._recovering = False
            if data.get("seeded"):
                self._last_reconnect_at = self.last_activity_at
        elif event_type == "error":
            self._recovering = False
        if event_type == "audio_delta":
            self._queued_audio += 1
            await self._audio_queue.put(("audio_delta", data))
        elif event_type == "interrupt":
            await self._interrupt(data)
        elif event_type == "speech_started":
            if self._queued_audio > 0:
                await self._interrupt(data)
        elif event_type in ("done", "transcript_delta", "agent_changed"):
            await self._audio_queue.put((event_type, data))
        elif event_type == "tool_call":
            self.loop.create_task(self._execute_tool_and_reply(data["call_id"], data["name"], data["arguments"]))
        elif event_type == "caller_transcript":
            if (data.get("text") or "").strip():
                self._observe("caller_said", text=data["text"].strip())
        elif event_type == "reconnected":
            self._observe("reconnected", agent=data.get("agent"))
        elif event_type == "error":
            await self._fail(data.get("message") or "realtime model socket error")

    async def _interrupt(self, data: dict) -> None:
        """Drop the output not yet emitted and queue the interrupt ahead of the kept control events.

        Audio and its transcript are dropped: the user will not hear them. The control events are
        kept: a queued ``done`` still has to reach the edge, which resets its interrupted state on
        it — dropping one would leave that state set into the next turn and swallow that turn's
        transcript — and an ``agent_changed`` still holds, since a handoff is not undone by talking
        over the agent that announced it. The interrupt goes before the kept events so the edge
        sees it before the ``done`` of the turn it cuts off, and it cannot overtake audio already
        emitted.
        """
        kept = []
        while True:
            try:
                item = self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item[0] not in ("audio_delta", "transcript_delta"):
                kept.append(item)
        self._queued_audio = 0
        await self._audio_queue.put(("interrupt", data))
        for item in kept:
            await self._audio_queue.put(item)

    async def _fail(self, message: str) -> None:
        """Report a dead model socket to the edge, then mark the connection for eviction.

        A dropped socket would otherwise be written to forever with every later chunk silently
        lost, so it is surfaced as a terminal error chunk (the edge can tell the user) and
        ``closed`` is set, which makes the pool drop it and reconnect on the next message.
        """
        _log.error(f"Realtime session {self.session_id} failed: {message}")
        self.closed = True
        if self._pacing_task:
            self._pacing_task.cancel()
            self._pacing_task = None
        await self._emit(StreamChunk(error=message, done=True))
        self._report_closed()

    async def _pacing_loop(self) -> None:
        """Emit model audio at playback rate, with control events behind their own audio.

        The model generates audio faster than it is spoken, so emitting every delta immediately
        would grow the edge's playback queue without bound. This drains ``_audio_queue`` on a
        real-time schedule; the transcript and ``done``/``interrupt``/``agent_changed`` ride the
        same queue so they cannot overtake the audio they belong to (the output queue is FIFO per
        session).

        The words emitted are what the caller heard, so they are what the realtime hooks are told an
        agent said (``agent_said``), when its turn ends, it is talked over, or the call moves on.
        """
        item_start_time = 0.0
        audio_played_ms = 0.0
        while True:
            try:
                event_type, data = await self._audio_queue.get()
                if event_type in ("audio_delta", "transcript_delta"):
                    self._last_model_output_at = time.time()
                if event_type == "transcript_delta":
                    message_id = data.get("message_id") or ""
                    await self._emit(StreamChunk(event=TextDelta(message_id=message_id, content=data["delta"]), delta=data["delta"]))
                    self._said.append(data["delta"])
                    continue
                if event_type != "audio_delta":
                    if event_type == "done":
                        await self._emit(StreamChunk(done=True))
                        self._report_said()
                    elif event_type == "interrupt":
                        await self._emit(StreamChunk(event=Interrupt()))
                        self._report_said(interrupted=True)
                    elif event_type == "agent_changed":
                        await self._emit(
                            StreamChunk(event=AgentChanged(agent=data["agent"], previous_agent=data.get("previous_agent"), agents=data.get("agents")))
                        )
                        self._report_said()
                        self._speaker = data["agent"]
                        self._observe("agent_changed", agent=data["agent"])
                    # A turn ended or the speaker changed: the next audio starts a new pacing window,
                    # so a gap before it (a handoff's reconnect) is not paid back as a burst.
                    audio_played_ms = 0.0
                    continue

                self._queued_audio = max(0, self._queued_audio - 1)
                if audio_played_ms == 0.0:
                    item_start_time = time.time()

                # The model may output a different rate than the edge; convert once, here, so the
                # edge always receives EDGE_SAMPLE_RATE audio and no adapter resamples.
                pcm16 = PCM16Resampler.resample(base64.b64decode(data["delta"]), self.adapter.output_sample_rate, EDGE_SAMPLE_RATE)
                message_id = data.get("message_id") or ""
                await self._emit(StreamChunk(event=AudioDelta(message_id=message_id, content=base64.b64encode(pcm16).decode("utf-8"))))

                duration_ms = (len(pcm16) / 2) / (EDGE_SAMPLE_RATE / 1000.0)
                audio_played_ms += duration_ms

                elapsed_ms = (time.time() - item_start_time) * 1000.0
                sleep_ms = (audio_played_ms - self._playback_lead_ms) - elapsed_ms
                if sleep_ms > 0:
                    await asyncio.sleep(sleep_ms / 1000.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _log.error(f"Error in realtime pacing loop: {e}")

    async def _execute_tool_and_reply(self, call_id: str, name: str, arguments: str) -> None:
        """Execute a tool through the adapter and send the result back to the model.

        The adapter owns invocation (framework-native tool objects differ); this class owns the
        ``ToolContext`` lifecycle, so a tool function can read ``ToolContext.get()`` while it
        runs. System tools (sandbox, knowledge base, schedule, ...) are attached to the native
        agent at wrap time, so they resolve here alongside user-defined tools.

        The call counts toward ``is_responding`` until its result is sent, which then marks
        ``last_tool_result_at``: the model owes a reply to it.
        """
        _log.info(f"Executing tool {name} for session {self.session_id}")
        self._tools_in_flight += 1
        try:
            # The adapter activates this context in its framework's own way (OpenAI sets the
            # contextvar around ``on_invoke_tool``; ADK enters the cache the wrapper fetches from).
            ctx = ToolContext(self.runtime, self.agent, self.session, [])
            try:
                # Enter the same execution scopes a unary run does, so a tool that reads
                # Session.current()/Agent.current(), the volatile cache, or holds the session lock
                # sees them exactly as it would on the normal path.
                async with self.session:
                    with self.agent._activate():
                        result_str = await self.adapter.execute_tool(name, arguments, ctx, call_id)
            except Exception as e:
                _log.exception(f"Tool execution {name} failed")
                result_str = f"Error: {e}"

            _log.info(f"Tool {name} result: {result_str[:200]}")
            await self.adapter.send_tool_result(call_id, result_str)
        finally:
            self._last_tool_result_at = time.time()
            self._tools_in_flight -= 1

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

    def append_audio(self, audio_data: str) -> None:
        """Thread-safe: convert edge-rate audio to the model's input rate, then schedule the append."""
        self.last_activity_at = time.time()
        pcm16 = PCM16Resampler.resample(base64.b64decode(audio_data), EDGE_SAMPLE_RATE, self.adapter.input_sample_rate)
        converted = base64.b64encode(pcm16).decode("utf-8")
        self._dispatch_send(self.adapter.append_audio(converted), "append_audio")

    def send_text(self, text: str, *, from_edge: bool = False) -> None:
        """Thread-safe: schedule text send on the pool's event loop.

        :param text: The text to put into the conversation; the model responds to it.
        :param from_edge: The text came from the edge (the caller typed it, or the edge sent it for
            them); it then marks :attr:`last_edge_text_at`. Leave it unset for text the application
            sends itself, such as a background job reporting back.
        """
        self.last_activity_at = time.time()
        if from_edge:
            self._last_edge_text_at = self.last_activity_at
            self._observe_soon("edge_text", text=text)
        self._dispatch_send(self.adapter.send_text(text), "send_text")

    def _dispatch_send(self, coro, action: str) -> None:
        """Run a model-send coroutine on the pool loop and observe its result.

        Called from a consumer thread, this blocks until the send finishes (bounded), so the input
        message is not acked before the audio/text reached the model and a failed socket is
        reported here rather than vanishing as an unobserved future exception. When already on the
        pool loop (a direct or test call) it cannot block on itself, so the send is scheduled and
        any failure is logged by a done-callback.
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
            future.result(timeout=_SEND_TIMEOUT_SECONDS)
        except Exception as e:
            _log.error(f"Realtime session {self.session_id}: failed to {action}: {e}")

    def _log_send_failure(self, task: "asyncio.Task", action: str) -> None:
        if not task.cancelled() and task.exception() is not None:
            _log.error(f"Realtime session {self.session_id}: failed to {action}: {task.exception()}")

    async def close(self) -> None:
        """Stop pacing and disconnect the adapter; a second call returns at once.

        The realtime hooks are told the call is ``disconnected``, and given a moment
        (``_HOOK_DRAIN_SECONDS``) to finish the events still waiting for them.
        """
        self.closed = True
        if self._disconnecting:
            return
        self._disconnecting = True
        if self._pacing_task:
            self._pacing_task.cancel()
            self._pacing_task = None
        try:
            await self.adapter.disconnect()
        finally:
            self._report_closed()
            await self._finish_hooks()

    def _observe(self, event_type: str, **fields: Any) -> None:
        """Queue a realtime event for the agent's realtime hooks; nothing when it has none. Call on the pool loop."""
        if self._hook_events is not None:
            self._hook_events.put_nowait(RealtimeEvent(type=event_type, session_id=self.session_id, **fields))

    def _observe_soon(self, event_type: str, **fields: Any) -> None:
        """``_observe`` from any thread: input arrives on a consumer thread, and the hook queue belongs to the pool loop."""
        if self._hook_events is None:
            return
        event = RealtimeEvent(type=event_type, session_id=self.session_id, **fields)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._hook_events.put_nowait(event)
        elif not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._hook_events.put_nowait, event)

    @property
    def is_ready(self) -> bool:
        """Whether the model socket has connected, is not closed and is not being recovered: text sent now
        reaches the model at once."""
        return self._connected_at is not None and not self.closed and not self._recovering

    @property
    def last_reconnect_at(self) -> Optional[float]:
        """Epoch seconds when the adapter last replaced a lost model socket by replaying the conversation into a
        new one (``reconnected`` with ``seeded``); ``None`` before that. The model owes a reply to that seed, as
        it does to a tool result, until ``last_model_output_at`` is later."""
        return self._last_reconnect_at

    @property
    def connected_at(self) -> Optional[float]:
        """Epoch seconds when the model socket finished connecting; ``None`` before that."""
        return self._connected_at

    @property
    def agent_has_spoken(self) -> bool:
        """Whether the agent the call is with has said anything since the call moved to it (or began).

        In the model's own time (:attr:`last_model_generated_at` against :attr:`last_agent_change_at`), so
        it is known when the agent calls a tool, a handoff say, while its words are still being paced out.
        """
        generated, changed = self._last_model_generated_at, self._last_agent_change_at
        return generated is not None and (changed is None or generated > changed)

    def _report_said(self, interrupted: bool = False) -> None:
        """Tell the hooks what the agent speaking said since its turn began, if anything."""
        text, self._said = "".join(self._said).strip(), []
        if text:
            self._observe("agent_said", agent=self._speaker, text=text, interrupted=interrupted)

    def _report_closed(self) -> None:
        """Tell the hooks, once, what the agent last said and that the call's connection is gone."""
        if self._closed_reported:
            return
        self._closed_reported = True
        self._report_said()
        self._observe("disconnected", agent=self._speaker)

    async def _serve_hooks(self) -> None:
        """Give each realtime event to the agent's hooks, in order, one at a time, until ``disconnected``."""
        events = self._hook_events
        if events is None:
            return
        while True:
            event = await events.get()
            for hook in list(getattr(self.agent, "realtime_hooks", None) or []):
                try:
                    await hook.on_event(self.session, self.agent, event)
                except Exception:
                    _log.exception(f"Realtime hook {type(hook).__name__} failed on {event.type} in session {self.session_id}")
            if event.type == "disconnected":
                return

    async def _finish_hooks(self) -> None:
        """Wait for the hooks to take the events left (at most ``_HOOK_DRAIN_SECONDS``), then stop them."""
        task, self._hook_task = self._hook_task, None
        if task is None:
            return
        done, _ = await asyncio.wait({task}, timeout=_HOOK_DRAIN_SECONDS)
        if not done:
            _log.warning(f"Realtime hooks of session {self.session_id} did not finish in {_HOOK_DRAIN_SECONDS}s; stopping them")
            task.cancel()
            await asyncio.wait({task})


@dataclass
class _Post:
    text: str
    key: Optional[str]
    expires_at: float


class RealtimeOutbox:
    """What application code has asked to say into one session's call, said at the call's next quiet moment.

    Text sent into a call starts a model response, and on Gemini Live cuts off one being generated, so
    a post waits until nobody is talking: the model is not mid-response, the caller is not speaking,
    the model has answered what it was last given (the caller's words, text from the edge, a tool
    result, a conversation replayed into a recovered socket, the last post), and nothing has happened
    for ``QUIET_SECONDS``. An input the model never
    answers (noise, a silent turn) stops holding the call after ``REPLY_TIMEOUT_SECONDS``.

    The pool keeps one per session, not per connection, so a post made while the model socket
    reconnects, or before the caller joins, is said once a connection is quiet. A post with a ``key``
    replaces a waiting post with the same key, and ``withdraw`` drops one; a post not said within its
    ``expires_after`` is dropped. Thread-safe; posts are said by the pool's loop.
    """

    QUIET_SECONDS = 1.5
    REPLY_TIMEOUT_SECONDS = 15.0
    MAX_PENDING = 20

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._lock = threading.Lock()
        self._pending: list[_Post] = []
        self._last_post_at: Optional[float] = None
        # The connection the last post went into: a new one owes no reply to it.
        self._connection: Optional[RealtimeConnection] = None

    @property
    def empty(self) -> bool:
        with self._lock:
            return not self._pending

    def add(self, text: str, key: Optional[str], expires_after: float, now: float) -> None:
        post = _Post(text, key, now + expires_after)
        with self._lock:
            if key is not None:
                for i, waiting in enumerate(self._pending):
                    if waiting.key == key:
                        self._pending[i] = post
                        return
            if len(self._pending) >= self.MAX_PENDING:
                dropped = self._pending.pop(0)
                _log.warning(f"Too many posts waiting for session {self.session_id}; dropped the oldest: {dropped.text[:80]}")
            self._pending.append(post)

    def withdraw(self, key: str) -> bool:
        """Drop the waiting post with ``key``; returns whether there was one."""
        with self._lock:
            kept = [post for post in self._pending if post.key != key]
            withdrawn = len(kept) < len(self._pending)
            self._pending = kept
        return withdrawn

    def expire(self, now: float) -> None:
        with self._lock:
            for post in self._pending:
                if post.expires_at <= now:
                    _log.info(f"A post for session {self.session_id} expired before the call was quiet: {post.text[:80]}")
            self._pending = [post for post in self._pending if post.expires_at > now]

    def quiet_for(self, connection: RealtimeConnection, now: float) -> Optional[float]:
        """Seconds since anything happened in ``connection``'s call, or ``None`` while it is busy or owes a reply."""
        with self._lock:
            return self._quiet_for(connection, now)

    def take(self, connection: RealtimeConnection, now: float) -> Optional[str]:
        """The next post to say into ``connection`` now, removed from the outbox; ``None`` while the call is busy."""
        self.expire(now)
        with self._lock:
            if not self._pending:
                return None
            quiet = self._quiet_for(connection, now)
            if quiet is None or quiet < self.QUIET_SECONDS:
                return None
            post = self._pending.pop(0)
            self._last_post_at = now
        return post.text

    def _quiet_for(self, connection: RealtimeConnection, now: float) -> Optional[float]:
        """``quiet_for``, with the lock held: it may forget the last post, which a new connection owes nothing to."""
        self._notice(connection)
        if not connection.is_ready or connection.is_responding or connection.is_caller_speaking or self._owes_reply(connection, now):
            return None
        times = (
            connection.connected_at,
            connection.last_model_output_at,
            connection.last_caller_speech_at,
            connection.last_edge_text_at,
            connection.last_tool_result_at,
            connection.last_reconnect_at,
            self._last_post_at,
        )
        return now - max(t for t in times if t is not None)

    def _notice(self, connection: RealtimeConnection) -> None:
        if connection is not self._connection:
            self._connection = connection
            self._last_post_at = None

    def _owes_reply(self, connection: RealtimeConnection, now: float) -> bool:
        """Whether the model has still to answer something it was given, and is still being waited for.

        Answered by what the model generated after it, not by what was played after it: words generated before a
        handoff or a tool result can still be playing out after it, and are no answer to it.
        """
        output = connection.last_model_generated_at
        given = (
            connection.last_caller_speech_at,
            connection.last_edge_text_at,
            connection.last_tool_result_at,
            connection.last_reconnect_at,
            self._last_post_at,
        )
        return any(at is not None and (output is None or output < at) and now - at < self.REPLY_TIMEOUT_SECONDS for at in given)


class RealtimeConnectionPool:
    """Process-wide registry of persistent realtime WebSocket connections.

    One connection per session_id.  Any ConsumerLoop thread can look up a connection
    by session_id and send audio to it.  The pool runs a single shared asyncio event
    loop on the ThreadRunner thread it is assigned to, so all WebSocket I/O is
    multiplexed onto that loop regardless of how many consumer threads feed it.

    Follows the ConversationThreadManager singleton pattern.
    """

    _instance: Optional["RealtimeConnectionPool"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> Optional["RealtimeConnectionPool"]:
        """Return the process-wide pool, or None if not initialized."""
        return cls._instance

    @classmethod
    def initialize(cls) -> "RealtimeConnectionPool":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Test isolation."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    def __init__(self):
        self._connections: dict[str, RealtimeConnection] = {}
        self._conn_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()
        # Set once shutdown starts: no connection is created after it, since the loop it would run
        # on is about to close.
        self._stopping = threading.Event()
        # What applications asked to say into each session's call (``post_when_idle``), per session so
        # that it outlives a reconnect.
        self._outboxes: dict[str, RealtimeOutbox] = {}
        self._outbox_lock = threading.Lock()

    def get_task(self) -> ThreadRunner.Task:
        """Returns the ThreadRunner.Task that runs this pool's event loop."""
        return ThreadRunner.Task(
            execution_function=self.start,
            thread_name="realtime-pool",
            stop_all_on_failure=True,
            graceful=True,
        )

    def start(self) -> None:
        """Blocking entry point: runs the shared asyncio event loop until shutdown.

        Called as a ``ThreadRunner.Task`` execution_function, so this method blocks on
        the ThreadRunner thread for the lifetime of the pool — the same lifecycle shape
        as ``AgentRunner.start()`` and ``ResponseHandler.start()``.
        """
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        try:
            self._loop.run_until_complete(self._wait_for_shutdown())
        finally:
            self._stopping.set()
            self._loop.run_until_complete(self._close_all())
            self._loop.run_until_complete(self._finish_remaining_tasks())
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def _evict_stale(self, now: float) -> list[tuple[str, "RealtimeConnection", str]]:
        """Remove the idle connections, and those whose model socket failed; returns them, to be closed.

        Removed under the lock they were inspected under: a consumer may replace a failed connection as soon as the
        lock is released, and that replacement must not be the one closed.
        """
        evicted = []
        with self._conn_lock:
            for session_id, conn in list(self._connections.items()):
                if conn.closed:
                    reason = "its model socket failed"
                elif (now - conn.last_activity_at) > _IDLE_TIMEOUT_SECONDS:
                    reason = f"idle for > {_IDLE_TIMEOUT_SECONDS}s"
                    conn.closed = True
                else:
                    continue
                del self._connections[session_id]
                evicted.append((session_id, conn, reason))
        return evicted

    async def _wait_for_shutdown(self) -> None:
        last_sweep = time.time()
        while not ThreadRunner.shutdown_event.is_set():
            now = time.time()
            if now - last_sweep > _SWEEP_SECONDS:
                last_sweep = now
                # Idle connections, and connections whose model socket failed: a failed one is otherwise
                # released only when its session sends more input, which a caller who left never does.
                for session_id, conn, reason in self._evict_stale(now):
                    _log.info(f"Realtime session {session_id} {reason}; evicting.")
                    self._loop.create_task(conn.close())
            try:
                self._deliver_posts(now)
            except Exception:
                _log.exception("Failed to deliver posts into realtime calls")
            before = time.monotonic()
            await asyncio.sleep(_POST_POLL_SECONDS)
            lag = time.monotonic() - before - _POST_POLL_SECONDS
            if lag > _LOOP_LAG_WARNING_SECONDS:
                _log.warning(f"The realtime loop was blocked for {lag:.1f} s: every call's audio, replies and tools waited behind it")

    # Talking into a live call, for application code (see RealtimeCall)

    def post_when_idle(self, session_id: str, text: str, *, key: Optional[str] = None, expires_after: float = 600.0) -> bool:
        """Say ``text`` into the session's live call at its next quiet moment (``RealtimeOutbox``). Thread-safe.

        :param session_id: The call's session.
        :param text: What to say; the model answers it as it would the caller's words.
        :param key: A post with the same key still waiting is replaced by this one.
        :param expires_after: Seconds the post may wait for a quiet moment before it is dropped.
        :return: Whether a call is connected now. The post waits either way, for a call to connect.
        """
        with self._outbox_lock:
            outbox = self._outboxes.setdefault(session_id, RealtimeOutbox(session_id))
            outbox.add(text, key, expires_after, time.time())
        return self.is_connected(session_id)

    def withdraw(self, session_id: str, key: str) -> bool:
        """Drop the post with ``key`` still waiting for the session's call; returns whether there was one."""
        with self._outbox_lock:
            outbox = self._outboxes.get(session_id)
            return outbox.withdraw(key) if outbox is not None else False

    def close(self, session_id: str) -> bool:
        """End the session's call now: close its model connection and drop the posts still waiting for it.

        Thread-safe. The hooks are told ``disconnected``, as for an idle eviction. The session's next input
        starts a new call. Returns whether the session had a connection.
        """
        with self._conn_lock:
            conn = self._connections.pop(session_id, None)
        with self._outbox_lock:
            self._outboxes.pop(session_id, None)
        if conn is None:
            return False
        conn.closed = True
        if self._loop is not None and not self._loop.is_closed() and not self._stopping.is_set():
            asyncio.run_coroutine_threadsafe(conn.close(), self._loop)
        _log.info(f"Realtime session {session_id} closed by the application")
        return True

    def is_connected(self, session_id: str) -> bool:
        """Whether the session has a live call whose model socket is connected."""
        return self._live(session_id) is not None

    def quiet_for(self, session_id: str) -> Optional[float]:
        """Seconds since anything happened in the session's call, while nobody is talking and nothing is owed a
        reply; ``None`` while the call is busy, or when there is no live call."""
        conn = self._live(session_id)
        if conn is None:
            return None
        with self._outbox_lock:
            outbox = self._outboxes.setdefault(session_id, RealtimeOutbox(session_id))
        return outbox.quiet_for(conn, time.time())

    def agent_has_spoken(self, session_id: str) -> Optional[bool]:
        """Whether the agent the call is with has said anything since it got the call; ``None`` with no live call."""
        conn = self._live(session_id)
        return conn.agent_has_spoken if conn is not None else None

    def _live(self, session_id: str) -> Optional["RealtimeConnection"]:
        with self._conn_lock:
            conn = self._connections.get(session_id)
        return conn if conn is not None and conn.is_ready else None

    def _deliver_posts(self, now: float) -> None:
        """Say each session's next post into its call if the call is quiet; forget outboxes left with nothing to do."""
        with self._outbox_lock:
            outboxes = list(self._outboxes.values())
        for outbox in outboxes:
            conn = self._live(outbox.session_id)
            if conn is None:
                outbox.expire(now)
            else:
                text = outbox.take(conn, now)
                if text is not None:
                    _log.info(f"Posted into call {outbox.session_id}: {text[:200]}")
                    conn.send_text(text)
            with self._outbox_lock:
                if conn is None and outbox.empty and self._outboxes.get(outbox.session_id) is outbox:
                    del self._outboxes[outbox.session_id]

    async def _close_all(self) -> None:
        """Close every connection, including one a consumer thread registered while this ran."""
        while True:
            with self._conn_lock:
                if not self._connections:
                    return
                session_id, conn = self._connections.popitem()
            try:
                await conn.close()
            except Exception:
                _log.exception(f"Failed to close connection for session {session_id}")

    async def _finish_remaining_tasks(self) -> None:
        """Let work still on the loop finish briefly, then cancel it, before the loop closes.

        Closing the loop with tasks pending destroys them mid-flight (an SDK client's own close, a
        tool call), and a consumer thread waiting on a connect that never ran would block until its
        timeout. Cancelling hands that waiter an immediate error instead.
        """
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=_SHUTDOWN_GRACE_SECONDS)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def get_connection(self, session_id: str) -> Optional["RealtimeConnection"]:
        """Return the session's existing connection, or None.

        Thread-safe fast path for the hot audio path: a caller resolves the agent/session (and
        the logging that comes with it) only when this returns None and it must create one.

        A connection whose model socket has failed (``closed``) is evicted here, so returning None
        makes the caller reconnect on this message rather than write to a dead socket.
        """
        stale = None
        with self._conn_lock:
            conn = self._connections.get(session_id)
            if conn is not None and conn.closed:
                del self._connections[session_id]
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
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        integration: Optional[str] = None,
        reply_context: Optional[dict] = None,
    ) -> RealtimeConnection:
        """Get or create a persistent realtime connection for a session.

        Thread-safe.  Called from any ConsumerLoop thread.  The global lock is held only
        while checking/inserting the registry entry — the actual WebSocket connect runs
        outside the lock so one slow session cannot block every other session.

        On SQS FIFO queues, messages with the same group_id (session_id) are delivered
        to one consumer thread at a time, so concurrent creates for the same session are
        structurally prevented by the transport.

        A new connection gets its delivery context before it connects: it emits output (the agent
        it starts with, anything the adapter reports while connecting) as soon as it is connected,
        and output emitted with no context has no edge to route back to.

        :param request_id: The delivery context, as :meth:`RealtimeConnection.update_delivery_context`
            takes it; applied only to a connection created here.
        :param user_id: See ``request_id``.
        :param integration: See ``request_id``.
        :param reply_context: See ``request_id``.
        """
        if not self._loop_ready.wait(timeout=10):
            raise RuntimeError("RealtimeConnectionPool event loop not ready")
        if self._stopping.is_set() or ThreadRunner.shutdown_event.is_set():
            raise RuntimeError("RealtimeConnectionPool is shutting down: no new connection is opened")

        # Fast path: a live connection already exists.
        with self._conn_lock:
            existing = self._connections.get(session_id)
            if existing is not None and not existing.closed:
                return existing
            # Reserve the slot so a concurrent caller for a different session proceeds
            # without waiting for this session's connect.
            conn = RealtimeConnection(session_id, agent, runtime, session, self._loop)
            conn.update_delivery_context(request_id, user_id, integration, reply_context or {})
            self._connections[session_id] = conn

        # Connect outside the global lock.
        try:
            future = asyncio.run_coroutine_threadsafe(conn.connect(), self._loop)
            future.result(timeout=15)
            return conn
        except Exception:
            with self._conn_lock:
                self._connections.pop(session_id, None)
            raise

    def dispatch(
        self, body: "BaseRunRequest", request_id: str, user_id: Optional[str], attributes: Mapping[str, Any], chat_service: "ChatService"
    ) -> None:
        """Forward one realtime input message's requests to its session's model connection.

        The single path every realtime runner (the pipeline's and ECS's) takes, so they cannot drift.
        During shutdown the input is dropped: the sockets are closing, and replaying it to a new
        connection after a restart would feed the model stale audio. Otherwise the session's
        connection is reused, or created on its first message (resolving the agent and session only
        then, not per audio chunk); its delivery context is refreshed so the output routes back to
        the edge that sent this input; and each voice or text request is sent to the model.

        :param body: The input message's run request.
        :param request_id: The resolved request id, stamped on the output.
        :param user_id: The input's user id, if any.
        :param attributes: The input message's attributes, carrying the integration return address.
        :param chat_service: Resolves the agent and session when the connection is created.
        """
        if ThreadRunner.shutdown_event.is_set():
            _log.debug(f"Shutting down: dropping realtime input for session {body.session_id}")
            return

        delivery = {
            "request_id": request_id,
            "user_id": user_id,
            "integration": IntegrationDelivery.integration_of(attributes),
            "reply_context": IntegrationDelivery.reply_context(attributes),
        }
        conn = self.get_connection(body.session_id)
        if conn is None:
            handler = chat_service.prepare_agent_handler(body.session_id, body.agent)
            conn = self.get_or_create(body.session_id, handler.service.agent, handler.service.runtime, handler.service.session, **delivery)

        conn.update_delivery_context(**delivery)
        for request in body.requests:
            if getattr(request, "type", None) == "voice":
                conn.append_audio(request.audio_data)
            elif getattr(request, "type", None) == "text":
                conn.send_text(request.prompt, from_edge=True)

    @staticmethod
    def send_permanent_failure(
        transport: QueueTransport, source_attributes: Mapping[str, Any], group_id: Optional[str], dedup_id: Optional[str], error: str
    ) -> None:
        """Send a terminal error chunk for a realtime input message that exhausted its retries.

        A runner's generic failure reply carries no ``ATTR_REALTIME``, so the Response Handler would
        route it to a webhook outbound adapter, which a stateful edge does not have. Emitting the
        same marked ``StreamChunk`` shape the connections emit sends it to the live edge's
        ``deliver_chunk`` error path instead, so the room is told rather than left silent.

        :param transport: The transport to send the output message on.
        :param source_attributes: The failed input message's attributes; its user id and integration
            return address are forwarded.
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

    def shutdown(self) -> None:
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._close_all(), self._loop)


class RealtimeCall:
    """A session's live realtime call, as application code outside it sees it: a background job reporting back,
    a webhook, a timer.

    ``post_when_idle`` says something into the call at its next quiet moment, without cutting anyone off;
    ``quiet_for``, ``connected`` and ``agent_has_spoken`` tell what the call is doing. What the caller and the
    agents say is observed with a ``RealtimeHook`` (``Module.realtime_hook``). It all works in the process that
    runs the realtime pool (the Agent Runner, which is every process of the single-process topology); in any
    other process there is no call to reach, and a post is dropped with a warning.
    """

    def __init__(self, session_id: str):
        """
        :param session_id: The call's session: the session id the edge serves the call under.
        """
        self.session_id = session_id

    @property
    def connected(self) -> bool:
        """Whether the call's model socket is connected now."""
        pool = RealtimeConnectionPool.get()
        return pool is not None and pool.is_connected(self.session_id)

    def quiet_for(self) -> Optional[float]:
        """Seconds since anything happened in the call, while nobody is talking and the model owes no reply; ``None``
        while the call is busy, or when it is not connected."""
        pool = RealtimeConnectionPool.get()
        return pool.quiet_for(self.session_id) if pool is not None else None

    @property
    def agent_has_spoken(self) -> Optional[bool]:
        """Whether the agent the call is with has said anything since it got the call (or since the call began);
        ``None`` when the call is not connected. Known as soon as the model generates the words, before they are
        heard, so a handoff policy can refuse an agent that hands the call on without a word."""
        pool = RealtimeConnectionPool.get()
        return pool.agent_has_spoken(self.session_id) if pool is not None else None

    def post_when_idle(self, text: str, *, key: Optional[str] = None, expires_after: float = 600.0) -> bool:
        """Say ``text`` into the call at its next quiet moment. Thread-safe.

        Nothing is cut off: the text waits until the model is not responding, the caller is not speaking, the
        model has answered what it was last given, and the call has been quiet for a moment. It waits through a
        reconnect, and for a call that is not connected yet.

        :param text: What to say; the model answers it as it would the caller's words, so say whose it is
            (for example "[Team update] ...").
        :param key: A post with the same key still waiting is replaced: a newer progress update supersedes an older one.
        :param expires_after: Seconds the post may wait before it is dropped as out of date.
        :return: Whether the call is connected now.
        """
        pool = RealtimeConnectionPool.get()
        if pool is None:
            _log.warning(f"No realtime pool in this process: nothing posted into session {self.session_id}")
            return False
        return pool.post_when_idle(self.session_id, text, key=key, expires_after=expires_after)

    def withdraw(self, key: str) -> bool:
        """Drop the post with ``key`` if it is still waiting, such as a question that no longer applies; returns
        whether one was dropped."""
        pool = RealtimeConnectionPool.get()
        return pool.withdraw(self.session_id, key) if pool is not None else False

    def close(self) -> bool:
        """End the call now, such as when the application ends a meeting: its model connection is closed and the
        posts still waiting for it are dropped. The session's next input starts a new call. Returns whether the
        call was open."""
        pool = RealtimeConnectionPool.get()
        return pool.close(self.session_id) if pool is not None else False
