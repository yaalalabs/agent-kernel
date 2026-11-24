from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar

from agentkernel.core.logger import TraceStage

from ak_bench.load.records import ResponseEvent


class ClientDriver(ABC):
    """One client of the deployed app, over any transport (WebSocket, REST, SSE, ...).

    send() hands the request over and returns without waiting for the reply; the reply is reported later through
    on_event (a socket listener for WebSocket, a per-request task for HTTP).
    """

    trace_stages: ClassVar[tuple[TraceStage, ...]]  # request-path stages this mode produces, in order

    def __init__(self, endpoint: str, token: str, on_event: Callable[[ResponseEvent], None]):
        self.endpoint = endpoint
        self.token = token
        self.on_event = on_event

    @abstractmethod
    async def connect(self) -> None:
        """Prepares the client (opens the socket or HTTP client); raises when the server refuses it."""

    @abstractmethod
    async def send(self, request_id: str, session_id: str, prompt: str) -> None:
        """Returns once the request is sent; never waits for the reply."""

    @abstractmethod
    async def close(self) -> None:
        """Stops any reply listening still running and releases the connection."""
