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
        :param adapter: The edge adapter to host.
        :raises ValueError: If the adapter's ``source`` is not ``Source.REALTIME``.
        """
        if adapter.source is not Source.REALTIME:
            raise ValueError(
                f"{type(adapter).__name__}.source is {adapter.source}: an EdgeLifecycleAdapter's create_edge() must return a realtime StatefulEdgeAdapter"
            )
        self._adapter = adapter
        self._stop_requested = threading.Event()
        # Set from ``stop()`` on another thread to wake the runner at once; created on the edge's loop by ``_run_until_stopped``.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None

    @property
    def adapter(self) -> StatefulEdgeAdapter:
        """The hosted adapter."""
        return self._adapter

    def stop(self) -> None:
        """Ask this edge to stop; ``start()`` then returns. Safe from any thread: the handler calls it on an end event and at process shutdown."""
        self._stop_requested.set()
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass  # the edge's loop has closed: the edge already ended

    def start(self) -> None:
        """Register the adapter by its ``session_id``, then run the edge's blocking loop."""
        session_id = self._adapter.session_id
        StatefulEdgeRegistry.register(self._adapter, session_id=session_id)
        try:
            run_async_sync(self._run_until_stopped())
        finally:
            if session_id:
                StatefulEdgeRegistry.unregister(session_id, self._adapter)

    async def _run_until_stopped(self) -> None:
        # Stopped before it started (a connection that ended at once): an adapter cannot stop what it has not begun.
        if ThreadRunner.shutdown_event.is_set() or self._stop_requested.is_set():
            self._log.info(f"Edge {self._adapter.name} stopped before it started")
            return

        self._wake = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        # A stop() that ran before the loop was published could not wake it: catch it here instead.
        if self._stop_requested.is_set():
            self._wake.set()
        await self._run_edge(asyncio.create_task(self._adapter.start()))

    async def _run_edge(self, task: asyncio.Task) -> None:
        """Wait until the edge ends by itself or ``stop()`` is called, then stop it cleanly. Nothing is polled."""
        assert self._wake is not None
        woken = asyncio.ensure_future(self._wake.wait())
        try:
            await asyncio.wait({task, woken}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            woken.cancel()
        if task.done():
            task.result()  # raise if exception occurred
            return

        self._log.info(f"Edge {self._adapter.name} stopping")

        try:
            await asyncio.wait_for(self._adapter.stop(), timeout=self.GRACEFUL_STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._log.warning(f"Edge {self._adapter.name} stop() did not return within {self.GRACEFUL_STOP_TIMEOUT_SECONDS}s; cancelling")
            await self._cancel(task)
            return
        except Exception:
            self._log.exception(f"Error calling stop() on Edge {self._adapter.name}")

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.GRACEFUL_STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._log.warning(f"Edge {self._adapter.name} did not stop within {self.GRACEFUL_STOP_TIMEOUT_SECONDS}s; cancelling")
            await self._cancel(task)

    @staticmethod
    async def _cancel(task: asyncio.Task) -> None:
        """Cancel the edge's task and wait for it to finish."""
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class EdgeLifecycleRESTRequestHandler(RESTRequestHandler):
    """Hosts an :class:`EdgeLifecycleAdapter`: one stateful edge per live connection, started and ended at runtime.

    The sibling of ``WebhookRESTRequestHandler``: it mounts the adapter's webhook route, and for each lifecycle event
    runs the edge for the session on a thread of its own (:class:`_EdgeRunner`), or stops it. Edges must run in the
    process that hosts the Response Handler, so it is mounted inside a pipeline topology. At process shutdown it starts
    no new edges and stops every live one, through ``ThreadRunner.call_on_shutdown``, so no edge polls for it::

        IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])
    """

    requires_pipeline = True
    # The adapter's ``parse`` verifies the platform's signature, as a messaging webhook's ``verify`` does; mounted behind
    # the identity dependency, the platform's own ``Authorization`` header would be refused before it is checked.
    authenticates_itself = True

    _log = logging.getLogger("ak.integration.edge_lifecycle")

    def __init__(self, adapter: EdgeLifecycleAdapter):
        """
        :param adapter: The platform's lifecycle adapter.
        :raises ValueError: If the adapter declares no webhook route.
        """
        if not adapter.webhook_path:
            raise ValueError(f"{type(adapter).__name__} must declare a webhook_path for its platform's lifecycle webhooks")
        self._adapter = adapter
        self._runners: dict[str, _EdgeRunner] = {}
        # Sessions whose start arrived while their edge was ending: a new edge starts once that one has ended.
        self._restart: set[str] = set()
        self._lock = threading.Lock()
        # Started with the first edge; stops every live edge the moment the process starts shutting down.
        self._shutdown_watcher: threading.Thread | None = None

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
                if self._runners[session_id].adapter.ending:
                    self._restart.add(session_id)
                return
            if self._shutdown_watcher is None:
                self._shutdown_watcher = ThreadRunner.call_on_shutdown(self._stop_all, name=f"{self._adapter.name}-shutdown")
            runner = _EdgeRunner(self._adapter.create_edge(session_id))
            thread = threading.Thread(target=self._run, args=(session_id, runner), daemon=True, name=f"{self._adapter.name}-{session_id}")
            self._runners[session_id] = runner
        self._log.info(f"Starting an edge: integration={self._adapter.name}, session_id={session_id}")
        thread.start()

    def _run(self, session_id: str, runner: _EdgeRunner) -> None:
        try:
            runner.start()
        except Exception:
            self._log.exception(f"Edge failed: integration={self._adapter.name}, session_id={session_id}")
        finally:
            restart = False
            with self._lock:
                if self._runners.get(session_id) is runner:
                    del self._runners[session_id]
                    restart = session_id in self._restart
                    self._restart.discard(session_id)
            if restart:
                self._log.info(
                    f"A start arrived while the edge was ending; starting a new one: integration={self._adapter.name}, session_id={session_id}"
                )
                self._start(session_id)

    def _stop_all(self) -> None:
        """Stop every live edge; run once the process starts shutting down (a signal or a failed task).

        Edges started after this reads the runners are refused by ``_start``, which checks the same flag under the same lock.
        """
        with self._lock:
            runners = list(self._runners.values())
        self._log.info(f"Shutting down; stopping {len(runners)} live edge(s): integration={self._adapter.name}")
        for runner in runners:
            runner.stop()

    def _stop(self, session_id: str) -> None:
        with self._lock:
            self._restart.discard(session_id)
            runner = self._runners.get(session_id)
        if runner is not None:
            runner.stop()
