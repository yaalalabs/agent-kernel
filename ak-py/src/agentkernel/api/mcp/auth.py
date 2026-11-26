"""MCP authentication over the configured identity provider (spec #603, section 8.6).

FastMCP owns the HTTP side of authentication: it reads the bearer token, asks a ``TokenVerifier``
for an access token, answers 401 with the resource metadata when the verifier declines, and
makes the access token reachable from a tool call through ``get_access_token()``. This module
supplies that verifier over Agent Kernel's own provider and picks the ``auth`` object the
server is built with, so MCP callers are authenticated exactly as REST callers are.
"""

import logging
from typing import Any
from urllib.parse import urlsplit

from fastmcp.server.auth.auth import AuthProvider, RemoteAuthProvider, TokenVerifier
from mcp.server.auth.provider import AccessToken
from pydantic import AnyHttpUrl

from ...core.config import AKConfig
from ...core.model import Principal
from ...identity.errors import AuthenticationError
from ...identity.provider.base import IdentityProvider, RequestContext
from ...identity.provider.factory import IdentityProviderFactory

# The claim the verifier stores the principal under. FastMCP copies the verifier's token into its
# own AccessToken before a tool sees it, keeping only the SDK fields, so a subclass field does not
# survive the hop; the claims do.
PRINCIPAL_CLAIM = "ak.principal"


class AKAccessToken(AccessToken):
    """The SDK's access token plus the principal it authenticated.

    The ``principal`` field serves in-process readers; what reaches a tool is the
    ``PRINCIPAL_CLAIM`` entry in ``claims``, read back through ``principal_of``.
    """

    principal: Principal

    @staticmethod
    def principal_of(token: AccessToken | None) -> Principal:
        """The principal a call's access token carries, or the anonymous principal.

        :param token: What ``get_access_token()`` returned: None on an open server, this class in
            process, or FastMCP's rebuilt token (SDK fields only) over HTTP.
        :return: The verifier's principal when the token carries one, else the anonymous principal
            (a token another verifier minted authenticated nobody Agent Kernel knows).
        """
        if isinstance(token, AKAccessToken):
            return token.principal
        data = token.claims.get(PRINCIPAL_CLAIM) if token is not None and token.claims else None
        return Principal.model_validate(data) if isinstance(data, dict) else Principal.anonymous()


class AKTokenVerifier(TokenVerifier):
    """Verifies a bearer token through the configured identity provider.

    A token the provider accepts becomes an ``AKAccessToken`` whose SDK fields mirror the
    principal (``subject`` and ``client_id`` the subject, ``claims`` the principal's plus the
    principal itself under ``PRINCIPAL_CLAIM``, ``expires_at`` the ``exp`` claim when the provider
    kept one); a refused token is ``None``, which FastMCP turns into a 401. The provider's reason
    stays in the log.
    """

    _log = logging.getLogger("ak.api.mcp.auth")

    def __init__(self, provider: IdentityProvider):
        """
        :param provider: The configured identity provider.
        """
        super().__init__()
        self._provider = provider

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self._provider.authenticate(token, RequestContext(path="/mcp", http_method="POST"))
        except AuthenticationError as exc:
            self._log.info(f"Refused MCP credential: {exc}")
            return None
        expires_at = principal.claims.get("exp")
        return AKAccessToken(
            token=token,
            client_id=principal.subject,
            scopes=[],
            expires_at=expires_at if isinstance(expires_at, int) else None,
            subject=principal.subject,
            claims={**principal.claims, PRINCIPAL_CLAIM: principal.model_dump(mode="json")},
            principal=principal,
        )


class AKMCPAuthProvider:
    """Selects FastMCP's ``auth`` for the configured identity provider."""

    DISCOVERY_SUFFIX = "/.well-known/openid-configuration"

    @staticmethod
    def from_config() -> AuthProvider | None:
        """Build the server's ``auth`` object from the ``identity`` block.

        :return: None without an identity block (MCP stays open); the verifier alone for a bearer
            provider; for a provider advertising an ``openIdConnect`` scheme, the verifier wrapped
            in a ``RemoteAuthProvider`` that publishes the RFC 9728 resource metadata naming the
            issuer as the authorization server, for the public ``mcp.url`` resource (``RESTAPI``
            serves that document at the app root, where the 401 points).
        """
        provider = IdentityProviderFactory.get()
        if provider is None:
            return None
        verifier = AKTokenVerifier(provider)
        scheme, settings = provider.security_scheme()
        discovery: Any = settings.get("url") if scheme == "openIdConnect" else None
        if not isinstance(discovery, str):
            return verifier
        issuer = discovery.removesuffix(AKMCPAuthProvider.DISCOVERY_SUFFIX)
        # The public URL, never the bind address: http://0.0.0.0:8000 names nothing a client reaches.
        resource = AKConfig.get().mcp.url.rstrip("/")
        parts = urlsplit(resource)
        return RemoteAuthProvider(
            token_verifier=verifier,
            authorization_servers=[AnyHttpUrl(issuer)],
            base_url=f"{parts.scheme}://{parts.netloc}",
            resource_base_url=resource,
        )
