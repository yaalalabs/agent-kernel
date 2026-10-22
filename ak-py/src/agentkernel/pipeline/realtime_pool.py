import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, Optional, Sequence

from ..core.base import Agent as BaseAgent
from ..core.base import Session
from ..core.config import AKConfig
from ..core.event import AgentChanged, AudioDelta, Interrupt, TextDelta
from ..core.model import StreamChunk
from ..core.realtime import EDGE_SAMPLE_RATE, PCM16Resampler, RealtimeEvent, RealtimeObserver
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
# Bound on a consumer thread's wait for a new connection's model socket to connect.
_CONNECT_TIMEOUT_SECONDS = 15.0
# Connections idle for this long are evicted and closed by the pool's background thread.
_IDLE_TIMEOUT_SECONDS = 300.0
# How often the pool's loop looks for idle and failed connections to evict.
_SWEEP_SECONDS = 5.0
# Allow pending work this long to finish before shutdown cancels it.
_SHUTDOWN_GRACE_SECONDS = 2.0
# When a connection closes, how long its realtime observers may take over the events still waiting for them.
_OBSERVER_DRAIN_SECONDS = 2.0
# Allow cancelled tools this long to clean up before disconnecting the adapter.
_TOOL_CANCEL_SECONDS = 2.0
# How often the pool's loop wakes to look for connections to evict and to measure its own lag.
_TICK_SECONDS = 0.25
# Stop treating silent output as busy after this timeout; this does not confirm response completion.
_UNFINISHED_RESPONSE_SECONDS = 15.0
# Require a brief quiet interval before sending text, since caller speech may only be paused.
_QUIET_SECONDS = 1.5
# Stop waiting for an inferred reply after this timeout; this does not confirm that a reply arrived.
_REPLY_WAIT_SECONDS = 15.0
# The pool's loop paces every call's audio; a stall this long is logged, since every call waited behind it.
_LOOP_LAG_WARNING_SECONDS = 1.0


# The connection: one live call's model socket, its paced output, its tools, its turn state and its observers


class RealtimeConnection:
    """A persistent realtime model connection for one session that emits the framework adapter's output to the queue."""

    def __init__(
        self,
        session_id: str,
        agent: BaseAgent,
        runtime: Runtime,
        session: Session,
        loop: asyncio.AbstractEventLoop,
        observers: Sequence[RealtimeObserver] = (),
    ):
        self.session_id = session_id
        self.agent = agent
        self.runtime = runtime
        self.session = session
        self.loop = loop
        # Buffer audio ahead of edge playback to absorb broker latency and jitter.
        self._playback_lead_ms = AKConfig.get().execution.realtime.playback_lead_ms

        self.request_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.integration: Optional[str] = None
        self.reply_context: dict = {}
        # Mark failed or closed sockets for eviction so later input creates a new connection.
        self.closed = False
        # Reuse one transport per connection to avoid rebuilding clients for every audio chunk.
        self._transport = QueueTransportFactory.create()
        # Audio + terminal/control events are paced here, once for every framework adapter.
        self._audio_queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        # Count audio not yet emitted so caller speech can interrupt queued playback.
        self._queued_audio = 0
        self._pacing_task: Optional[asyncio.Task] = None
        # Disconnect the adapter only once, even if shutdown and eviction both close it.
        self._disconnecting = False
        self.last_activity_at: float = time.time()
        # Track tool tasks so closing the call cancels work holding its session lock.
        self._tool_tasks: set[asyncio.Task] = set()
        # The tasks holding the session lock for tool calls the adapter's framework runs (``open_tool_scope``).
        self._scope_holders: set[asyncio.Task] = set()
        # Track busy state separately from last_activity_at, which advances even on silent audio frames.
        self._tools_in_flight = 0
        # Keep the response open until done or interruption, even if paced audio temporarily runs out.
        self._response_open = False
        self._last_model_output_at: Optional[float] = None
        self._last_model_generated_at: Optional[float] = None
        self._last_agent_change_at: Optional[float] = None
        self._last_tool_result_at: Optional[float] = None
        self._last_caller_speech_at: Optional[float] = None
        self._last_edge_text_at: Optional[float] = None
        # Track history replay on reconnect as input that may need a model reply.
        self._last_reconnect_at: Optional[float] = None
        self._caller_speaking = False
        # Block application sends during recovery so they do not interrupt the restarted response.
        self._recovering = False
        # Block application sends until adapter connection setup has returned.
        self._connected_at: Optional[float] = None
        # When application text was last sent into this connection (``send_if_quiet``): the model owes it a reply.
        self._last_post_at: Optional[float] = None
        # Deliver observer events in order on a separate task; allocate no queue without observers.
        self._observers = list(observers)
        self._observer_events: Optional[asyncio.Queue] = None
        self._observer_task: Optional[asyncio.Task] = None
        self._closed_reported = False
        # Collect the delivered speaker and transcript for agent_said events.
        self._speaker = agent.name
        self._said: list[str] = []

        if not getattr(self.agent, "realtime_runner_cls", None):
            raise ValueError(f"Agent {self.agent.name} has no realtime_runner_cls configured")

        self.adapter: "BaseRealtimeRunner" = self.agent.realtime_runner_cls()
        if self.adapter.runs_tools:
            self.adapter.use_tool_scope(self.open_tool_scope)

    @property
    def is_responding(self) -> bool:
        """Whether the model is mid-response, has output not yet emitted to the edge, or has a tool call still running; safe from any thread."""
        return self._audio_queue.qsize() > 0 or self._tools_in_flight > 0 or self._response_unfinished()

    def _response_unfinished(self) -> bool:
        generated = self._last_model_generated_at
        return self._response_open and generated is not None and time.time() - generated < _UNFINISHED_RESPONSE_SECONDS

    @property
    def last_model_output_at(self) -> Optional[float]:
        """Epoch seconds when the model's audio or transcript last left for the edge, or ``None`` before that."""
        return self._last_model_output_at

    @property
    def last_model_generated_at(self) -> Optional[float]:
        """Epoch seconds when the adapter last reported model audio or transcript, or ``None`` before that."""
        return self._last_model_generated_at

    @property
    def last_agent_change_at(self) -> Optional[float]:
        """Epoch seconds when the adapter last reported a handoff (``agent_changed``), or ``None`` before that."""
        return self._last_agent_change_at

    @property
    def last_tool_result_at(self) -> Optional[float]:
        """Epoch seconds when a tool call's result was last sent to the model, or ``None`` before that."""
        return self._last_tool_result_at

    @property
    def last_edge_text_at(self) -> Optional[float]:
        """Epoch seconds when text from the edge last reached the model, or ``None`` before that."""
        return self._last_edge_text_at

    @property
    def last_caller_speech_at(self) -> Optional[float]:
        """Epoch seconds when the caller was last heard speaking, or ``None`` before that."""
        return self._last_caller_speech_at

    @property
    def is_caller_speaking(self) -> bool:
        """Whether the caller is speaking now; known only on an adapter that reports ``speech_stopped``, always ``False`` otherwise."""
        return self._caller_speaking

    def update_delivery_context(self, request_id: Optional[str], user_id: Optional[str], integration: Optional[str], reply_context: dict) -> None:
        """Called before pushing audio to ensure callbacks route output to the right place."""
        self.request_id = request_id
        self.user_id = user_id
        self.integration = integration
        self.reply_context = reply_context

    async def connect(self) -> None:
        """Connect the framework adapter, bind its callback, start pacing its output and queue the starting agent with its team."""
        await self._audio_queue.put(("agent_changed", {"agent": self.agent.name, "agents": self.adapter.team(self.agent)}))
        await self.adapter.connect(self.session, self.agent, self.handle_framework_event)
        if self._observers:
            self._observer_events = asyncio.Queue()
            self._observer_task = asyncio.create_task(self._serve_observers())
        self._observe("connected", agent=self.agent.name)
        self._connected_at = time.time()
        self._pacing_task = asyncio.create_task(self._pacing_loop())

    async def handle_framework_event(self, event_type: str, data: dict) -> None:
        """Queue one adapter event, sending audio and control events through the paced queue in the order the model produced them."""
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
            task = self.loop.create_task(self._execute_tool_and_reply(data["call_id"], data["name"], data["arguments"]))
            self._tool_tasks.add(task)
            task.add_done_callback(self._tool_tasks.discard)
        elif event_type == "caller_transcript":
            if (data.get("text") or "").strip():
                self._observe("caller_said", text=data["text"].strip())
        elif event_type == "reconnected":
            self._observe("reconnected", agent=data.get("agent"))
        elif event_type == "error":
            await self._fail(data.get("message") or "realtime model socket error")

    async def _interrupt(self, data: dict) -> None:
        """Drop the output not yet emitted and queue the interrupt ahead of the kept control events."""
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
        """Report a dead model socket to the edge as a terminal error chunk, then mark the connection for eviction."""
        _log.error(f"Realtime session {self.session_id} failed: {message}")
        self.closed = True
        if self._pacing_task:
            self._pacing_task.cancel()
            self._pacing_task = None
        await self._emit(StreamChunk(error=message, done=True))
        self._report_closed()

    async def _pacing_loop(self) -> None:
        """Emit model audio at playback rate, keeping the transcript and control events behind the audio they belong to."""
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
                    # Reset pacing after turns and handoffs so connection delays do not cause an audio burst.
                    audio_played_ms = 0.0
                    continue

                self._queued_audio = max(0, self._queued_audio - 1)
                if audio_played_ms == 0.0:
                    item_start_time = time.time()

                # Resample model audio once here to the edge rate for every adapter.
                pcm16 = PCM16Resampler.resample(base64.b64decode(data["delta"]), self.adapter.output_sample_rate, EDGE_SAMPLE_RATE)
                message_id = data.get("message_id") or ""
                await self._emit(StreamChunk(event=AudioDelta(message_id=message_id, content=base64.b64encode(pcm16).decode("utf-8"))))
                self.adapter.audio_emitted(message_id, pcm16, data.get("content_index", 0))

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
        """Execute a tool through the adapter in a ``ToolContext``, as a cancellable task of this connection, and send the result to the model."""
        _log.info(f"Executing tool {name} for session {self.session_id}")
        self._tools_in_flight += 1
        sent = False
        try:
            # The adapter activates this context in its framework's own way, around the framework's own tool call.
            ctx = ToolContext(self.runtime, self.agent, self.session, [])
            try:
                # Give tools the session lock and current-agent context used by normal runs.
                async with self.session:
                    with self.agent._activate():
                        result_str = await self.adapter.execute_tool(name, arguments, ctx, call_id)
            except Exception as e:
                _log.exception(f"Tool execution {name} failed")
                result_str = f"Error: {e}"

            if self.closed:
                _log.info(f"Tool {name} finished after session {self.session_id} closed; its result is not sent: {result_str[:200]}")
                return
            _log.info(f"Tool {name} result: {result_str[:200]}")
            try:
                await self.adapter.send_tool_result(call_id, result_str)
            except Exception:
                _log.exception(f"Sending the result of tool {name} to session {self.session_id} failed")
                return
            sent = True
        except asyncio.CancelledError:
            _log.info(f"Tool {name} of session {self.session_id} was cancelled: the call closed")
            raise
        finally:
            if sent:
                self._last_tool_result_at = time.time()
            self._tools_in_flight -= 1

    async def open_tool_scope(self) -> ToolContext:
        """Give a native tool task AK context and a separate session-lock holder until the tool task ends."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("A tool scope is opened from the task running the tool call")
        ctx = ToolContext(self.runtime, self.agent, self.session, [])
        held, finished = asyncio.Event(), asyncio.Event()
        holder = self.loop.create_task(self._hold_tool_scope(ctx, held, finished))
        self._scope_holders.add(holder)
        holder.add_done_callback(self._scope_holders.discard)
        self._tools_in_flight += 1
        self._tool_tasks.add(task)
        task.add_done_callback(lambda done: self._close_tool_scope(done, finished, held, holder))
        waiting = self.loop.create_task(held.wait())
        try:
            await asyncio.wait({waiting, holder}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiting.cancel()
        if not held.is_set():
            # The holder ended without the lock (cancelled at shutdown): the tool cannot run in the call's scope.
            raise RuntimeError(f"The tool scope of session {self.session_id} could not be opened: its session lock holder ended")
        Session.current_session.set(self.session)
        BaseAgent.current_agent.set(self.agent)
        ctx.set()
        return ctx

    async def _hold_tool_scope(self, ctx: ToolContext, held: asyncio.Event, finished: asyncio.Event) -> None:
        """Hold the session lock, and keep ``ctx`` fetchable, until the tool call's task ends."""
        async with self.session:
            with ctx:
                held.set()
                await finished.wait()

    def _close_tool_scope(self, task: asyncio.Task, finished: asyncio.Event, held: asyncio.Event, holder: asyncio.Task) -> None:
        """The tool call's task ended: release its scope; a result it gave a call still open is a reply owed."""
        finished.set()
        if not held.is_set():
            # Ended (cancelled) while waiting for the lock: its holder must not take the lock later for nothing.
            holder.cancel()
        self._tool_tasks.discard(task)
        self._tools_in_flight -= 1
        if not task.cancelled() and not self.closed:
            self._last_tool_result_at = time.time()

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
        """Thread-safe: schedule a text send on the pool's event loop, marking ``last_edge_text_at`` when the text came from the edge."""
        self.last_activity_at = time.time()
        if from_edge:
            self._last_edge_text_at = self.last_activity_at
            self._observe_soon("edge_text", text=text)
        self._dispatch_send(self.adapter.send_text(text), "send_text")

    def _dispatch_send(self, coro, action: str) -> None:
        """Run a model-send coroutine on the pool loop, blocking a consumer thread until it finishes and observing its failure."""
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
        """Stop pacing, cancel running tool calls, disconnect the adapter and tell the observers ``disconnected``; a second call returns at once."""
        self.closed = True
        if self._disconnecting:
            return
        self._disconnecting = True
        if self._pacing_task:
            self._pacing_task.cancel()
            self._pacing_task = None
        try:
            await self._cancel_tools()
            await self.adapter.disconnect()
        finally:
            self._report_closed()
            await self._finish_observers()

    async def _cancel_tools(self) -> None:
        """Cancel the tool calls still running, and wait at most ``_TOOL_CANCEL_SECONDS`` for them to unwind."""
        current = asyncio.current_task()
        tasks = [task for task in self._tool_tasks if not task.done() and task is not current]
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        _, pending = await asyncio.wait(tasks, timeout=_TOOL_CANCEL_SECONDS)
        if pending:
            _log.warning(f"{len(pending)} tool calls of session {self.session_id} did not stop within {_TOOL_CANCEL_SECONDS}s of being cancelled")

    def _observe(self, event_type: str, **fields: Any) -> None:
        """Queue a realtime event for the observers; nothing when there are none. Call on the pool loop."""
        if self._observer_events is not None:
            self._observer_events.put_nowait(RealtimeEvent(type=event_type, session_id=self.session_id, **fields))

    def _observe_soon(self, event_type: str, **fields: Any) -> None:
        """``_observe`` from any thread: input arrives on a consumer thread, and the observer queue belongs to the pool loop."""
        if self._observer_events is None:
            return
        event = RealtimeEvent(type=event_type, session_id=self.session_id, **fields)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._observer_events.put_nowait(event)
        elif not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._observer_events.put_nowait, event)

    @property
    def is_ready(self) -> bool:
        """Whether the model socket has connected, is not closed and is not being recovered, so text sent now reaches the model at once."""
        return self._connected_at is not None and not self.closed and not self._recovering

    @property
    def last_post_at(self) -> Optional[float]:
        """Epoch seconds when application text was last sent into this connection (``send_if_quiet``), or ``None``."""
        return self._last_post_at

    def awaiting_reply(self, now: float) -> bool:
        """Infer a pending reply from input/output timestamps, bounded by _REPLY_WAIT_SECONDS."""
        output = self._last_model_generated_at
        given = (self._last_caller_speech_at, self._last_edge_text_at, self._last_tool_result_at, self._last_reconnect_at, self._last_post_at)
        return any(at is not None and (output is None or output < at) and now - at < _REPLY_WAIT_SECONDS for at in given)

    def quiet_since(self, now: float) -> Optional[float]:
        """Return the quiet stretch start, or None while unavailable, busy, speaking or awaiting an inferred reply."""
        if not self.is_ready or self.is_responding or self.is_caller_speaking or self.awaiting_reply(now):
            return None
        times = (
            self._connected_at,
            self._last_model_output_at,
            self._last_caller_speech_at,
            self._last_edge_text_at,
            self._last_tool_result_at,
            self._last_reconnect_at,
            self._last_agent_change_at,
            self._last_post_at,
        )
        return max(t for t in times if t is not None)

    async def send_if_quiet(self, text: str, quiet_since: Optional[float] = None) -> bool:
        """On the pool loop, send only in an eligible quiet stretch; return False if declined and raise on failure."""
        now = time.time()
        since = self.quiet_since(now)
        if since is None or now - since < _QUIET_SECONDS or (quiet_since is not None and since != quiet_since):
            return False
        before, self._last_post_at = self._last_post_at, now
        try:
            await self.adapter.send_text(text)
        except BaseException:
            # Failed or cancelled: the model may not have the text, so it owes it no reply.
            self._last_post_at = before
            raise
        self.last_activity_at = now
        _log.info(f"Sent into call {self.session_id}: {text[:200]}")
        return True

    @property
    def last_reconnect_at(self) -> Optional[float]:
        """Epoch seconds when the adapter last replaced a lost model socket by replaying the conversation into it, or ``None`` before that."""
        return self._last_reconnect_at

    @property
    def connected_at(self) -> Optional[float]:
        """Epoch seconds when the model socket finished connecting; ``None`` before that."""
        return self._connected_at

    @property
    def agent_has_spoken(self) -> bool:
        """Whether the agent the call is with has said anything since the call moved to it (or began), in the model's own time."""
        generated, changed = self._last_model_generated_at, self._last_agent_change_at
        return generated is not None and (changed is None or generated > changed)

    def _report_said(self, interrupted: bool = False) -> None:
        """Tell the observers what the agent speaking said since its turn began, if anything."""
        text, self._said = "".join(self._said).strip(), []
        if text:
            self._observe("agent_said", agent=self._speaker, text=text, interrupted=interrupted)

    def _report_closed(self) -> None:
        """Tell the observers, once, what the agent last said and that the call's connection is gone."""
        if self._closed_reported:
            return
        self._closed_reported = True
        self._report_said()
        self._observe("disconnected", agent=self._speaker)

    async def _serve_observers(self) -> None:
        """Give each realtime event to the observers, in order, one at a time, until ``disconnected``."""
        events = self._observer_events
        if events is None:
            return
        while True:
            event = await events.get()
            for observer in self._observers:
                try:
                    await observer.on_event(self.session, self.agent, event)
                except Exception:
                    _log.exception(f"Realtime observer {type(observer).__name__} failed on {event.type} in session {self.session_id}")
            if event.type == "disconnected":
                return

    async def _finish_observers(self) -> None:
        """Wait for the observers to take the events left (at most ``_OBSERVER_DRAIN_SECONDS``), then stop them."""
        task, self._observer_task = self._observer_task, None
        if task is None:
            return
        done, _ = await asyncio.wait({task}, timeout=_OBSERVER_DRAIN_SECONDS)
        if not done:
            _log.warning(f"Realtime observers of session {self.session_id} did not finish in {_OBSERVER_DRAIN_SECONDS}s; stopping them")
            task.cancel()
            await asyncio.wait({task})


# The pool: every call of this process, on one event loop


class RealtimeConnectionPool:
    """Process-wide registry of persistent realtime connections, one per session, multiplexed onto one shared asyncio event loop."""

    _instance: Optional["RealtimeConnectionPool"] = None
    _lock = threading.Lock()
    # Allow observer registration before pool startup; new connections capture the current list.
    _observers: list[RealtimeObserver] = []
    _observers_lock = threading.Lock()

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
    def observe(cls, observer: RealtimeObserver) -> None:
        """Have ``observer`` watch every realtime call this process connects from now on; thread-safe."""
        with cls._observers_lock:
            if observer not in cls._observers:
                cls._observers = [*cls._observers, observer]

    @classmethod
    def unobserve(cls, observer: RealtimeObserver) -> None:
        """Stop giving ``observer`` the calls connected from now on; thread-safe."""
        with cls._observers_lock:
            cls._observers = [o for o in cls._observers if o is not observer]

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
        # Reject new connections once shutdown begins.
        self._stopping = threading.Event()

    def get_task(self) -> ThreadRunner.Task:
        """Returns the ThreadRunner.Task that runs this pool's event loop."""
        return ThreadRunner.Task(
            execution_function=self.start,
            thread_name="realtime-pool",
            stop_all_on_failure=True,
            graceful=True,
        )

    def start(self) -> None:
        """Blocking entry point that runs the shared asyncio event loop on the ThreadRunner thread until shutdown."""
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
        """Remove the idle connections and those whose model socket failed, under the lock they were inspected under, and return them to be closed."""
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
                # Close idle and failed connections even when no further input arrives.
                for session_id, conn, reason in self._evict_stale(now):
                    _log.info(f"Realtime session {session_id} {reason}; evicting.")
                    self._loop.create_task(conn.close())
            before = time.monotonic()
            await asyncio.sleep(_TICK_SECONDS)
            lag = time.monotonic() - before - _TICK_SECONDS
            if lag > _LOOP_LAG_WARNING_SECONDS:
                _log.warning(f"The realtime loop was blocked for {lag:.1f} s: every call's audio, replies and tools waited behind it")

    # Reaching a session's call, for application code (see RealtimeCall)

    def close(self, session_id: str) -> bool:
        """End the session's call now, closing its model connection; thread-safe, returns whether it was open."""
        with self._conn_lock:
            conn = self._connections.pop(session_id, None)
        if conn is None:
            return False
        conn.closed = True
        if self._loop is not None and not self._loop.is_closed() and not self._stopping.is_set():
            asyncio.run_coroutine_threadsafe(conn.close(), self._loop)
        _log.info(f"Realtime session {session_id} closed by the application")
        return True

    # What RealtimeCall reads the call's state through

    def open_connection(self, session_id: str) -> Optional["RealtimeConnection"]:
        """The session's connection unless it is closed: ready, connecting or recovering."""
        with self._conn_lock:
            conn = self._connections.get(session_id)
        return conn if conn is not None and not conn.closed else None

    def live_connection(self, session_id: str) -> Optional["RealtimeConnection"]:
        """The session's connection while it is ready: its model socket connected, not closed and not recovering."""
        with self._conn_lock:
            conn = self._connections.get(session_id)
        return conn if conn is not None and conn.is_ready else None

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
        """Let work still on the loop finish briefly, then cancel it, before the loop closes."""
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=_SHUTDOWN_GRACE_SECONDS)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def get_connection(self, session_id: str) -> Optional["RealtimeConnection"]:
        """Return the session's existing connection or None, evicting one whose model socket failed; thread-safe fast path for the audio path."""
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
        """Get or create the session's realtime connection, giving a new one its delivery context before it connects; thread-safe."""
        if not self._loop_ready.wait(timeout=10):
            raise RuntimeError("RealtimeConnectionPool event loop not ready")
        if self._stopping.is_set() or ThreadRunner.shutdown_event.is_set():
            raise RuntimeError("RealtimeConnectionPool is shutting down: no new connection is opened")

        # Fast path: a live connection already exists.
        with self._conn_lock:
            existing = self._connections.get(session_id)
            if existing is not None and not existing.closed:
                return existing
            # Reserve this session before connecting so other sessions need not wait.
            conn = RealtimeConnection(session_id, agent, runtime, session, self._loop, observers=self._observers)
            conn.update_delivery_context(request_id, user_id, integration, reply_context or {})
            self._connections[session_id] = conn

        # Connect outside the global lock.
        future = None
        try:
            future = asyncio.run_coroutine_threadsafe(conn.connect(), self._loop)
            future.result(timeout=_CONNECT_TIMEOUT_SECONDS)
            return conn
        except Exception:
            # A connect that timed out still runs on the loop: stop it, and close whatever it opened, since nothing evicts it now.
            if future is not None:
                future.cancel()
            conn.closed = True
            with self._conn_lock:
                if self._connections.get(session_id) is conn:
                    del self._connections[session_id]
            if not self._loop.is_closed() and not self._stopping.is_set():
                asyncio.run_coroutine_threadsafe(conn.close(), self._loop)
            raise

    def dispatch(
        self, body: "BaseRunRequest", request_id: str, user_id: Optional[str], attributes: Mapping[str, Any], chat_service: "ChatService"
    ) -> None:
        """Forward one realtime input message's requests to its session's model connection, creating the connection on first use."""
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
        """Send a terminal error chunk to the live edge for a realtime input message that exhausted its retries."""
        attributes = {ATTR_REALTIME: "true", ATTR_REQUEST_ID: source_attributes.get(ATTR_REQUEST_ID) or "unknown"}
        for key, value in source_attributes.items():
            if key == ATTR_USER_ID or IntegrationDelivery.is_routing_attribute(key):
                attributes[key] = value
        body = json.dumps(StreamChunk(error=error, done=True).model_dump(exclude_none=True, mode="json"))
        transport.send(QueueName.OUTPUT, QueueMessage(body=body, attributes=attributes, group_id=group_id, dedup_id=dedup_id))

    def shutdown(self) -> None:
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._close_all(), self._loop)


# Application code's view of a call


class RealtimeCall:
    """Public call access; the application owns message scheduling and retry policy."""

    def __init__(self, session_id: str):
        """Bind the call to the session id the edge serves it under."""
        self.session_id = session_id

    @staticmethod
    def _pool() -> Optional[RealtimeConnectionPool]:
        return RealtimeConnectionPool.get()

    @staticmethod
    def observe(observer: RealtimeObserver) -> None:
        """Have ``observer`` watch every realtime call this process connects from now on; register it before calls begin."""
        RealtimeConnectionPool.observe(observer)

    @staticmethod
    def unobserve(observer: RealtimeObserver) -> None:
        """Stop giving ``observer`` the calls connected from now on."""
        RealtimeConnectionPool.unobserve(observer)

    def _live(self) -> Optional[RealtimeConnection]:
        """The call's connection while it is ready."""
        pool = self._pool()
        return pool.live_connection(self.session_id) if pool is not None else None

    def _open(self) -> Optional[RealtimeConnection]:
        """The call's connection unless it is closed: ready, connecting or recovering."""
        pool = self._pool()
        return pool.open_connection(self.session_id) if pool is not None else None

    @property
    def connected(self) -> bool:
        """Whether the call's model socket is connected now."""
        return self._live() is not None

    def quiet_since(self) -> Optional[float]:
        """Return the quiet-stretch epoch timestamp for send_if_quiet, or None while the call is unavailable or busy."""
        conn = self._live()
        return conn.quiet_since(time.time()) if conn is not None else None

    def quiet_for(self) -> Optional[float]:
        """Seconds since anything happened in the call while it is quiet; ``None`` while it is busy or not connected."""
        since = self.quiet_since()
        return None if since is None else time.time() - since

    @property
    def agent_has_spoken(self) -> Optional[bool]:
        """Whether the agent the call is with has said anything since it got the call; ``None`` when the call is not connected."""
        conn = self._live()
        return conn.agent_has_spoken if conn is not None else None

    @property
    def last_caller_input_at(self) -> Optional[float]:
        """Epoch seconds when the caller last spoke or text from the edge last arrived; ``None`` before that or without a call."""
        conn = self._open()
        if conn is None:
            return None
        return max((at for at in (conn.last_caller_speech_at, conn.last_edge_text_at) if at is not None), default=None)

    @property
    def last_agent_change_at(self) -> Optional[float]:
        """Epoch seconds when the call last moved to another agent, in the model's time; ``None`` before that, or without a call."""
        conn = self._open()
        return conn.last_agent_change_at if conn is not None else None

    @property
    def last_tool_result_at(self) -> Optional[float]:
        """Epoch seconds when a tool's result was last given to the model; ``None`` before that or without a call."""
        conn = self._open()
        return conn.last_tool_result_at if conn is not None else None

    async def send_if_quiet(self, text: str, *, quiet_since: Optional[float] = None) -> bool:
        """Await from any loop; send in the eligible quiet stretch or return False without queuing; send failures raise."""
        pool = self._pool()
        loop = pool._loop if pool is not None else None
        if loop is None or loop.is_closed():
            return False
        # Sending does not guarantee playback; later caller speech can still interrupt it.
        send = self._send_if_quiet(pool, text, quiet_since)
        if asyncio.get_running_loop() is loop:
            return await send
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(send, loop))

    async def _send_if_quiet(self, pool: "RealtimeConnectionPool", text: str, quiet_since: Optional[float]) -> bool:
        conn = pool.live_connection(self.session_id)
        return await conn.send_if_quiet(text, quiet_since) if conn is not None else False

    def close(self) -> bool:
        """End the call now, closing its model connection and cancelling running tool calls; returns whether it was open."""
        pool = self._pool()
        return pool.close(self.session_id) if pool is not None else False
