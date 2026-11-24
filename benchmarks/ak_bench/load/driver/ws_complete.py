import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agentkernel.core import TraceStage
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from ak_bench.load.driver.base import ClientDriver
from ak_bench.load.records import ResponseEvent

_logger = logging.getLogger("ak_bench")


class WebSocketCompleteDriver(ClientDriver):
    """AK's WebSocket chat frames, one complete reply per request (async mode, complete message type)."""

    trace_stages = tuple(s for s in TraceStage if s not in (TraceStage.AGENT_FIRST_CHUNK, TraceStage.RESPONSE_POLL_START, TraceStage.RESPONSE_FOUND))
    # AK accepts the socket, then closes it on a refused token; a close within this time counts as a refused connect.
    AUTH_GRACE_S = 0.5

    def __init__(self, endpoint, token, on_event):
        super().__init__(endpoint, token, on_event)
        self._ws: ClientConnection | None = None
        self._receiver: asyncio.Task | None = None
        self._in_flight: dict[str, None] = {}  # insertion-ordered set

    def url(self) -> str:
        parts = urlsplit(self.endpoint)
        query = urlencode([*parse_qsl(parts.query), ("token", self.token)])
        return urlunsplit(parts._replace(query=query))

    async def connect(self) -> None:
        self._ws = await connect(self.url())
        try:
            await asyncio.wait_for(self._ws.wait_closed(), self.AUTH_GRACE_S)
        except TimeoutError:
            self._receiver = asyncio.create_task(self._receive())
            return
        raise ConnectionRefusedError(f"server closed the connection: {self._ws.close_code} {self._ws.close_reason}")

    async def send(self, request_id: str, session_id: str, prompt: str) -> None:
        self._in_flight[request_id] = None
        try:
            await self._ws.send(json.dumps({"request_id": request_id, "body": {"session_id": session_id, "prompt": prompt}}))
        except BaseException:
            self._in_flight.pop(request_id, None)
            raise

    async def close(self) -> None:
        if self._receiver is not None:
            self._receiver.cancel()
            await asyncio.gather(self._receiver, return_exceptions=True)
        if self._ws is not None:
            await self._ws.close()

    async def _receive(self) -> None:
        try:
            async for raw in self._ws:
                self._handle(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
        except ConnectionClosed:
            pass

    def _handle(self, raw: str) -> None:
        try:
            frame = json.loads(raw)
        except ValueError:
            _logger.warning("dropped a non-JSON frame: %.200s", raw)
            return
        if not isinstance(frame, dict):
            return
        kind = frame.get("type")
        # AK reports a failure as {"error": ...} (agent error, permanent delivery failure) or status FAILED (enqueue failure).
        failed = "error" in frame or frame.get("status") == "FAILED"
        # Only replies count: CHAT_QUEUED carries the request id but is the ack, and an unknown frame must not pass as a reply.
        if kind != "CHAT_RESPONSE" and not (kind == "SYSTEM_RESPONSE" and failed):
            return
        request_id = self._match(frame, raw)
        if request_id is None:
            _logger.debug("dropped an unmatched %s frame: %.200s", kind, raw)
            return
        del self._in_flight[request_id]
        wall, mono = datetime.now(UTC), time.monotonic()
        if failed:
            self.on_event(ResponseEvent(request_id, "error", wall, mono, str(frame.get("error") or frame.get("message"))))
        else:
            self.on_event(ResponseEvent(request_id, "first_chunk", wall, mono))
            self.on_event(ResponseEvent(request_id, "complete", wall, mono))

    def _match(self, frame: dict, raw: str) -> str | None:
        """The frame's request_id; else the in-flight id found in the frame text (AK's complete reply carries none, the prompt is the id)."""
        request_id = frame.get("request_id")
        if request_id is not None:
            return request_id if request_id in self._in_flight else None
        return next((r for r in self._in_flight if r in raw), None)
