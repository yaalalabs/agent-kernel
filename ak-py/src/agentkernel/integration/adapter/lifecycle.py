import asyncio
import logging
import threading

from fastapi import APIRouter, Request

from ...api.handler import RESTRequestHandler
from ...core.util.async_bridge import run_async_sync
from ...pipeline.thread_runner import ThreadRunner
from .base import EdgeLifecycleAdapter, Source, StatefulEdgeAdapter
from .registry import StatefulEdgeRegistry


class _EdgeRunner:
    """Runs one :class:`StatefulEdgeAdapter` for the life of its connection, on the calling thread.

    The per-edge half of :class:`EdgeLifecycleRESTRequestHandler`, which starts one per lifecycle event. Must run in the
    same process as the Response Handler, which routes replies to the registered adapter.
    """

    _log = logging.getLogger("ak.integration.edge_lifecycle")
    GRACEFUL_STOP_TIMEOUT_SECONDS: float = 10.0
    """Bound on the adapter's own teardown before it is force-cancelled."""

    def __init__(self, adapter: StatefulEdgeAdapter):
        """
        :param adapter: The gateway adapter to host.
        :raises ValueError: If the adapter's ``source`` is not ``Source.REALTIME``.
        """
        if adapter.source is not Source.REALTIME:
            raise ValueError(
                f"{type(adapter).__name__} is a {adapter.source} adapter: host it with WebhookRESTRequestHandler or PollerRunner, not EdgeLifecycleRESTRequestHandler"
            )
        self._adapter = adapter
        self._stop_requested = threading.Event()

    @property
    def adapter(self) -> StatefulEdgeAdapter:
        """The hosted adapter."""
        return self._adapter

    def stop(self) -> None:
        """Ask this edge to stop, as process shutdown would; ``start()`` then returns. Safe from any thread."""
        self._stop_requested.set()

    def start(self) -> None:
        """Register the adapter by its ``session_id``, then run the gateway's blocking loop."""
        session_id = getattr(self._adapter, "session_id", None)
        StatefulEdgeRegistry.register(self._adapter, session_id=session_id)
        try:
            run_async_sync(self._run_until_shutdown())
        finally:
            if session_id:
                StatefulEdgeRegistry.unregister(session_id, self._adapter)

    async def _run_until_shutdown(self) -> None:
        # Stopped before it started (a connection that ended at once): an adapter cannot stop what it has not begun.
        if ThreadRunner.shutdown_event.is_set() or self._stop_requested.is_set():
            self._log.info(f"Edge {self._adapter.name} stopped before it started")
            return

        task = asyncio.create_task(self._adapter.start())

        while not (ThreadRunner.shutdown_event.is_set() or self._stop_requested.is_set()):
            if task.done():
                task.result()  # raise if exception occurred
                return
            await asyncio.sleep(0.5)

        self._log.info(f"Edge {self._adapter.name} stopping")

        try:
            await self._adapter.stop()
        except Exception:
            self._log.exception(f"Error calling stop() on Edge {self._adapter.name}")

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.GRACEFUL_STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._log.warning(f"Edge {self._adapter.name} did not stop within {self.GRACEFUL_STOP_TIMEOUT_SECONDS}s; cancelling")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class EdgeLifecycleRESTRequestHandler(RESTRequestHandler):
    """Hosts an :class:`EdgeLifecycleAdapter`: one stateful edge per live connection, started and ended at runtime.

    The sibling of ``WebhookRESTRequestHandler``: it mounts the adapter's webhook route, and for each lifecycle event
    runs the edge for the session on a thread of its own (:class:`_EdgeRunner`), or stops it. Gateways must run in the
    process that hosts the Response Handler, so it is mounted inside a pipeline topology. At process shutdown it starts
    no new edges; each live edge sees the shutdown itself and stops::

        IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])
    """

    requires_pipeline = True

    _log = logging.getLogger("ak.integration.edge_lifecycle")

    def __init__(self, adapter: EdgeLifecycleAdapter):
        """
        :param adapter: The platform's lifecycle adapter.
        :raises ValueError: If the adapter declares no webhook route.
        """
        if not adapter.webhook_path:
            raise ValueError(f"{type(adapter).__name__} must declare a webhook_path for its platform's lifecycle webhooks")
        self._adapter = adapter
        self._runners: dict[str, tuple[_EdgeRunner, threading.Thread]] = {}
        self._lock = threading.Lock()

    @property
    def adapter(self) -> EdgeLifecycleAdapter:
        """The hosted adapter."""
        return self._adapter

    def get_router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route(self._adapter.webhook_path, self.handle, methods=["POST"])
        return router

    async def handle(self, request: Request) -> dict:
        """Parse one lifecycle webhook, then start or stop the session's edge.

        :raises HTTPException: Raised by the adapter for a delivery that must be rejected.
        """
        event = await self._adapter.parse(request)
        if event is None:
            self._log.debug(f"Ignored delivery: integration={self._adapter.name}")
        elif event.start:
            if self._adapter.should_start(event.session_id):
                self._start(event.session_id)
        else:
            self._stop(event.session_id)
        return {"status": "ok"}

    def _start(self, session_id: str) -> None:
        # A platform may deliver a webhook more than once: a session already served is left alone.
        with self._lock:
            if ThreadRunner.shutdown_event.is_set():
                self._log.info(f"Shutting down; not starting an edge: integration={self._adapter.name}, session_id={session_id}")
                return
            if session_id in self._runners:
                return
            runner = _EdgeRunner(self._adapter.create_edge(session_id))
            thread = threading.Thread(target=self._run, args=(session_id, runner), daemon=True, name=f"{self._adapter.name}-{session_id}")
            self._runners[session_id] = (runner, thread)
        self._log.info(f"Starting an edge: integration={self._adapter.name}, session_id={session_id}")
        thread.start()

    def _run(self, session_id: str, runner: _EdgeRunner) -> None:
        try:
            runner.start()
        except Exception:
            self._log.exception(f"Edge failed: integration={self._adapter.name}, session_id={session_id}")
        finally:
            with self._lock:
                if self._runners.get(session_id, (None,))[0] is runner:
                    del self._runners[session_id]

    def _stop(self, session_id: str) -> None:
        with self._lock:
            entry = self._runners.get(session_id)
        if entry is not None:
            entry[0].stop()
