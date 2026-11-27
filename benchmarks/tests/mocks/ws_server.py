import asyncio
import contextlib
import json
import time
from collections import Counter
from typing import Self
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from ak_bench.load.token import TokenSigner


class MockWsServer:
    """Local stand-in for AK's WebSocket chat endpoint: CHAT_QUEUED, then after delay_s a CHAT_RESPONSE echoing the prompt (no request id).

    Like AK, a bad token (or a user in fail_connect_for) is accepted and then closed with 1008. Requests in `drop` are never
    answered, requests in `fail` get AK's enqueue-failure SYSTEM_RESPONSE FAILED and requests in `agent_error` its agent-error
    CHAT_RESPONSE {"error": ...}, both without request id or prompt as AK sends them (all three take request ids or users), and
    `duplicate` sends every reply twice.
    """

    def __init__(self, secret: str, delay_s: float = 0.0, drop=(), fail=(), agent_error=(), fail_connect_for=(), duplicate: bool = False):
        self.signer = TokenSigner(secret)
        self.delay_s = delay_s
        self.drop, self.fail, self.agent_error, self.fail_connect_for = set(drop), set(fail), set(agent_error), set(fail_connect_for)
        self.duplicate = duplicate
        self.connections: Counter[str] = Counter()  # accepted connections per user
        self.frames: Counter[str] = Counter()  # chat frames per user
        self.received: list[tuple[str, dict, float]] = []  # (user, frame, monotonic arrival)
        self.paths: list[str] = []
        self._replies: set[asyncio.Task] = set()
        self.url = ""

    async def __aenter__(self) -> Self:
        self._server = await serve(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/ws"
        return self

    async def __aexit__(self, *exc) -> None:
        for task in self._replies:
            task.cancel()
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, ws: ServerConnection) -> None:
        self.paths.append(ws.request.path)
        token = parse_qs(urlsplit(ws.request.path).query).get("token", [""])[0]
        user = token.rpartition(".")[0]
        if not user or token != self.signer.token(user) or user in self.fail_connect_for:
            await ws.close(1008, "Authentication failed")
            return
        self.connections[user] += 1
        async for raw in ws:
            frame = json.loads(raw)
            self.frames[user] += 1
            self.received.append((user, frame, time.monotonic()))
            request_id = frame["request_id"]
            await ws.send(json.dumps({"status": "SUCCESS", "subject": user, "request_id": request_id, "type": "CHAT_QUEUED"}))
            if not {request_id, user} & self.drop:
                task = asyncio.create_task(self._reply(ws, user, request_id, frame["body"]))
                self._replies.add(task)
                task.add_done_callback(self._replies.discard)

    async def _reply(self, ws: ServerConnection, user: str, request_id: str, body: dict) -> None:
        await asyncio.sleep(self.delay_s)
        if {request_id, user} & self.fail:
            reply = {"status": "FAILED", "message": "Request processing failed", "type": "SYSTEM_RESPONSE"}
        elif {request_id, user} & self.agent_error:
            reply = {"error": "agent failed", "type": "CHAT_RESPONSE"}
        else:
            reply = {"result": f"content={{'echo': '{body['prompt']}'}}", "session_id": body["session_id"], "type": "CHAT_RESPONSE"}
        with contextlib.suppress(ConnectionClosed):
            for _ in range(2 if self.duplicate else 1):
                await ws.send(json.dumps(reply))
