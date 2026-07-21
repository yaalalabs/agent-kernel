"""``EmbeddedBroker`` — runs ``BrokerWorkerCore`` inline in the caller's event loop.

Always synchronous: ``submit`` runs the request to completion and returns the result
directly, so ``wait`` is ignored and there is never a pending task. Opt-in per deployment —
provider credentials live in the agent process, the documented trade-off for the simplest
possible setup (CLI/tests, or a deployment that accepts co-located execution).
"""

from typing import Optional, Union

from pydantic import BaseModel

from ..model import SandboxResult, SandboxTask
from .base import SandboxBroker, SandboxBrokerRequest, SandboxCompletion
from .worker import BrokerWorkerCore


class EmbeddedBroker(SandboxBroker):
    def __init__(self, config: Optional[BaseModel] = None) -> None:
        """Create the broker with its own in-process ``BrokerWorkerCore``; ``config`` (the
        ``sandbox.broker`` block) is accepted for factory uniformity but unused."""
        self._worker = BrokerWorkerCore()
        self._completions: dict[str, SandboxCompletion] = {}

    async def submit(self, request: SandboxBrokerRequest, wait: Optional[float] = None) -> Union[SandboxResult, SandboxTask]:
        """Run the request inline to completion and return its ``SandboxResult``.

        ``wait`` is ignored (always synchronous, never promotes). ``run()`` raises the real
        ``SandboxError`` on machinery/policy failure so the caller (and, above it, the tool
        layer) sees the true exception type.
        """
        result, session = await self._worker.run(request)
        self._completions[request.task_id] = SandboxCompletion(task_id=request.task_id, status="succeeded", result=result, sandbox_session=session)
        return result

    async def result(self, task_id: str) -> Optional[SandboxCompletion]:
        """Return the completion recorded for ``task_id`` in this process, or ``None``."""
        return self._completions.get(task_id)

    async def discard(self, task_id: str) -> None:
        """Drop the retained completion once the manager has persisted it. Idempotent."""
        self._completions.pop(task_id, None)
