import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from ..core.base import Agent as BaseAgent
from ..core.base import Session
from ..core.config import AKConfig
from ..core.event import AgentChanged, AudioDelta, InputTranscript, Interrupt, TextDelta
from ..core.model import StreamChunk
from ..core.realtime import EDGE_SAMPLE_RATE, PCM16Resampler
from ..core.realtime import RealtimeRunner as BaseRealtimeRunner
from ..core.runtime import Runtime
from ..core.tool import ToolContext
from .envelope import ATTR_INTEGRATION, ATTR_REALTIME, ATTR_REALTIME_END, ATTR_REQUEST_ID, ATTR_USER_ID, REPLY_CONTEXT_PREFIX, QueueMessage, QueueName
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
# At shutdown, how long work still on the pool loop may finish before it is cancelled.
_SHUTDOWN_GRACE_SECONDS = 2.0
# Reconnect back-off after a failed native session: BASE * 2 ** (failures - 1) seconds, capped at MAX.
_RECONNECT_BASE_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


class RealtimeConnection:
    """One session's realtime connection: wraps a framework ``RealtimeRunner`` and paces its output onto the output queue."""

    _closing: ClassVar[set[asyncio.Task]] = set()

    def __init__(self, session_id: str, agent: BaseAgent, runtime: Runtime, session: Session, loop: asyncio.AbstractEventLoop):
        self.session_id = session_id
        self.agent = agent
        self.runtime = runtime
        self.session = session
        self.loop = loop
        self._playback_lead_ms = AKConfig.get().execution.realtime.playback_lead_ms

        self.request_id: str | None = None
        self.user_id: str | None = None
        self.integration: str | None = None
        self.reply_context: dict = {}
        # Failed or closed: the pool evicts it and the next input reconnects.
        self.closed = False
        # A session that produced output restarts the reconnect back-off count when it fails.
        self.produced_output = False
        self._transport = QueueTransportFactory.create()
        self._audio_queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        # Audio not yet emitted: while it is non-zero, the user starting to speak is a barge-in.
        self._queued_audio = 0
        self._pacing_task: asyncio.Task | None = None
        # Shutdown, eviction and failure can all close one connection; disconnect only once.
        self._disconnecting = False
        self.last_activity_at: float = time.time()

        if not getattr(self.agent, "realtime_runner_cls", None):
            raise ValueError(f"Agent {self.agent.name} has no realtime_runner_cls configured")

        self.adapter: "BaseRealtimeRunner" = self.agent.realtime_runner_cls()

    def update_delivery_context(self, request_id: str | None, user_id: str | None, integration: str | None, reply_context: dict) -> None:
        """Called before pushing audio to ensure callbacks route output to the right place."""
        self.request_id = request_id
        self.user_id = user_id
        self.integration = integration
        self.reply_context = reply_context

    async def connect(self) -> None:
        """Connect the adapter and start pacing; the initial speaker and team are queued ahead of any output."""
        speaker = self.adapter.initial_speaker(self.agent)
        if speaker is not None:
            await self._audio_queue.put(("agent_changed", {"agent": speaker, "agents": self.adapter.team(self.agent)}))
        # Set once here: the SDK's tool tasks are created inside connect() and inherit these contextvars.
        # The session lock is not taken; holding it for a whole call would block every other run of the session.
        tool_context = ToolContext(self.runtime, self.agent, self.session, []).set()
        session_token = Session.current_session.set(self.session)
        try:
            with self.agent._activate():
                await self.adapter.connect(self.session, self.agent, self.handle_framework_event)
        finally:
            Session.current_session.reset(session_token)
            tool_context.reset()
        if self.closed:
            # end_session() may have closed this connection while the native session was still opening:
            # close what it opened now, and leave no pacing task behind for a connection nobody reads.
            await self.adapter.disconnect()
            return
        self._pacing_task = asyncio.create_task(self._pacing_loop())

    async def handle_framework_event(self, event_type: str, data: dict) -> None:
        """Queue one adapter event behind the audio it belongs to; an unknown event fails the connection.

        ``speech_started`` is a barge-in only while paced audio is still queued.
        :param event_type: One of the event names :meth:`RealtimeRunner.connect` lists.
        :param data: The event's payload.
        """
        if self.closed:
            return
        self.last_activity_at = time.time()
        if event_type in ("audio_delta", "transcript_delta", "done"):
            self.produced_output = True
        if event_type == "audio_delta":
            self._queued_audio += 1
            await self._audio_queue.put(("audio_delta", data))
        elif event_type == "interrupt":
            await self._interrupt(data)
        elif event_type == "speech_started":
            if self._queued_audio > 0:
                await self._interrupt(data)
        elif event_type in ("done", "transcript_delta", "agent_changed", "input_transcript"):
            await self._audio_queue.put((event_type, data))
        elif event_type == "error":
            await self._fail(data.get("message") or "realtime session error")
        elif event_type == "tool_call":
            await self._fail(
                f"Realtime runner {type(self.adapter).__name__} reported a tool_call, which the realtime pool no longer runs: "
                "the framework's native session executes its own tools"
            )
        else:
            await self._fail(f"Realtime runner {type(self.adapter).__name__} reported an unknown event '{event_type}'")

    async def _interrupt(self, data: dict) -> None:
        """Drop unheard audio and its transcript, then queue the interrupt ahead of the kept control events.

        Control events are kept: the edge resets its interrupted state on ``done``, and a handoff still holds.
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
        """Send the edge one terminal error chunk, mark the connection closed and close the adapter."""
        _log.error(f"Realtime session {self.session_id} failed: {message}")
        self.closed = True
        if self._pacing_task:
            self._pacing_task.cancel()
            self._pacing_task = None
        try:
            await self._emit(StreamChunk(error=message, done=True))
        finally:
            # Called from inside the adapter's listener, which cannot await its own shutdown.
            self.close_in_background(asyncio.get_running_loop())

    async def fail_to_connect(self, error: BaseException) -> None:
        """Send the edge one terminal error chunk for a failed connect, then close what it opened.

        :param error: What the connect raised (a timeout included).
        """
        _log.error(f"Realtime session {self.session_id} could not start: {error!r}")
        try:
            await self._emit(StreamChunk(error=f"Realtime session could not start: {str(error) or type(error).__name__}", done=True))
        except Exception as e:
            _log.error(f"Realtime session {self.session_id}: could not report its failed start: {e}")
        finally:
            await self.close()

    async def _pacing_loop(self) -> None:
        """Emit queued audio at playback rate; other events follow the audio queued before them."""
        item_start_time = 0.0
        audio_played_ms = 0.0
        while True:
            try:
                event_type, data = await self._audio_queue.get()
                if event_type == "transcript_delta":
                    message_id = data.get("message_id") or ""
                    await self._emit(StreamChunk(event=TextDelta(message_id=message_id, content=data["delta"]), delta=data["delta"]))
                    continue
                if event_type == "input_transcript":
                    await self._emit(StreamChunk(event=InputTranscript(message_id=data.get("message_id") or uuid.uuid4().hex, content=data["text"])))
                    continue
                if event_type != "audio_delta":
                    if event_type == "done":
                        await self._emit(StreamChunk(done=True))
                    elif event_type == "interrupt":
                        await self._emit(StreamChunk(event=Interrupt()))
                    elif event_type == "agent_changed":
                        await self._emit(
                            StreamChunk(event=AgentChanged(agent=data["agent"], previous_agent=data.get("previous_agent"), agents=data.get("agents")))
                        )
                    # A new pacing window, so a gap before the next audio is not paid back as a burst.
                    audio_played_ms = 0.0
                    continue

                self._queued_audio = max(0, self._queued_audio - 1)
                if audio_played_ms == 0.0:
                    item_start_time = time.time()

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

    def send_text(self, text: str) -> None:
        """Thread-safe: schedule text send on the pool's event loop."""
        self.last_activity_at = time.time()
        self._dispatch_send(self.adapter.send_text(text), "send_text")

    def _dispatch_send(self, coro, action: str) -> None:
        """Run a send on the pool loop, blocking (bounded) so the input is not acked before it reached the model.

        On the pool loop itself the send is scheduled instead, and a failure is logged.
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

    def close_in_background(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule :meth:`close` on ``loop``; the task is held in ``_closing`` since the loop keeps only a weak reference."""
        task = loop.create_task(self.close())
        RealtimeConnection._closing.add(task)
        task.add_done_callback(self._close_finished)

    def _close_finished(self, task: "asyncio.Task") -> None:
        RealtimeConnection._closing.discard(task)
        if not task.cancelled() and task.exception() is not None:
            _log.error(f"Realtime session {self.session_id}: failed to close: {task.exception()}")

    async def close(self) -> None:
        """Stop pacing and disconnect the adapter; a second call returns at once."""
        self.closed = True
        if self._disconnecting:
            return
        self._disconnecting = True
        if self._pacing_task:
            self._pacing_task.cancel()
            self._pacing_task = None
        await self.adapter.disconnect()


class RealtimeConnectionPool:
    """Process-wide registry of realtime connections, one per session id.

    Runs one asyncio loop on its ThreadRunner thread; every consumer thread sends through it.
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
        # Per session: (consecutive failures, retry-at time).
        self._failures: dict[str, tuple[int, float]] = {}
        self._conn_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
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
        """Blocking entry point: runs the pool's event loop until shutdown."""
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

    async def _wait_for_shutdown(self) -> None:
        last_sweep = time.time()
        while not ThreadRunner.shutdown_event.is_set():
            now = time.time()
            if now - last_sweep > 5.0:
                last_sweep = now
                with self._conn_lock:
                    for session_id in [sid for sid, (_, retry_at) in self._failures.items() if now - retry_at >= _IDLE_TIMEOUT_SECONDS]:
                        del self._failures[session_id]
                # Closed and removed under one lock, so a lookup cannot count the eviction as a failure.
                idle: list[tuple[str, RealtimeConnection]] = []
                with self._conn_lock:
                    for session_id, conn in list(self._connections.items()):
                        if not conn.closed and (now - conn.last_activity_at) > _IDLE_TIMEOUT_SECONDS:
                            conn.closed = True
                            del self._connections[session_id]
                            idle.append((session_id, conn))

                for session_id, conn in idle:
                    _log.info(f"Realtime session {session_id} idle for > {_IDLE_TIMEOUT_SECONDS}s; evicting.")
                    conn.close_in_background(self._loop)
            await asyncio.sleep(0.5)

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
        """Let work still on the loop finish briefly, then cancel the rest before the loop closes."""
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=_SHUTDOWN_GRACE_SECONDS)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

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

        :param request_id: The delivery context of a connection created here, set before it connects.
        :param user_id: See ``request_id``.
        :param integration: See ``request_id``.
        :param reply_context: See ``request_id``.
        """
        if not self._loop_ready.wait(timeout=10):
            raise RuntimeError("RealtimeConnectionPool event loop not ready")
        if self._stopping.is_set() or ThreadRunner.shutdown_event.is_set():
            raise RuntimeError("RealtimeConnectionPool is shutting down: no new connection is opened")

        with self._conn_lock:
            existing = self._connections.get(session_id)
            if existing is not None and not existing.closed:
                return existing
            conn = RealtimeConnection(session_id, agent, runtime, session, self._loop)
            conn.update_delivery_context(request_id, user_id, integration, reply_context or {})
            self._connections[session_id] = conn

        future = asyncio.run_coroutine_threadsafe(conn.connect(), self._loop)
        try:
            future.result(timeout=15)
            return conn
        except Exception as e:
            self._discard_failed(session_id, conn, future, e)
            raise

    def _note_failure(self, session_id: str, conn: RealtimeConnection) -> None:
        """Record a failed connection and its retry time. The caller holds ``_conn_lock``."""
        count = 1 if conn.produced_output else self._failures.get(session_id, (0, 0.0))[0] + 1
        delay = min(_RECONNECT_MAX_SECONDS, _RECONNECT_BASE_SECONDS * 2 ** (count - 1))
        self._failures[session_id] = (count, time.time() + delay)
        _log.warning(f"Realtime session {session_id}: native session failed ({count} in a row); not retrying for {delay:.0f}s")

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
        if conn is not None and self._loop and not self._loop.is_closed() and not self._stopping.is_set():
            future = asyncio.run_coroutine_threadsafe(conn.close(), self._loop)
            try:
                future.result(timeout=_SEND_TIMEOUT_SECONDS)
            except Exception as e:
                _log.error(f"Realtime session {session_id}: failed to close on end: {e}")
        _log.info(f"Realtime session {session_id} ended by its edge")

    def _discard_failed(self, session_id: str, conn: RealtimeConnection, connect: "Future", error: BaseException) -> None:
        """Drop a connection whose connect failed or timed out, cancel it, and tell its edge.

        Only this connection's entry is removed; a replacement registered meanwhile stays.
        """
        with self._conn_lock:
            if self._connections.get(session_id) is conn:
                del self._connections[session_id]
            self._note_failure(session_id, conn)
        connect.cancel()
        conn.closed = True
        if self._loop and not self._loop.is_closed() and not self._stopping.is_set():
            asyncio.run_coroutine_threadsafe(conn.fail_to_connect(error), self._loop)

    def dispatch(
        self, body: "BaseRunRequest", request_id: str, user_id: str | None, attributes: Mapping[str, Any], chat_service: "ChatService"
    ) -> None:
        """Forward one realtime input message to its session's connection, creating it on first use.

        The one path both realtime runners (pipeline and ECS) take. Input is dropped during shutdown.

        :param body: The input message's run request.
        :param request_id: The resolved request id, stamped on the output.
        :param user_id: The input's user id, if any.
        :param attributes: The input message's attributes, carrying the integration return address.
        :param chat_service: Resolves the agent and session when the connection is created.
        """
        if ThreadRunner.shutdown_event.is_set():
            _log.debug(f"Shutting down: dropping realtime input for session {body.session_id}")
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
            _log.debug(f"Realtime session {body.session_id}: native session failed moments ago, dropping input until the retry time")
            return
        if conn is None:
            handler = chat_service.prepare_agent_handler(body.session_id, body.agent)
            conn = self.get_or_create(body.session_id, handler.service.agent, handler.service.runtime, handler.service.session, **delivery)

        conn.update_delivery_context(**delivery)
        for request in body.requests:
            if getattr(request, "type", None) == "voice":
                conn.append_audio(request.audio_data)
            elif getattr(request, "type", None) == "text":
                conn.send_text(request.prompt)

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

    def shutdown(self) -> None:
        with self._conn_lock:
            self._failures.clear()
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._close_all(), self._loop)
