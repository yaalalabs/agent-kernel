import logging
import threading
from typing import Optional

from ...core.util.async_bridge import run_async_sync
from .base import Source, StatefulEdgeAdapter
from .registry import StatefulEdgeRegistry


class GatewayRunner:
    """Hosts a stateful :class:`StatefulEdgeAdapter` gateway until the process shuts down or :meth:`stop` is called."""

    _log = logging.getLogger("ak.integration.gateway_runner")
    GRACEFUL_STOP_TIMEOUT_SECONDS: float = 10.0
    """Bound on the adapter's own teardown before it is force-cancelled."""

    def __init__(self, adapter: StatefulEdgeAdapter):
        """Binds the gateway adapter to host, raising ``ValueError`` unless its ``source`` is ``Source.REALTIME``."""
        if adapter.source is not Source.REALTIME:
            raise ValueError(
                f"{type(adapter).__name__} is a {adapter.source} adapter: "
                "host it with WebhookRESTRequestHandler or PollerRunner, not GatewayRunner"
            )
        self._adapter = adapter
        self._stop_requested = threading.Event()
        self._started = threading.Event()
        self._finished = threading.Event()

    @property
    def adapter(self) -> StatefulEdgeAdapter:
        """The hosted adapter (IOHandler names its thread after it)."""
        return self._adapter

    def start(self) -> None:
        """Register the outbound adapter, then run the gateway's blocking loop."""
        self._started.set()
        try:
            if self._stop_requested.is_set():
                self._log.info(f"Gateway {self._adapter.name} was stopped before it started")
                return
            session_id = getattr(self._adapter, "session_id", None)
            StatefulEdgeRegistry.register(self._adapter, session_id=session_id)
            try:
                run_async_sync(self._run_until_shutdown())
            finally:
                if session_id:
                    # Only its own entry: a gateway opened for the same session since this one was stopped may
                    # already have registered in its place.
                    StatefulEdgeRegistry.unregister(session_id, adapter=self._adapter)
        finally:
            self._finished.set()

    def stop(self, timeout: Optional[float] = None) -> bool:
        """Stop the gateway from any thread, before or after :meth:`start`; returns whether ``start()`` has returned or never ran."""
        self._stop_requested.set()
        if not self._started.is_set():
            return True
        return self._finished.wait(timeout)

    async def _run_until_shutdown(self) -> None:
        import asyncio

        from ...pipeline.thread_runner import ThreadRunner

        task = asyncio.create_task(self._adapter.start())

        while not ThreadRunner.shutdown_event.is_set() and not self._stop_requested.is_set():
            if task.done():
                task.result()  # raise if exception occurred
                return
            await asyncio.sleep(0.5)

        reason = "it was stopped" if self._stop_requested.is_set() else "the shutdown event"
        self._log.info(f"Gateway {self._adapter.name} stopping: {reason}")

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
