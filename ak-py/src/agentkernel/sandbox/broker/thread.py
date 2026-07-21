"""``ThreadBroker`` — the default local broker flavor (CLI and REST API modes).

One daemon thread runs a private event loop that consumes an in-memory ``asyncio.Queue``
of requests through ``BrokerWorkerCore``. ``submit()`` enqueues thread-safely and bridges
the response future back to the caller's loop:

* ``wait=None`` awaits the result indefinitely (machinery failures raise the real
  ``SandboxError``, matching the embedded flavor).
* ``wait=N`` bounds the wait; on expiry the execution is promoted to a ``SandboxTask``
  and continues on the broker thread. Its completion is kept in worker memory and,
  because the process is shared, ``result()`` serves it to ``SandboxManager.task_status``.

Concurrency contract: every provider handle is created and used only on the broker
thread's loop — callers never touch one.
"""

import asyncio
import concurrent.futures
import logging
import threading
import time
from typing import Optional, Union

from pydantic import BaseModel

from ..errors import SandboxBrokerError, SandboxTimeoutError
from ..model import SandboxResult, SandboxTask
from .base import SandboxBroker, SandboxBrokerRequest, SandboxCompletion
from .worker import BrokerWorkerCore

logger = logging.getLogger("ak.sandbox.broker")


class ThreadBroker(SandboxBroker):
    """In-process broker running executions on a dedicated daemon thread."""

    def __init__(self, config: Optional[BaseModel] = None) -> None:
        """Create the broker; the worker thread starts lazily on first ``submit()``.
        ``config`` (the ``sandbox.broker`` block) is accepted for factory uniformity."""
        self._worker = BrokerWorkerCore()
        self._completions: dict[str, SandboxCompletion] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()
        self._closed = False

    # -- lifecycle ----------------------------------------------------------- #

    def _ensure_started(self) -> None:
        """Start the broker thread once (thread-safe) and wait until its loop is ready."""
        if self._thread is not None:
            return
        with self._start_lock:
            if self._thread is not None:
                return
            if self._closed:
                raise SandboxBrokerError("sandbox thread broker is closed")
            self._thread = threading.Thread(target=self._run_loop, name="ak-sandbox-broker", daemon=True)
            self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        """Thread target: own event loop + request queue, consumed until the shutdown sentinel."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._queue = asyncio.Queue()
        self._ready.set()
        try:
            loop.run_until_complete(self._consume())
        finally:
            loop.close()

    async def _consume(self) -> None:
        """Dispatch each queued request as its own task (per-session serialization lives in
        ``BrokerWorkerCore``); a ``None`` sentinel drains in-flight tasks and exits."""
        in_flight: set[asyncio.Task] = set()
        while True:
            item = await self._queue.get()
            if item is None:
                break
            request, response = item
            task = asyncio.get_running_loop().create_task(self._handle(request, response))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)
        if in_flight:
            await asyncio.gather(*in_flight, return_exceptions=True)

    async def close(self) -> None:
        """Stop the broker thread (drains in-flight executions). Idempotent."""
        with self._start_lock:
            self._closed = True
            thread, loop = self._thread, self._loop
        if thread is None or loop is None or not thread.is_alive():
            return
        loop.call_soon_threadsafe(self._queue.put_nowait, None)
        await asyncio.to_thread(thread.join, 5.0)

    # -- request path -------------------------------------------------------- #

    async def submit(self, request: SandboxBrokerRequest, wait: Optional[float] = None) -> Union[SandboxResult, SandboxTask]:
        """Enqueue the request on the broker loop and await its result.

        ``wait=None`` awaits indefinitely; ``wait=N`` promotes to a ``SandboxTask`` on
        expiry (``wait=0`` always promotes) while the execution continues on the broker
        thread. While waiting, machinery failures raise the real ``SandboxError``.
        """
        self._ensure_started()
        response: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (request, response))
        bridged = asyncio.wrap_future(response)
        if wait is None:
            return await bridged
        try:
            return await asyncio.wait_for(asyncio.shield(bridged), timeout=wait)
        except asyncio.TimeoutError:
            # Promote. The completion resolves into worker memory for result(); retrieve the
            # abandoned future's eventual exception so asyncio never logs it as un-retrieved.
            bridged.add_done_callback(lambda f: f.cancelled() or f.exception())
            return SandboxTask(
                task_id=request.task_id,
                sandbox_session_id=request.sandbox_session.sandbox_session_id,
                profile=request.profile,
                status="pending",
                submitted_at=time.time(),
            )

    async def _handle(self, request: SandboxBrokerRequest, response: concurrent.futures.Future) -> None:
        """Run one request on the broker loop; store its completion and deliver the result
        (or the real exception) to a caller that is still waiting."""
        try:
            result, session = await self._worker.run(request)
        except SandboxTimeoutError as exc:
            self._complete(request, "timed_out", error=str(exc))
            self._deliver_exception(response, exc)
        except Exception as exc:  # noqa: BLE001 — terminal guarantee: every task ends with a completion
            logger.warning("Sandbox task %s failed: %s", request.task_id, exc)
            self._complete(request, "failed", error=str(exc))
            self._deliver_exception(response, exc)
        else:
            self._completions[request.task_id] = SandboxCompletion(
                task_id=request.task_id, status="succeeded", result=result, sandbox_session=session
            )
            if not response.done():
                response.set_result(result)

    def _complete(self, request: SandboxBrokerRequest, status: str, *, error: str) -> None:
        """Record a terminal failure completion for ``result()`` lookups."""
        self._completions[request.task_id] = SandboxCompletion(
            task_id=request.task_id, status=status, error=error, sandbox_session=request.sandbox_session
        )

    @staticmethod
    def _deliver_exception(response: concurrent.futures.Future, exc: Exception) -> None:
        """Hand the exception to a still-waiting caller; a promoted (abandoned) future
        swallows it via the done-callback installed at promotion."""
        if not response.done():
            response.set_exception(exc)

    async def result(self, task_id: str) -> Optional[SandboxCompletion]:
        """Return the completion held in worker memory for ``task_id``, or ``None``."""
        return self._completions.get(task_id)
