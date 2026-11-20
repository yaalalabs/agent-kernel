import asyncio
import json
import logging
import threading
import time
from collections.abc import Mapping
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, Optional

from ..core.base import Agent as BaseAgent
from ..core.base import Session
from ..core.config import AKConfig
from ..core.model import StreamChunk
from ..core.runtime import Runtime
from ..pipeline.envelope import (
    ATTR_REALTIME,
    ATTR_REALTIME_END,
    ATTR_REQUEST_ID,
    ATTR_USER_ID,
    QueueMessage,
    QueueName,
)
from ..pipeline.integration_delivery import IntegrationDelivery
from ..pipeline.thread_runner import ThreadRunner
from ..pipeline.transport.base import QueueTransport, QueueTransportFactory
from .connection import RealtimeConnection

if TYPE_CHECKING:  # typing only; the runners pass these in
    from ..core.chat_service import ChatService
    from ..core.model import BaseRunRequest


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
       session's failure record and does not block the session id: later input opens a new connection. A
       connection taken out of the pool (by eviction, failure or end) stays in ``_closing`` until its close has
       finished, and a new call for the session waits for it (``_wait_for_close``, bounded by
       ``CLOSE_WAIT_SECONDS``) before it loads the session.
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
    # How long a new call for a session waits for that session's previous close to finish before it goes on without it.
    # Long enough for a slow store write and a disconnect, short enough that a stuck close does not hold the caller.
    CLOSE_WAIT_SECONDS = 15.0
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
        # Per session: the connection that was taken out of the pool and is still closing. A new call waits for it.
        self._closing: dict[str, RealtimeConnection] = {}
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
        """Forget stale failure records and finished closes, and evict connections idle for longer than ``IDLE_TIMEOUT_SECONDS``."""
        with self._conn_lock:
            for session_id in [sid for sid, (_, retry_at) in self._failures.items() if now - retry_at >= self.FAILURE_RECORD_TTL_SECONDS]:
                del self._failures[session_id]
            # A finished close needs no waiting: a session that never reconnects must not keep its connection for good.
            for session_id in [sid for sid, conn in self._closing.items() if conn.close_done.is_set()]:
                del self._closing[session_id]
        # Closed and removed under one lock, so a lookup cannot count the eviction as a failure.
        idle: list[tuple[str, RealtimeConnection]] = []
        with self._conn_lock:
            for session_id, conn in list(self._connections.items()):
                if not conn.closed and (now - conn.last_activity_at) > self.IDLE_TIMEOUT_SECONDS:
                    conn.mark_closed("idle")
                    del self._connections[session_id]
                    self._closing[session_id] = conn
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
                self._closing[session_id] = conn
                stale = conn
                conn = None
        # During shutdown the pool closes every connection itself.
        if stale is not None and self._loop and not self._loop.is_closed() and not self._stopping.is_set():
            asyncio.run_coroutine_threadsafe(stale.close(), self._loop)
        return conn

    def _wait_for_close(self, session_id: str) -> None:
        """Wait (bounded) until the session's previous connection has finished closing.

        A connection that is still closing has not stored the session or cleared its run state yet. A new call that
        loaded the session or published its principal now would read old data, and the old close would then wipe
        the new call's principal and cache.

        :param session_id: The session a new call is about to start for.
        """
        with self._conn_lock:
            closing = self._closing.get(session_id)
        if closing is None or self._stopping.is_set():
            return
        if not closing.close_done.wait(self.CLOSE_WAIT_SECONDS):
            self._log.warning(
                f"Realtime session {session_id}: the previous call is still closing after {self.CLOSE_WAIT_SECONDS:.0f}s; starting anyway"
            )
        with self._conn_lock:
            if self._closing.get(session_id) is closing:
                del self._closing[session_id]

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
                self._closing[session_id] = conn
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
            # Before the load: the session the previous call stored must be the one this call starts from.
            self._wait_for_close(body.session_id)
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
