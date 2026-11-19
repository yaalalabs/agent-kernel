"""``GatewayHTTP``: the HTTP client every built-in gateway shares (spec §4).

It maps failures to ``UsageRetrievalError`` and logs the method and path only: never the query string (it carries
user ids), headers (they carry keys) or body.
"""

import asyncio
import logging
from typing import Any

import httpx

from ..errors import UsageRetrievalError


class _GatewayQueryRedactor(logging.Filter):
    """Strips the query string from httpx's own ``HTTP Request: <method> <url>`` line for gateway URLs."""

    def __init__(self) -> None:
        super().__init__()
        self.prefixes: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 1 and isinstance(args[1], httpx.URL) and args[1].query:
            url = str(args[1])
            if any(url.startswith(prefix) for prefix in tuple(self.prefixes)):
                record.args = (args[0], url.split("?", 1)[0], *args[2:])
        return True


_REDACTOR = _GatewayQueryRedactor()
logging.getLogger("httpx").addFilter(_REDACTOR)


class GatewayHTTP:
    """One gateway's HTTP client: JSON in and out, typed errors, paths-only logging.

    The ``httpx.AsyncClient`` is created lazily and bound to the loop that first uses it. A call from another loop
    (a sync bridge) uses a per-call client, so a client is never used on a loop it was not created on.
    """

    _log = logging.getLogger("ak.cost.gateway.http")

    def __init__(
        self,
        gateway: str,
        base_url: str,
        headers: dict[str, str] | None = None,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        :param gateway: The gateway's name, for errors and logs.
        :param base_url: Every request path is relative to it.
        :param headers: Sent on every request, typically the auth header.
        :param timeout: Seconds a request may take.
        :param transport: An httpx transport for tests; None uses the network.
        """
        self._gateway = gateway
        self._base_url = base_url.rstrip("/")
        self._headers = dict(headers or {})
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        _REDACTOR.prefixes.add(str(httpx.URL(self._base_url)))  # normalised as httpx logs it (lower-case host)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Send one request and return its parsed JSON body.

        :param path: Relative to the base URL, without a query string; pass the query as ``params``.
        :param headers: Per-request headers over the client's, e.g. an auth header resolved per call.
        :raises UsageRetrievalError: On a connect, timeout, decoding or redirect error, a non-2xx status (``auth`` set for 401 and 403),
            or a body that is not JSON.
        """
        loop = asyncio.get_running_loop()
        if self._client is None or self._loop is None or self._loop.is_closed():
            self._client, self._loop = self._new_client(), loop
        if self._loop is loop:
            return await self._send(self._client, method, path, params, json, headers)
        async with self._new_client() as client:
            return await self._send(client, method, path, params, json, headers)

    async def close(self) -> None:
        """Close the shared client; one bound to another (possibly dead) loop is dropped instead."""
        client, self._client = self._client, None
        if client is not None and self._loop is asyncio.get_running_loop():
            await client.aclose()

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=self._timeout, transport=self._transport)

    async def _send(
        self, client: httpx.AsyncClient, method: str, path: str, params: dict[str, Any] | None, json: Any, headers: dict[str, str] | None
    ) -> Any:
        where = f"gateway '{self._gateway}' {method} {path}"
        try:
            response = await client.request(method, path, params=params, json=json, headers=headers)
        except httpx.RequestError as exc:  # transport, decoding and redirect failures
            self._log.warning(f"{where} failed: {type(exc).__name__}")
            raise UsageRetrievalError(f"{where} failed: {type(exc).__name__}", gateway=self._gateway, path=path) from exc
        status = response.status_code
        self._log.debug(f"{where} -> {status}")
        if not response.is_success:
            auth = status in (401, 403)
            self._log.warning(f"{where} returned {status}")
            raise UsageRetrievalError(
                f"{where} returned {status}", gateway=self._gateway, path=path, status=status, auth=auth, detail=response.text[:500]
            )
        try:
            return response.json()
        except ValueError:
            self._log.warning(f"{where} returned a body that is not JSON")
            raise UsageRetrievalError(f"{where} returned a body that is not JSON", gateway=self._gateway, path=path, status=status) from None
