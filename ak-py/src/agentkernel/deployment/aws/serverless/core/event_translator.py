import asyncio
import base64
import logging
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message


class LambdaEventTranslator:
    """API Gateway REST (v1) proxy events <-> Starlette, for the Lambda hosts: the webhook host (#760) and the protocol host (#932).

    It builds the real ``starlette.requests.Request`` every webhook adapter reads, or runs a whole ASGI
    app on the event, and turns what the handler produced back into the proxy response FastAPI would
    have sent. It holds no state.

    FastAPI and Starlette are imported at module scope, so ``deployment.aws.serverless.core`` never
    imports this module: only the Lambda hosts reach it, through ``agentkernel.aws``'s lazy exports.
    """

    _log = logging.getLogger("ak.aws.lambda.webhook")

    def to_request(self, event: Mapping[str, Any]) -> Request:
        """Build the Starlette request an adapter reads from an API Gateway proxy event.

        :param event: The API Gateway REST (v1) proxy event.
        :return: A request whose body is the exact bytes the platform sent.
        :raises binascii.Error: If a body flagged as base64 is not valid base64.
        """
        scope = self._scope(event, event.get("path") or "/")
        body = self._body(event)
        delivered = False

        async def receive() -> dict[str, Any]:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(scope, receive)

    async def call_app(self, app: ASGIApp, event: Mapping[str, Any], app_path: str) -> dict[str, Any]:
        """Run a whole ASGI app (FastAPI, with its routing and middleware) on an API Gateway proxy event.

        ``to_request`` hands one endpoint a request; this hands an app the same request, as the ASGI
        server would, and buffers what it answers into one proxy response. The app sees ``app_path``
        rather than the event's path, so a host can strip the API Gateway prefix first.

        A streamed answer is buffered whole: MCP answers a tool call as one ``text/event-stream`` body,
        and a proxy response is a single body. Streaming to the client is out of scope here (#894).

        ``receive`` gives the app the body once. Any later call waits until the response is complete
        and then reports ``http.disconnect``, so an app that listens for a client disconnect while it
        streams (Starlette does) is not told the client left before it has answered.

        :param app: The ASGI app, for example the one ``RESTAPI.build_app`` returns.
        :param event: The API Gateway REST (v1) proxy event.
        :param app_path: The path the app routes on.
        :return: The API Gateway proxy response.
        :raises RuntimeError: If the app returns without starting a response.
        :raises binascii.Error: If a body flagged as base64 is not valid base64.
        """
        scope = self._scope(event, app_path)
        body = self._body(event)
        delivered = False
        response_complete = asyncio.Event()
        status: int | None = None
        raw_headers: list[tuple[bytes, bytes]] = []
        chunks: list[bytes] = []

        async def receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await response_complete.wait()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            nonlocal status, raw_headers
            if message["type"] == "http.response.start":
                status = message["status"]
                raw_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    response_complete.set()

        try:
            await app(scope, receive, send)
        finally:
            response_complete.set()  # release a disconnect listener the app left waiting
        if status is None:
            raise RuntimeError("The ASGI app returned without starting a response")
        return self.proxy_response_from_parts(status, raw_headers, b"".join(chunks))

    async def to_proxy_response(self, request: Request | None, result: Any) -> dict[str, Any]:
        """Turn an endpoint's return value into the proxy response FastAPI would have sent.

        A Starlette ``Response`` (an SDK's own, such as Bolt's) passes through as it is. Any other
        value is encoded as FastAPI encodes a route with no response model: ``jsonable_encoder``,
        then the default ``JSONResponse``, with status 200.

        :param request: The request the endpoint served; unused, kept for FastAPI's call shape.
        :param result: What the endpoint returned.
        :return: The API Gateway proxy response.
        :raises TypeError: For a streaming response, which a proxy response cannot carry.
        """
        response = result if isinstance(result, Response) else JSONResponse(jsonable_encoder(result))
        return self._proxy_response(response)

    async def error_to_proxy_response(self, exc: Exception, request: Request | None = None) -> dict[str, Any]:
        """Turn an exception into the proxy response FastAPI would have sent.

        An ``HTTPException`` goes through FastAPI's own handler: its status, its headers, and
        ``{"detail": ...}``, or no body for a status that allows none. Anything else is logged
        and answered with the plain-text 500 Starlette sends, never the exception text.

        :param exc: The exception the request or the endpoint raised.
        :param request: The request, when it was built; FastAPI's handler ignores it.
        :return: The API Gateway proxy response.
        """
        if isinstance(exc, HTTPException):
            return self._proxy_response(await http_exception_handler(request, exc))
        self._log.error(f"Lambda host request failed: {exc!r}", exc_info=exc)
        return self._proxy_response(PlainTextResponse("Internal Server Error", status_code=500))

    def _scope(self, event: Mapping[str, Any], path: str) -> dict[str, Any]:
        """The ASGI scope for a proxy event, serving ``path``.

        The one place the event's method, headers, query string, server and client become a scope,
        so a request handed to an endpoint and one handed to an app read the same values.

        :param event: The API Gateway REST (v1) proxy event.
        :param path: The path the scope carries: the event's own for ``to_request``, the app's for ``call_app``.
        :return: The ASGI HTTP scope.
        """
        headers = self._headers(event)
        header_map = dict(headers)
        request_context = event.get("requestContext") or {}

        host = header_map.get(b"host", b"").decode("latin-1") or request_context.get("domainName")
        port = self._forwarded_port(header_map.get(b"x-forwarded-port", b""))
        source_ip = (request_context.get("identity") or {}).get("sourceIp")

        return {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": str(event.get("httpMethod") or "GET").upper(),
            "scheme": self._first_value(header_map.get(b"x-forwarded-proto", b"")) or "https",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "root_path": "",
            "query_string": self._query_string(event),
            "headers": headers,
            "server": (host, port) if host else None,
            "client": (source_ip, 0) if source_ip else None,
        }

    @staticmethod
    def _first_value(value: bytes) -> str:
        """The first entry of a forwarded header: a proxy in front of API Gateway may append its own."""
        return value.decode("latin-1").split(",", 1)[0].strip()

    @classmethod
    def _forwarded_port(cls, value: bytes) -> int:
        """The port from ``x-forwarded-port``, or 443 when it is absent or not a number."""
        try:
            return int(cls._first_value(value))
        except ValueError:
            return 443

    @staticmethod
    def _body(event: Mapping[str, Any]) -> bytes:
        """The exact body bytes: signature checks hash them."""
        body = event.get("body")
        if body is None:
            return b""
        if event.get("isBase64Encoded"):
            return base64.b64decode(body, validate=True)
        return body.encode("utf-8")

    @staticmethod
    def _headers(event: Mapping[str, Any]) -> list[tuple[bytes, bytes]]:
        """ASGI headers from ``multiValueHeaders``, falling back to ``headers``.

        Names are lower-cased, the ASGI rule that makes Starlette's lookup case-insensitive.
        """
        multi_value = event.get("multiValueHeaders")
        pairs = (
            [(name, value) for name, values in multi_value.items() for value in values or []]
            if multi_value
            else list((event.get("headers") or {}).items())
        )
        return [(name.lower().encode("latin-1"), LambdaEventTranslator._encode_header_value(str(value))) for name, value in pairs]

    @staticmethod
    def _encode_header_value(value: str) -> bytes:
        try:
            return value.encode("latin-1")
        except UnicodeEncodeError:
            return value.encode("utf-8")

    @staticmethod
    def _query_string(event: Mapping[str, Any]) -> bytes:
        """The query string from ``multiValueQueryStringParameters``, falling back to ``queryStringParameters``.

        A valid proxy event can carry only the single-value map, and Meta's ``hub.challenge``
        handshake is read from the query.
        """
        multi_value = event.get("multiValueQueryStringParameters")
        if multi_value:
            return urlencode([(name, value) for name, values in multi_value.items() for value in values or []]).encode("ascii")
        return urlencode(list((event.get("queryStringParameters") or {}).items())).encode("ascii")

    @staticmethod
    def _proxy_response(response: Response) -> dict[str, Any]:
        """An API Gateway proxy response carrying a Starlette response's status, headers and bytes.

        ``multiValueHeaders`` keeps repeated headers such as ``set-cookie``. A body that is not
        UTF-8 is sent as base64.
        """
        if not hasattr(response, "body"):
            raise TypeError("streaming responses are not supported on Lambda")
        return LambdaEventTranslator.proxy_response_from_parts(response.status_code, response.raw_headers, bytes(response.body))

    @staticmethod
    def proxy_response_from_parts(status: int, raw_headers: Sequence[tuple[bytes, bytes]], body: bytes) -> dict[str, Any]:
        """The one place an API Gateway proxy response is built: a status, raw ASGI headers and the whole body.

        ``multiValueHeaders`` keeps repeated headers such as ``set-cookie``. A body that is not
        UTF-8 is sent as base64.

        :param status: The HTTP status code.
        :param raw_headers: The response headers as ASGI sends them, name and value as bytes.
        :param body: The whole response body.
        :return: The API Gateway proxy response.
        """
        headers: dict[str, list[str]] = {}
        for name, value in raw_headers:
            headers.setdefault(name.decode("latin-1"), []).append(value.decode("latin-1"))
        try:
            text, is_base64 = body.decode("utf-8"), False
        except UnicodeDecodeError:
            text, is_base64 = base64.b64encode(body).decode("ascii"), True
        return {"statusCode": status, "multiValueHeaders": headers, "body": text, "isBase64Encoded": is_base64}
