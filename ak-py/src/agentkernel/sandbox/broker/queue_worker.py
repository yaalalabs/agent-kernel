"""``QueueBrokerWorker`` — the ``queue`` broker flavor's worker process (spec #503).

The chat pipeline's Agent Runner / Output Consumer split applied inside one process, over the
``sandbox.broker.queue`` block's two queues:

* the **request loop** consumes the input queue, serializes per sandbox session with a
  cross-thread lock (each message runs under its own event loop, so the core's asyncio lock
  cannot carry this here), drives ``BrokerWorkerCore`` (fail-closed checks and self-heal
  unchanged), truncates oversized results, and sends the ready-to-store record to the
  output queue;
* the **output loop** consumes the output queue and persists each record verbatim to the
  shared response store, then upserts the idle-sweep inventory.

The queue hop between them is what decouples execution from store availability: once the
record is queued, a store outage retries the persist via output-queue redelivery without
re-running the (side-effectful) sandbox operation. A third task sweeps idle sandbox sessions
via the store's optional key-scan capability.
"""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Optional

from ...core.config import AKConfig
from ...pipeline.consumer import ConsumerLoop
from ...pipeline.envelope import ATTR_REQUEST_ID, QueueMessage, QueueName
from ...pipeline.response_store.base import ResponseStore
from ...pipeline.response_store.factory import ResponseStoreFactory
from ...pipeline.thread_runner import ThreadRunner
from ...pipeline.transport.base import QueueTransport, QueueTransportFactory
from ..errors import SandboxConfigError
from ..factory import SandboxProviderFactory
from ..model import SandboxSession
from .base import ExecutionCompletion
from .queue import check_store_pairing
from .wire import BrokerWireCodec
from .worker import BrokerWorkerCore

logger = logging.getLogger("ak.sandbox.broker.worker")

_STATUS_CODES = {"succeeded": 200, "failed": 500, "timed_out": 504}

_INVENTORY_PREFIX = "session:"


class QueueBrokerWorker:
    """Blocking sandbox execution worker (the ``AgentRunner`` analogue for the sandbox broker)."""

    def __init__(self, sandbox_config: Optional[Any] = None) -> None:
        """Validate the configuration and build the transport, store, and engine, all
        fail-fast: a misconfigured worker must die at startup, not on its first message.
        ``sandbox_config`` defaults to ``AKConfig.get().sandbox`` (injectable for tests)."""
        config = sandbox_config if sandbox_config is not None else AKConfig.get().sandbox
        self._broker = self._validated_broker(config)
        transport_type = QueueTransportFactory.resolve_type(self._broker.queue)
        self._transport: QueueTransport = QueueTransportFactory.create(queues_config=self._broker.queue, config_path="sandbox.broker.queue")
        self._store: ResponseStore = ResponseStoreFactory.create(
            response_store_config=self._broker.response_store,
            transport_type=transport_type,
            ttl=self._broker.response_ttl,
            config_path="sandbox.broker.response_store",
        )
        # Truncation happens here in the worker (against inline_payload_max_bytes), never in core.
        self._core = BrokerWorkerCore(inline_payload_max_bytes=None)
        # Per-session serialization across the request-loop threads (see _process_request).
        self._session_locks: dict[str, threading.Lock] = {}
        self._session_locks_guard = threading.Lock()

    @staticmethod
    def _validated_broker(config: Any) -> Any:
        """The startup fail-fasts: enabled, the right flavor, both blocks, and the
        in_memory pairing rule (shared with the client via ``check_store_pairing``)."""
        if not config.enabled:
            raise SandboxConfigError("QueueBrokerWorker requires sandbox.enabled: true")
        broker = config.broker
        if broker.flavor != "queue":
            raise SandboxConfigError(f"QueueBrokerWorker requires sandbox.broker.flavor 'queue' (got '{broker.flavor}')")
        if broker.queue is None:
            raise SandboxConfigError("the 'queue' broker flavor requires the sandbox.broker.queue block")
        if broker.response_store is None:
            raise SandboxConfigError("the 'queue' broker flavor requires the sandbox.broker.response_store block")
        check_store_pairing(broker.queue, broker.response_store)
        return broker

    # -- lifecycle ------------------------------------------------------------ #

    @classmethod
    def run(cls) -> None:
        """Blocking worker entry point: signal discipline, then the three peer tasks."""
        ThreadRunner.install_shutdown_signal_handlers(logger)
        cls().start()

    def start(self, exit_on_shutdown: bool = True) -> None:
        """Run the request loop, the output loop, and the sweep until shutdown."""
        queues = self._broker.queue
        self._transport.check_consumer_capacity(QueueName.INPUT, queues.input.no_of_consumers)
        self._transport.check_consumer_capacity(QueueName.OUTPUT, queues.output.no_of_consumers)
        ThreadRunner.run(
            tasks=[
                ThreadRunner.Task(
                    execution_function=lambda: self._consumer_loop(QueueName.INPUT).run(),
                    thread_name="sandbox-worker-loop",
                    stop_all_on_failure=True,
                    graceful=True,
                ),
                ThreadRunner.Task(
                    execution_function=lambda: self._consumer_loop(QueueName.OUTPUT).run(),
                    thread_name="sandbox-output-loop",
                    stop_all_on_failure=True,
                    graceful=True,
                ),
                ThreadRunner.Task(
                    execution_function=self._sweep_loop,
                    thread_name="sandbox-sweep",
                    stop_all_on_failure=True,
                    graceful=True,
                ),
            ],
            exit_on_shutdown=exit_on_shutdown,
        )

    def _consumer_loop(self, queue: QueueName) -> ConsumerLoop:
        """Build one of the two loops; both nest inside ``start()``'s runner, so they drain
        and return on shutdown (``exit_on_shutdown=False``) and only ``start()`` exits."""
        queues = self._broker.queue
        request_side = queue == QueueName.INPUT
        block = queues.input if request_side else queues.output
        return ConsumerLoop(
            process=self._process_request if request_side else self._process_completion,
            on_permanent_failure=self._on_request_permanent_failure if request_side else self._on_completion_permanent_failure,
            max_receive_count=block.max_receive_count,
            num_consumers=block.no_of_consumers,
            batch_size=queues.batch_size or 1,
            consumer_factory=lambda: self._transport.create_consumer(queue),
            thread_name_prefix="sandbox-worker" if request_side else "sandbox-output",
            queue=queue,
            logger=logger,
            exit_on_shutdown=False,
        )

    # -- the request loop ------------------------------------------------------ #

    async def _process_request(self, message: QueueMessage) -> None:
        """Execute one request and queue its ready-to-store record. A decode failure raises
        (nack, bounded redelivery, permanent-failure path; no silent drop); a send failure
        raises and the redelivery re-executes (the documented at-least-once window, closed
        once the record is queued)."""
        request = BrokerWireCodec.decode_request(message.body)
        # Serialize per session with a threading.Lock: each message runs under its own
        # asyncio.run() in one of several consumer threads, so the core's asyncio.Lock cannot
        # be contended safely across those loops. Contention only arises when a redelivery
        # overlaps a still-running execution (ack_wait below the policy timeout); otherwise
        # the transport's one-in-flight-per-group FIFO already carries the guarantee.
        lock = self._session_lock(request.sandbox_session.sandbox_session_id)
        await asyncio.to_thread(lock.acquire)
        try:
            completion = await self._core.process(request)  # never raises: terminal guarantee
        finally:
            lock.release()
        self._truncate(completion)
        self._send_completion(completion, ak_session_id=request.ak_session_id)

    def _session_lock(self, sandbox_session_id: str) -> threading.Lock:
        """Return (creating on first use) the cross-thread lock for one sandbox session."""
        with self._session_locks_guard:
            lock = self._session_locks.get(sandbox_session_id)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[sandbox_session_id] = lock
            return lock

    def _truncate(self, completion: ExecutionCompletion) -> None:
        """Truncate an oversized result in place so the whole encoded record fits within
        ``inline_payload_max_bytes`` (v1, no offload: ``result_ref`` stays None): a per-field
        cap would let stdout, stderr, and files each approach the limit and the combined
        record blow the transport's message-size cap, failing the very send the truncation
        exists to protect. Output files are dropped first, then the streams give up bytes,
        longest first. The notice is stamped before trimming so it never re-overflows."""
        result = completion.result
        limit = self._broker.inline_payload_max_bytes
        if result is None or self._encoded_size(completion) <= limit:
            return
        note = f"output truncated to fit the {limit}-byte record limit; rerun with a file redirection to keep full output"
        result.notice = note if result.notice is None else f"{result.notice}; {note}"
        while result.output_files and self._encoded_size(completion) > limit:
            result.output_files = result.output_files[:-1]
        # Every trimmed character frees at least one encoded byte, so cutting by the overshoot
        # converges in a few passes despite JSON-escaping inflation.
        while (overshoot := self._encoded_size(completion) - limit) > 0:
            stream = "stdout" if len(result.stdout) >= len(result.stderr) else "stderr"
            text: str = getattr(result, stream)
            if not text:
                break
            setattr(result, stream, text[: max(len(text) - overshoot, 0)])

    def _encoded_size(self, completion: ExecutionCompletion) -> int:
        """The completion body's wire size: what ``_send_completion`` will enqueue as ``body``."""
        return len(json.dumps(BrokerWireCodec.encode_completion(completion)).encode("utf-8"))

    def _send_completion(self, completion: ExecutionCompletion, *, ak_session_id: str) -> None:
        """Send the ready-to-store record to the output queue, where the output loop
        persists it verbatim."""
        record = {
            "request_id": completion.task_id,
            "session_id": ak_session_id,
            "status_code": _STATUS_CODES[completion.status],
            "body": BrokerWireCodec.encode_completion(completion),
        }
        self._transport.send(
            QueueName.OUTPUT,
            QueueMessage(
                body=json.dumps(record),
                attributes={ATTR_REQUEST_ID: completion.task_id},
                group_id=completion.sandbox_session.sandbox_session_id,
                dedup_id=completion.task_id,
            ),
        )

    def _on_request_permanent_failure(self, message: QueueMessage) -> None:
        """Terminal disposition for a request that exhausted its deliveries: send a ``failed``
        completion record so no task with a recoverable id ends without one. Catches its own
        exceptions (the ``ConsumerLoop`` contract)."""
        try:
            ak_session_id = "unknown"
            try:
                request = BrokerWireCodec.decode_request(message.body)
                task_id: Optional[str] = request.task_id
                session = request.sandbox_session
                ak_session_id = request.ak_session_id
            except Exception:  # noqa: BLE001 — an undecodable body still gets a placeholder completion
                task_id = message.attributes.get(ATTR_REQUEST_ID)
                if not task_id:
                    logger.error("Dropping undecodable sandbox request with no %s attribute (message %s)", ATTR_REQUEST_ID, message.message_id)
                    return
                now = time.time()
                session = SandboxSession(sandbox_session_id=task_id, profile="unknown", provider_type="unknown", created_at=now, last_used_at=now)
            self._send_completion(
                ExecutionCompletion(
                    task_id=task_id,
                    status="failed",
                    error=f"sandbox execution failed after {message.receive_count} deliveries",
                    error_type="ExecutionBrokerError",
                    sandbox_session=session,
                ),
                ak_session_id=ak_session_id,
            )
        except Exception:  # noqa: BLE001 — a raising hook would loop the message forever
            logger.exception("Failed to record the permanent failure of sandbox request message %s", message.message_id)

    # -- the output loop ------------------------------------------------------- #

    def _process_completion(self, message: QueueMessage) -> None:
        """Persist one ready-to-store record (the ``ECSOutputConsumer`` role). A decode or
        store-write failure raises: redelivery retries the persist only; the sandbox
        operation is never re-executed from here."""
        record = json.loads(message.body)
        self._store.add_message(record)
        try:
            # Every terminal status updates the inventory: a failed operation may still have
            # provisioned a sandbox (its session carries the sandbox_id), and that sandbox
            # must be sweepable; a cleared sandbox_id (destroy) drops the record.
            self._update_inventory(BrokerWireCodec.decode_completion(record["body"]))
        except Exception:  # noqa: BLE001 — inventory is best-effort; the persisted record must not loop
            logger.exception("Failed to update the sweep inventory for request %s", record.get("request_id"))

    def _update_inventory(self, completion: ExecutionCompletion) -> None:
        """Upsert the idle-sweep inventory for a successful managed-profile completion; a
        completion whose session holds no sandbox anymore (a destroy) drops the record."""
        session = completion.sandbox_session
        profile_cfg = AKConfig.get().sandbox.profiles.get(session.profile)
        if profile_cfg is None or BrokerWorkerCore._environment_mode(session.profile) == "attached":
            return  # attached environments are never owned, so never swept (#494 rule)
        key = f"{_INVENTORY_PREFIX}{session.sandbox_session_id}"
        if not session.sandbox_id:
            self._store.delete_message(key)
            return
        self._store.add_message(
            {
                "request_id": key,
                "session_id": session.sandbox_session_id,
                "status_code": 200,
                "body": {
                    "provider_type": session.provider_type,
                    "sandbox_id": session.sandbox_id,
                    "profile": session.profile,
                    "idle_timeout": profile_cfg.idle_timeout,
                    "last_used_at": session.last_used_at,
                },
            }
        )

    def _on_completion_permanent_failure(self, message: QueueMessage) -> None:
        """A record that could not be persisted within its redelivery budget (a store outage
        outliving it): log and let ``dead_letter`` run; the task stays pending and
        ``check_sandbox_task`` keeps reporting it. Catches its own exceptions."""
        try:
            request_id = message.attributes.get(ATTR_REQUEST_ID) or json.loads(message.body).get("request_id")
        except Exception:  # noqa: BLE001 — best-effort identification only
            request_id = None
        logger.error(
            "Sandbox completion record %s could not be persisted after %d deliveries; the task stays pending until recovery",
            request_id or f"<undecodable message {message.message_id}>",
            message.receive_count,
        )

    # -- the idle sweep --------------------------------------------------------- #

    def _sweep_loop(self) -> None:
        """Every ``sweep_interval`` seconds, destroy managed sandboxes idle past their
        profile's ``idle_timeout``. A store without key-scan support disables the sweep with
        one startup WARNING naming the remaining backstops."""
        if not self._store.supports_key_scan():
            logger.warning(
                "Response store %s does not support key scans; the idle-session sweep is disabled "
                "(backstops: the agent-side idle reset on touch, and provider-side ceilings such as activeDeadlineSeconds)",
                type(self._store).__name__,
            )
            ThreadRunner.shutdown_event.wait()
            return
        while not ThreadRunner.shutdown_event.wait(timeout=self._broker.sweep_interval):
            try:
                asyncio.run(self._sweep_once())
            except Exception:  # noqa: BLE001 — a failing pass must not kill the worker
                logger.exception("Idle-session sweep pass failed; retrying next interval")

    async def _sweep_once(self) -> None:
        """One sweep pass over the ``session:`` inventory records."""
        now = time.time()
        for record in self._store.scan_records(_INVENTORY_PREFIX):
            body = record.get("body") or {}
            idle_timeout, last_used_at = body.get("idle_timeout"), body.get("last_used_at")
            if not idle_timeout or last_used_at is None or now - last_used_at <= idle_timeout:
                continue
            try:
                provider = SandboxProviderFactory.get(body["profile"])
                if provider is None or BrokerWorkerCore._environment_mode(body["profile"]) == "attached":
                    continue
                await provider.destroy(body["sandbox_id"])
                self._store.delete_message(record["request_id"])
                logger.info("Swept idle sandbox %s (inventory %s, idle > %ss)", body["sandbox_id"], record["request_id"], idle_timeout)
            except Exception:  # noqa: BLE001 — one bad record must not stop the pass
                logger.exception("Failed to sweep sandbox inventory record %s", record.get("request_id"))
