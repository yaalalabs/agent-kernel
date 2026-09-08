"""Broker wire contract and the ``ExecutionBroker`` ABC.

``ExecutionRequest``/``ExecutionCompletion`` are the public messages exchanged between
the agent-side ``ExecutionManager`` and a broker worker. They are self-sufficient — a request
carries the resolved principal, policy, and the sandbox session (including the reconnect
handle) so a remote worker needs nothing else to execute it.
"""

from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from ..model import SandboxPolicy, SandboxPrincipal, SandboxResult, SandboxSession, SandboxTask

BrokerOperation = Literal["execute_code", "execute_command", "install_packages", "upload_file", "download_file", "destroy"]


class BoundedCompletionStore:
    """A bounded, LRU-evicting ``task_id -> ExecutionCompletion`` map for the in-process broker
    flavors, so a long-running server does not accumulate one completion per execution for the
    process lifetime. The cap only bounds the tail: a completion is normally dropped as soon as
    ``ExecutionManager`` consumes it (``discard``), and promoted tasks are polled within seconds —
    far inside the cap — while synchronous results are never polled at all and just age out."""

    def __init__(self, maxlen: int = 1024) -> None:
        self._maxlen = maxlen
        self._items: "OrderedDict[str, ExecutionCompletion]" = OrderedDict()

    def set(self, task_id: str, completion: "ExecutionCompletion") -> None:
        self._items[task_id] = completion
        self._items.move_to_end(task_id)
        while len(self._items) > self._maxlen:
            self._items.popitem(last=False)  # evict the oldest

    def get(self, task_id: str) -> Optional["ExecutionCompletion"]:
        return self._items.get(task_id)

    def discard(self, task_id: str) -> None:
        self._items.pop(task_id, None)


class ExecutionRequest(BaseModel):
    task_id: str
    operation: BrokerOperation
    payload: dict[str, Any] = Field(default_factory=dict)  # operation arguments
    profile: str
    principal: SandboxPrincipal
    policy: SandboxPolicy
    sandbox_session: SandboxSession  # includes the reconnect handle — self-sufficient
    ak_session_id: str  # for completion routing
    agent: str  # for completion routing
    wait_deadline: Optional[float] = None  # epoch seconds; None = caller will not wait


class ExecutionCompletion(BaseModel):
    task_id: str
    status: Literal["succeeded", "failed", "timed_out"]
    result: Optional[SandboxResult] = None  # inline when small
    result_ref: Optional[dict[str, str]] = None  # {"bucket":..., "key":...} when offloaded
    error: Optional[str] = None
    error_type: Optional[str] = None  # SandboxError subclass name, for a typed re-raise across the wire
    sandbox_session: SandboxSession  # updated handle (e.g. newly created sandbox_id)


class ExecutionBroker(ABC):
    """Transport between the agent-side manager and the execution engine.

    In-process flavors (``embedded``, ``thread``) run ``BrokerWorkerCore`` locally; the AWS
    ``sqs`` flavor sends the request over a queue to a remote worker.
    """

    @abstractmethod
    async def submit(self, request: ExecutionRequest, wait: Optional[float]) -> Union[SandboxResult, SandboxTask]:
        """Submit a request. Returns a ``SandboxResult`` when it completes within ``wait``,
        or a ``SandboxTask`` handle when execution is promoted to run asynchronously."""

    @abstractmethod
    async def result(self, task_id: str) -> Optional[ExecutionCompletion]:
        """Return the completion for a previously submitted task, or None if not yet available."""

    async def discard(self, task_id: str) -> None:
        """Release any retained completion for ``task_id`` once the manager has consumed and
        persisted it. Idempotent; default no-op. In-process flavors that retain completions in
        memory override this to bound their footprint; durable flavors (e.g. ``sqs``) rely on
        the response store's TTL and keep the no-op."""
        return None

    async def close(self) -> None:
        """Release broker resources. Idempotent; default no-op."""
        return None
