import logging
import threading
from typing import Optional

from ...core.util.async_bridge import run_async_sync
from .base import Source, StatefulEdgeAdapter
from .registry import StatefulEdgeRegistry


class GatewayRunner:
    """Hosts a stateful :class:`StatefulEdgeAdapter` (spec #524 §7).

    The bidirectional sibling of :class:`WebhookRESTRequestHandler` and ``PollerRunner``: a
    gateway owns a long-lived platform connection, feeds the input queue with what it reads, and
    delivers replies back through that same connection. ``start()`` runs the adapter's own loop
    on an already-constructed instance.

    A gateway must run in the same process as the Response Handler: it registers itself as the
    platform's outbound adapter as it starts, so replies route back to its live connection.
    """

    _log = logging.getLogger("ak.integration.gateway_runner")
    GRACEFUL_STOP_TIMEOUT_SECONDS: float = 10.0
    """Bound on the adapter's own teardown before it is force-cancelled."""
    READY_TIMEOUT_SECONDS: float = 30.0
    """How long :meth:`start_background` waits for the edge to report ready."""

    def __init__(self, adapter: StatefulEdgeAdapter):
        """
        :param adapter: The gateway adapter to host.
        :raises ValueError: If the adapter's ``source`` is not ``Source.REALTIME``.
        """
        if adapter.source is not Source.REALTIME:
            raise ValueError(
                f"{type(adapter).__name__} is a {adapter.source} adapter: "
                "host it with WebhookRESTRequestHandler or PollerRunner, not GatewayRunner"
            )
        self._adapter = adapter
        self._stop_requested = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thread_error: Optional[BaseException] = None

    @property
    def running(self) -> bool:
        """True while a background gateway's thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def adapter(self) -> StatefulEdgeAdapter:
        """The hosted adapter (IOHandler names its thread after it)."""
        return self._adapter

    def start(self) -> None:
        """Register the outbound adapter, then run the gateway's blocking loop.

        The registration is what lets the Response Handler resolve this live connection by the
        adapter's ``session_id``. It happens here rather than in the adapter's constructor so the side
        effect is tied to being hosted, not to merely existing.
        """
        session_id = getattr(self._adapter, "session_id", None)
        StatefulEdgeRegistry.register(self._adapter, session_id=session_id)
        try:
            run_async_sync(self._run_until_shutdown())
        finally:
            if session_id:
                StatefulEdgeRegistry.unregister(session_id, self._adapter)

    def start_background(self, ready_timeout: Optional[float] = None) -> None:
        """Run the gateway on a thread of its own and return once its edge is ready.

        Unlike a boot-time gateway (hosted by ``IOHandler`` as a task whose failure ends the process), a
        background gateway reports its failure to the caller, so one failing does not end the others.

        :param ready_timeout: Seconds to wait for the edge to call ``_mark_ready``; defaults to
            :attr:`READY_TIMEOUT_SECONDS`.
        :raises RuntimeError: If already started.
        :raises Exception: Whatever the edge's ``start()`` raised, re-raised here.
        :raises TimeoutError: If the edge is not ready in time; the gateway is stopped first.
        """
        if self._thread is not None:
            raise RuntimeError(f"Gateway {self._adapter.name} is already started")
        timeout = self.READY_TIMEOUT_SECONDS if ready_timeout is None else ready_timeout
        self._thread = threading.Thread(target=self._run_thread, name=f"gateway-{self._adapter.name}-{self._adapter.session_id}", daemon=True)
        self._thread.start()
        elapsed = 0.0
        step = 0.02
        while elapsed < timeout:
            if self._adapter.wait_ready(step):
                return
            if not self._thread.is_alive():
                break
            elapsed += step
        if self._thread_error is not None or not self._thread.is_alive():
            error = self._thread_error
            self._thread.join(timeout=1.0)
            if error is not None:
                raise error
            raise RuntimeError(f"Gateway {self._adapter.name} ended before it was ready")
        self.stop()
        raise TimeoutError(f"Gateway {self._adapter.name} was not ready within {timeout}s")

    def stop(self, timeout: Optional[float] = None) -> None:
        """Stop a background gateway and wait for its thread; safe to call twice, and before a start.

        :param timeout: Seconds to wait for the thread; defaults to ``GRACEFUL_STOP_TIMEOUT_SECONDS + 1``.
        """
        self._stop_requested.set()
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return
        thread.join(timeout=timeout or self.GRACEFUL_STOP_TIMEOUT_SECONDS + 1)

    def _run_thread(self) -> None:
        try:
            self.start()
        except BaseException as e:  # reported to start_background's caller, never the process
            self._thread_error = e
            self._log.error(f"Background gateway {self._adapter.name} failed: {e}")

    async def _run_until_shutdown(self) -> None:
        import asyncio

        from ...pipeline.thread_runner import ThreadRunner

        task = asyncio.create_task(self._adapter.start())

        while not ThreadRunner.shutdown_event.is_set() and not self._stop_requested.is_set():
            if task.done():
                task.result()  # raise if exception occurred
                return
            await asyncio.sleep(0.5)

        self._log.info(f"Gateway {self._adapter.name} stopping due to shutdown event or stop request")

        try:
            await self._adapter.stop()
        except Exception:
            self._log.exception(f"Error calling stop() on Gateway {self._adapter.name}")

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.GRACEFUL_STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._log.warning(f"Gateway {self._adapter.name} did not stop within {self.GRACEFUL_STOP_TIMEOUT_SECONDS}s; cancelling")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
