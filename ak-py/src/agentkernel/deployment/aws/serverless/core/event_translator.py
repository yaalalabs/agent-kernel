import base64
import logging
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlencode

from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


class LambdaEventTranslator:
    """API Gateway REST (v1) proxy events <-> Starlette, for the Lambda webhook host (#760).

    It builds the real ``starlette.requests.Request`` every webhook adapter reads, and turns what
    the handler produced back into the proxy response FastAPI would have sent. It holds no state.

    FastAPI and Starlette are imported at module scope, so ``deployment.aws.serverless.core`` never
    imports this module: only ``LambdaWebhookHost`` reaches it, through ``agentkernel.aws``'s lazy export.
    """

    _log = logging.getLogger("ak.aws.lambda.webhook")

    def to_request(self, event: Mapping[str, Any]) -> Request:
        """Build the Starlette request an adapter reads from an API Gateway proxy event.

        :param event: The API Gateway REST (v1) proxy event.
        :return: A request whose body is the exact bytes the platform sent.
        :raises binascii.Error: If a body flagged as base64 is not valid base64.
        """
        headers = self._headers(event)
        header_map = dict(headers)
        request_context = event.get("requestContext") or {}
        path = event.get("path") or "/"

        host = header_map.get(b"host", b"").decode("latin-1") or request_context.get("domainName")
        port = self._forwarded_port(header_map.get(b"x-forwarded-port", b""))
        source_ip = (request_context.get("identity") or {}).get("sourceIp")

        scope = {
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
        body = self._body(event)
        delivered = False

        async def receive() -> Dict[str, Any]:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(scope, receive)

    async def to_proxy_response(self, request: Optional[Request], result: Any) -> Dict[str, Any]:
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

    async def error_to_proxy_response(self, exc: Exception, request: Optional[Request] = None) -> Dict[str, Any]:
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
        self._log.error(f"Webhook request failed: {exc!r}", exc_info=exc)
        return self._proxy_response(PlainTextResponse("Internal Server Error", status_code=500))

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
    def _headers(event: Mapping[str, Any]) -> List[Tuple[bytes, bytes]]:
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
    def _proxy_response(response: Response) -> Dict[str, Any]:
        """An API Gateway proxy response carrying a Starlette response's status, headers and bytes.

        ``multiValueHeaders`` keeps repeated headers such as ``set-cookie``. A body that is not
        UTF-8 is sent as base64.
        """
        if not hasattr(response, "body"):
            raise TypeError("streaming responses are not supported on Lambda")
        headers: Dict[str, List[str]] = {}
        for name, value in response.raw_headers:
            headers.setdefault(name.decode("latin-1"), []).append(value.decode("latin-1"))
        body = bytes(response.body)
        try:
            text, is_base64 = body.decode("utf-8"), False
        except UnicodeDecodeError:
            text, is_base64 = base64.b64encode(body).decode("ascii"), True
        return {"statusCode": response.status_code, "multiValueHeaders": headers, "body": text, "isBase64Encoded": is_base64}
