"""RequestAuthenticator: the one place a surface turns an inbound credential into the request's principal."""

import contextvars
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, ClassVar

from ...core.model import Principal
from ..errors import AuthenticationError
from .base import IdentityProvider, RequestContext
from .factory import IdentityProviderFactory

if TYPE_CHECKING:
    from starlette.requests import HTTPConnection

# The challenge a 401 carries so a client knows which scheme to retry with (RFC 6750 section 3).
BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}
# The close code a WebSocket gets for a refused credential (policy violation).
WS_POLICY_VIOLATION = 1008


class RequestAuthenticator:
    """Shared bearer-header and token extraction over the configured identity provider.

    Every HTTP and WebSocket surface authenticates through this class, so header parsing, the
    anonymous rules and the 401 details exist once. Without a provider (no ``identity`` block)
    every request is the anonymous principal and a header is ignored; with one, no credential is
    anonymous too, and a present credential must validate. Which routes refuse the anonymous
    principal is the handlers' decision, not this class's.
    """

    # The request's principal for code that holds no Request (the A2A executor reads it).
    _current: ClassVar[contextvars.ContextVar[Principal | None]] = contextvars.ContextVar("ak_request_principal", default=None)
    _log = logging.getLogger("ak.identity.provider.request")

    def __init__(self, provider: IdentityProvider | None, credentials: Any | None = None, inbound_ttl: int = 300):
        """
        :param provider: The configured provider, or None when no ``identity`` block exists.
        :param credentials: The credential store the inbound credential is retained in; None until the
            credentials capability lands (plan iteration 24), when ``credential_ref`` minting arrives with it.
        :param inbound_ttl: Seconds a request-scoped credential outlives its request once retention exists.
        """
        self._provider = provider
        self._credentials = credentials
        self._inbound_ttl = inbound_ttl

    @property
    def provider(self) -> IdentityProvider | None:
        """The configured provider, or None when no ``identity`` block exists (every request is anonymous)."""
        return self._provider

    @classmethod
    def from_config(cls) -> "RequestAuthenticator":
        """Build the authenticator over the configured provider, or over none when the ``identity`` block is absent.

        :return: The authenticator.
        :raises AKConfigError: If the ``identity`` block cannot be built into a provider.
        """
        return cls(IdentityProviderFactory.get())

    async def authenticate_bearer(self, header: str | None, context: RequestContext) -> Principal:
        """Authenticate an ``Authorization`` header.

        :param header: The header value, or None when the request carries none.
        :param context: Where the credential was presented.
        :return: The provider's principal, or the anonymous principal when there is no header or no
            provider. Without a provider the header is not parsed at all, so a malformed or non-bearer
            one (a proxy's Basic credential) is ignored like any other.
        :raises AuthenticationError: If the header is not ``Bearer <token>`` (``public_detail``
            ``Invalid authorization header``) or the provider refuses the token (``Unauthorized``).
        """
        if header is None or self._provider is None:
            return Principal.anonymous()
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("the authorization header is not 'Bearer <token>'", public_detail="Invalid authorization header")
        return await self.authenticate_token(token, context)

    async def authenticate_token(self, token: str | None, context: RequestContext) -> Principal:
        """Authenticate a bare token (a WebSocket query parameter, a CLI flag).

        :param token: The token, or None when none was presented.
        :param context: Where the credential was presented.
        :return: The provider's principal, or the anonymous principal when there is no token or no provider.
        :raises AuthenticationError: If the provider refuses the token.
        """
        if self._provider is None or token is None or not token.strip():
            return Principal.anonymous()
        return await self._provider.authenticate(token.strip(), context)

    def dependency(self) -> Callable[["HTTPConnection"], Coroutine[Any, Any, Principal]]:
        """The FastAPI dependency that puts the request's principal on ``state.principal``.

        Async, so it runs in the request's task and the contextvar it sets is what the endpoint
        and ``current()`` read. It takes the ``HTTPConnection`` FastAPI injects for HTTP and
        WebSocket scopes alike, so a WebSocket route on a dependency-guarded router is served
        rather than crashing on a missing ``Request``. An ``AuthenticationError`` is logged with
        its reason and the path, then answered with only the error's public detail: a 401 with
        ``WWW-Authenticate: Bearer`` (RFC 6750 section 3) over HTTP, a 1008 close on a WebSocket.

        :return: The dependency callable, to wrap in ``Depends``.
        """
        # Imported here, not at module level: the Lambda authorizer and WebSocket connection handler
        # authenticate through this class too, and their packages carry no FastAPI.
        from fastapi import HTTPException, WebSocketException
        from starlette.requests import HTTPConnection

        async def identity_dependency(connection: HTTPConnection) -> Principal:
            method = connection.scope.get("method")
            context = RequestContext(path=connection.url.path, http_method=method, headers=dict(connection.headers))
            try:
                principal = await self.authenticate_bearer(connection.headers.get("authorization"), context)
            except AuthenticationError as exc:
                self._log.info(f"Refused credential on {method or 'WEBSOCKET'} {connection.url.path}: {exc}")
                if connection.scope["type"] == "websocket":
                    raise WebSocketException(code=WS_POLICY_VIOLATION, reason=exc.public_detail) from exc
                raise HTTPException(status_code=401, detail=exc.public_detail, headers=BEARER_CHALLENGE) from exc
            connection.state.principal = principal
            RequestAuthenticator._current.set(principal)
            return principal

        return identity_dependency

    @classmethod
    def current(cls) -> Principal | None:
        """The principal the identity dependency established for the running request, or None outside one."""
        return cls._current.get()

    async def release(self, principal: Principal) -> None:
        """Drop the retained inbound credential of ``principal``; a no-op until the credentials capability lands."""
        return None
