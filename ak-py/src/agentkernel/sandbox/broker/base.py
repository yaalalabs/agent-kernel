"""Broker wire contract and the ``SandboxBroker`` ABC.

``SandboxBrokerRequest``/``SandboxCompletion`` are the public messages exchanged between
the agent-side ``SandboxManager`` and a broker worker. They are self-sufficient — a request
carries the resolved principal, policy, and the sandbox session (including the reconnect
handle) so a remote worker needs nothing else to execute it.
"""

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from ..model import SandboxPolicy, SandboxPrincipal, SandboxResult, SandboxSession, SandboxTask

BrokerOperation = Literal["execute_code", "execute_command", "install_packages", "upload_file", "download_file", "destroy"]


class SandboxBrokerRequest(BaseModel):
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


class SandboxCompletion(BaseModel):
    task_id: str
    status: Literal["succeeded", "failed", "timed_out"]
    result: Optional[SandboxResult] = None  # inline when small
    result_ref: Optional[dict[str, str]] = None  # {"bucket":..., "key":...} when offloaded
    error: Optional[str] = None
    sandbox_session: SandboxSession  # updated handle (e.g. newly created sandbox_id)


class SandboxBroker(ABC):
    """Transport between the agent-side manager and the execution engine.

    In-process flavors (``embedded``, ``thread``) run ``BrokerWorkerCore`` locally; the AWS
    ``sqs`` flavor sends the request over a queue to a remote worker.
    """

    @abstractmethod
    async def submit(self, request: SandboxBrokerRequest, wait: Optional[float]) -> Union[SandboxResult, SandboxTask]:
        """Submit a request. Returns a ``SandboxResult`` when it completes within ``wait``,
        or a ``SandboxTask`` handle when execution is promoted to run asynchronously."""

    @abstractmethod
    async def result(self, task_id: str) -> Optional[SandboxCompletion]:
        """Return the completion for a previously submitted task, or None if not yet available."""

    async def close(self) -> None:
        """Release broker resources. Idempotent; default no-op."""
        return None
