import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from typing import Optional

from ..core.base import Agent as BaseAgent
from ..core.base import Session
from ..core.event import AudioDelta, Interrupt, TextDelta
from ..core.model import StreamChunk
from ..core.realtime import EDGE_SAMPLE_RATE
from ..core.realtime import RealtimeRunner as BaseRealtimeRunner
from ..core.realtime import resample_pcm16
from ..core.runtime import Runtime
from ..core.tool import ToolContext
from .envelope import ATTR_INTEGRATION, ATTR_REALTIME, ATTR_REQUEST_ID, ATTR_USER_ID, REPLY_CONTEXT_PREFIX, QueueMessage, QueueName
from .thread_runner import ThreadRunner
from .transport.base import QueueTransportFactory

_log = logging.getLogger("ak.pipeline.realtime_pool")

# Bound on a consumer thread's wait for a model send to complete before the input is acked.
_SEND_TIMEOUT_SECONDS = 10.0


class RealtimeConnection:
    """A persistent realtime WebSocket connection for one session.

    Wraps a framework-specific realtime adapter (e.g. ``OpenAIRealtimeAdapter``) and handles
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
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._pacing_task: Optional[asyncio.Task] = None

        if not getattr(self.agent, "realtime_runner_cls", None):
            raise ValueError(f"Agent {self.agent.name} has no realtime_runner_cls configured")

        self.adapter: "BaseRealtimeRunner" = self.agent.realtime_runner_cls()

    def update_delivery_context(self, request_id: Optional[str], user_id: Optional[str], integration: Optional[str], reply_context: dict) -> None:
        """Called before pushing audio to ensure callbacks route output to the right place."""
        self.request_id = request_id
        self.user_id = user_id
        self.integration = integration
        self.reply_context = reply_context

    async def connect(self) -> None:
        """Connect the framework adapter, bind its callback, and start pacing its output."""
        await self.adapter.connect(self.session, self.agent, self.handle_framework_event)
        self._pacing_task = asyncio.create_task(self._pacing_loop())

    async def handle_framework_event(self, event_type: str, data: dict) -> None:
        """Queue one adapter event for emission.

        Audio deltas and the terminal/control events (``done``, ``interrupt``) go through
        ``_audio_queue`` so the pacing loop emits them in order at playback rate. The transcript
        streams immediately; a tool call runs on the loop. The adapters only report events in
        order — pacing is shared here for every framework.
        """
        if event_type == "audio_delta":
            self._audio_queue.put_nowait(("audio_delta", data))
        elif event_type == "interrupt":
            # Drop audio not yet emitted, then queue the interrupt behind it so it cannot
            # overtake audio already in flight to the edge.
            while not self._audio_queue.empty():
                self._audio_queue.get_nowait()
            self._audio_queue.put_nowait(("interrupt", data))
        elif event_type == "done":
            self._audio_queue.put_nowait(("done", data))
        elif event_type == "transcript_delta":
            message_id = data.get("message_id") or ""
            await self._emit(StreamChunk(event=TextDelta(message_id=message_id, content=data["delta"]), delta=data["delta"]))
        elif event_type == "tool_call":
            self.loop.create_task(self._execute_tool_and_reply(data["call_id"], data["name"], data["arguments"]))
        elif event_type == "error":
            await self._fail(data.get("message") or "realtime model socket error")

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

    async def _pacing_loop(self) -> None:
        """Emit model audio at playback rate, with control events behind their own audio.

        The model generates audio faster than it is spoken, so emitting every delta immediately
        would grow the edge's playback queue without bound. This drains ``_audio_queue`` on a
        real-time schedule; ``done``/``interrupt`` ride the same queue so they cannot overtake the
        audio they belong to (the output queue is FIFO per session).
        """
        item_start_time = 0.0
        audio_played_ms = 0.0
        while True:
            try:
                event_type, data = await self._audio_queue.get()
                if event_type != "audio_delta":
                    if event_type == "done":
                        await self._emit(StreamChunk(done=True))
                    elif event_type == "interrupt":
                        await self._emit(StreamChunk(event=Interrupt()))
                    if event_type in ("done", "interrupt"):
                        audio_played_ms = 0.0
                    continue

                if audio_played_ms == 0.0:
                    item_start_time = time.time()

                # The model may output a different rate than the edge; convert once, here, so the
                # edge always receives EDGE_SAMPLE_RATE audio and no adapter resamples.
                pcm16 = resample_pcm16(base64.b64decode(data["delta"]), self.adapter.output_sample_rate, EDGE_SAMPLE_RATE)
                message_id = data.get("message_id") or ""
                await self._emit(StreamChunk(event=AudioDelta(message_id=message_id, content=base64.b64encode(pcm16).decode("utf-8"))))

                duration_ms = (len(pcm16) / 2) / (EDGE_SAMPLE_RATE / 1000.0)
                audio_played_ms += duration_ms

                elapsed_ms = (time.time() - item_start_time) * 1000.0
                sleep_ms = (audio_played_ms - 50.0) - elapsed_ms
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
        """
        _log.info(f"Executing tool {name} for session {self.session_id}")
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
        pcm16 = resample_pcm16(base64.b64decode(audio_data), EDGE_SAMPLE_RATE, self.adapter.input_sample_rate)
        converted = base64.b64encode(pcm16).decode("utf-8")
        self._dispatch_send(self.adapter.append_audio(converted), "append_audio")

    def send_text(self, text: str) -> None:
        """Thread-safe: schedule text send on the pool's event loop."""
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
        self.closed = True
        if self._pacing_task:
            self._pacing_task.cancel()
            self._pacing_task = None
        await self.adapter.disconnect()


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
                cls._instance._start_background_thread()
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
        self._thread: Optional[threading.Thread] = None

    def _start_background_thread(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self.start, daemon=True, name="realtime-pool")
            self._thread.start()

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
            self._loop.run_until_complete(self._close_all())
            self._loop.close()

    async def _wait_for_shutdown(self) -> None:
        while not ThreadRunner.shutdown_event.is_set():
            await asyncio.sleep(0.5)

    async def _close_all(self) -> None:
        for session_id, conn in list(self._connections.items()):
            try:
                await conn.close()
            except Exception:
                _log.exception(f"Failed to close connection for session {session_id}")
        self._connections.clear()

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
        if stale is not None and self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(stale.close(), self._loop)
        return conn

    def get_or_create(self, session_id: str, agent: BaseAgent, runtime: Runtime, session: Session) -> RealtimeConnection:
        """Get or create a persistent realtime connection for a session.

        Thread-safe.  Called from any ConsumerLoop thread.  The global lock is held only
        while checking/inserting the registry entry — the actual WebSocket connect runs
        outside the lock so one slow session cannot block every other session.

        On SQS FIFO queues, messages with the same group_id (session_id) are delivered
        to one consumer thread at a time, so concurrent creates for the same session are
        structurally prevented by the transport.
        """
        if not self._loop_ready.wait(timeout=10):
            raise RuntimeError("RealtimeConnectionPool event loop not ready")

        # Fast path: a live connection already exists.
        with self._conn_lock:
            existing = self._connections.get(session_id)
            if existing is not None and not existing.closed:
                return existing
            # Reserve the slot so a concurrent caller for a different session proceeds
            # without waiting for this session's connect.
            conn = RealtimeConnection(session_id, agent, runtime, session, self._loop)
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

    def shutdown(self) -> None:
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._close_all(), self._loop)
