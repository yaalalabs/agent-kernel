import asyncio
import json
import logging
import threading
import uuid
from typing import TYPE_CHECKING, Optional

from ..core.base import Agent as BaseAgent
from ..core.base import Session
from ..core.event import AudioDelta, Interrupt, TextDelta
from ..core.model import StreamChunk
from ..core.runtime import Runtime
from ..core.tool import ToolContext
from .envelope import ATTR_INTEGRATION, ATTR_REALTIME, ATTR_REQUEST_ID, ATTR_USER_ID, REPLY_CONTEXT_PREFIX, QueueMessage, QueueName
from .thread_runner import ThreadRunner
from .transport.base import QueueTransportFactory

if TYPE_CHECKING:
    from ..core.base import RealtimeRunner as BaseRealtimeRunner

_log = logging.getLogger("ak.pipeline.realtime_pool")


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
        # One transport for the connection's lifetime: a realtime turn emits tens of chunks a
        # second, and building a transport (and its client) per chunk is pure overhead.
        self._transport = QueueTransportFactory.create()

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
        """Connect the framework adapter and bind its event callback."""
        await self.adapter.connect(self.session, self.agent, self.handle_framework_event)

    async def handle_framework_event(self, event_type: str, data: dict) -> None:
        """Translate one adapter event into a typed ``StreamChunk`` and emit it.

        The same chunk contract the text streaming path uses: audio is an ``AudioDelta``
        event, the transcript streams as ``TextDelta``, barge-in is an ``Interrupt`` event,
        and the turn ends with a ``done`` chunk.
        """
        if event_type == "audio_delta":
            message_id = data.get("message_id") or ""
            await self._emit(StreamChunk(event=AudioDelta(message_id=message_id, content=data["delta"])))
        elif event_type == "transcript_delta":
            message_id = data.get("message_id") or ""
            await self._emit(StreamChunk(event=TextDelta(message_id=message_id, content=data["delta"]), delta=data["delta"]))
        elif event_type == "interrupt":
            await self._emit(StreamChunk(event=Interrupt()))
        elif event_type == "done":
            await self._emit(StreamChunk(done=True))
        elif event_type == "tool_call":
            self.loop.create_task(self._execute_tool_and_reply(data["call_id"], data["name"], data["arguments"]))

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
        """Thread-safe: schedule audio append on the pool's event loop."""
        asyncio.run_coroutine_threadsafe(self.adapter.append_audio(audio_data), self.loop)

    def send_text(self, text: str) -> None:
        """Thread-safe: schedule text send on the pool's event loop."""
        asyncio.run_coroutine_threadsafe(self.adapter.send_text(text), self.loop)

    async def close(self) -> None:
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
        """
        with self._conn_lock:
            return self._connections.get(session_id)

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

        # Fast path: connection already exists.
        with self._conn_lock:
            existing = self._connections.get(session_id)
            if existing is not None:
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
