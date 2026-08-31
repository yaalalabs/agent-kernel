"""``QueueExecutionBroker`` — the ``queue`` broker flavor's agent-side client (spec #503).

``submit()`` serializes the request with :class:`BrokerWireCodec` and sends it to the sandbox
block's input queue (``group_id = sandbox_session_id`` carries the #494 per-session
serialization contract across the worker fleet; ``dedup_id = task_id``), then polls the shared
response store until the effective wait expires:

* ``wait=N`` bounds the poll; ``wait=None`` is bounded by ``sandbox.broker.wait_timeout``,
  never indefinite on this flavor — an unbounded await against a possibly-down remote worker
  would hang the agent turn, and the worker's terminal-completion guarantee plus the
  ``check_sandbox_task`` recovery path cover the tail.
* ``destroy`` is fire-and-forget: per-group FIFO orders it after every operation submitted
  before it, and the worker's destroys are idempotent.

The store is the durable source of truth: records are read without ``get_and_delete`` (the
TTL owns cleanup), so ``result()`` serves ``ExecutionManager.task_status`` from any process.
"""

import asyncio
import logging
import time
from typing import Optional, Union

from pydantic import BaseModel

from ...pipeline.envelope import ATTR_REQUEST_ID, QueueMessage, QueueName
from ...pipeline.response_store.base import ResponseStore
from ...pipeline.response_store.factory import ResponseStoreFactory
from ...pipeline.transport.base import QueueTransport, QueueTransportFactory
from .. import errors as sandbox_errors
from ..errors import ExecutionBrokerError, SandboxConfigError, SandboxPolicyError, SandboxTimeoutError
from ..model import SandboxResult, SandboxTask
from .base import ExecutionBroker, ExecutionCompletion, ExecutionRequest
from .wire import BrokerWireCodec

logger = logging.getLogger("ak.sandbox.broker")


class QueueExecutionBroker(ExecutionBroker):
    """Transport-backed broker client: submits over a queue, reads completions from the store."""

    def __init__(self, config: BaseModel) -> None:
        """``config`` is the ``sandbox.broker`` block (factory-injected). Fail fast on the two
        blocks the flavor cannot run without; the transport and store are built lazily on first
        use via the #503 factory seams, whose own errors (missing backend block, missing extra,
        the store/transport pairing rule) propagate as-is."""
        if getattr(config, "queue", None) is None:
            raise SandboxConfigError("sandbox.broker.flavor 'queue' requires the sandbox.broker.queue block")
        if getattr(config, "response_store", None) is None:
            raise SandboxConfigError("sandbox.broker.flavor 'queue' requires the sandbox.broker.response_store block")
        self._config = config
        self._transport: Optional[QueueTransport] = None
        self._store: Optional[ResponseStore] = None

    # -- lazy wiring --------------------------------------------------------- #

    def _get_transport(self) -> QueueTransport:
        if self._transport is None:
            self._transport = QueueTransportFactory.create(queues_config=self._config.queue)
        return self._transport

    def _get_store(self) -> ResponseStore:
        if self._store is None:
            self._store = ResponseStoreFactory.create(
                response_store_config=self._config.response_store,
                transport_type=QueueTransportFactory.resolve_type(self._config.queue),
                ttl=self._config.response_ttl,
            )
        return self._store

    # -- request path -------------------------------------------------------- #

    async def submit(self, request: ExecutionRequest, wait: Optional[float] = None) -> Union[SandboxResult, SandboxTask]:
        """Send the request to the input queue and poll the store within the effective wait.

        Returns the ``SandboxResult`` when the completion lands in time, re-raises the typed
        error for failed/timed-out completions, and promotes to a pending ``SandboxTask`` on
        expiry (``destroy`` always promotes immediately: fire-and-forget).
        """
        if request.operation == "destroy":
            effective_wait = 0.0
        else:
            effective_wait = wait if wait is not None else self._config.wait_timeout
        ceiling = self._config.worker_timeout_ceiling
        if ceiling is not None and request.policy.timeout > ceiling:
            raise SandboxPolicyError(
                f"policy timeout {request.policy.timeout}s exceeds the provisioned worker's timeout ceiling "
                f"(sandbox.broker.worker_timeout_ceiling={ceiling}s)"
            )
        body = BrokerWireCodec.encode_request(request)
        size = len(body.encode("utf-8"))
        limit = self._config.inline_payload_max_bytes
        if size > limit:
            raise ExecutionBrokerError(
                f"serialized {request.operation} request is {size} bytes, over sandbox.broker.inline_payload_max_bytes={limit}; "
                "pass large inputs as files or raise the limit"
            )
        message = QueueMessage(
            body=body,
            attributes={ATTR_REQUEST_ID: request.task_id},
            group_id=request.sandbox_session.sandbox_session_id,
            dedup_id=request.task_id,
        )
        await asyncio.to_thread(self._get_transport().send, QueueName.INPUT, message)
        if effective_wait > 0:
            completion = await self._poll(request.task_id, time.time() + effective_wait)
            if completion is not None:
                return self._unwrap(completion)
        return SandboxTask(
            task_id=request.task_id,
            sandbox_session_id=request.sandbox_session.sandbox_session_id,
            profile=request.profile,
            status="pending",
            submitted_at=time.time(),
        )

    async def _poll(self, task_id: str, deadline: float) -> Optional[ExecutionCompletion]:
        """Poll the store every ``wait_poll_interval`` seconds until the completion record
        lands or ``deadline`` passes. Store read failures are treated as transient: log and
        keep polling — a store blip must not fail an execution that is still running."""
        store = self._get_store()
        while True:
            body = None
            try:
                body = await asyncio.to_thread(store.get_message, task_id)
            except Exception as exc:  # noqa: BLE001 — poll continues until the deadline
                logger.warning("Sandbox completion poll for task %s failed (retrying until deadline): %s", task_id, exc)
            if body is not None:
                return BrokerWireCodec.decode_completion(body)
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(self._config.wait_poll_interval, remaining))

    def _unwrap(self, completion: ExecutionCompletion) -> SandboxResult:
        """Turn a terminal completion into the caller's outcome, reconstructing the typed
        error across the wire: only names defined in ``agentkernel.sandbox.errors`` are
        honored; unknown or absent names degrade to ``ExecutionBrokerError``."""
        if completion.status == "succeeded":
            return completion.result
        if completion.status == "timed_out":
            raise SandboxTimeoutError(completion.error or "sandbox execution timed out")
        exc_cls = getattr(sandbox_errors, completion.error_type or "", None)
        if isinstance(exc_cls, type) and issubclass(exc_cls, sandbox_errors.SandboxError):
            raise exc_cls(completion.error or "sandbox execution failed")
        raise ExecutionBrokerError(completion.error or "sandbox execution failed")

    async def result(self, task_id: str) -> Optional[ExecutionCompletion]:
        """Return the stored completion for ``task_id``, or ``None`` while it is pending.

        Serves ``ExecutionManager.task_status`` — the ``check_sandbox_task`` recovery path —
        including from a process that never submitted the task."""
        body = await asyncio.to_thread(self._get_store().get_message, task_id)
        return None if body is None else BrokerWireCodec.decode_completion(body)

    # discard(): inherited no-op — the store is durable and its TTL owns cleanup.
    # close(): inherited no-op — the send side of a QueueTransport holds no consumer resources.
