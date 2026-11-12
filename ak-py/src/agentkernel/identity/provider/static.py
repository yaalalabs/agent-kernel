"""StaticIdentityProvider: a configured map of secret-resolved credentials to principals."""

import hmac
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ...core.model import Principal
from ...core.util.factory import AKConfigError
from ...secret import SecretManager, SecretNotFoundError
from ..errors import AuthenticationError
from .base import IdentityProvider, RequestContext

if TYPE_CHECKING:
    from ...core.config import _IdentityProviderConfig


class StaticIdentityProvider(IdentityProvider):
    """The development, test and CLI provider: each configured credential authenticates one principal.

    The block names a secret key per principal; the credential value is resolved through the secret
    capability at construction, so it is never written in YAML. Authentication compares the
    presented credential against every resolved value in constant time and yields a principal in
    the ``static`` namespace.
    """

    name = "static"
    NAMESPACE = "static"

    _log = logging.getLogger("ak.identity.provider.static")

    def __init__(self, principals: Mapping[str, Mapping[str, Any]], secrets: SecretManager | None = None):
        """Resolve every credential and build the principal each one authenticates.

        :param principals: Credential secret key -> principal fields (subject, kind, groups, roles, claims).
        :param secrets: The secret manager to resolve the keys through; the process-wide one when omitted.
        :raises AKConfigError: If there are no principals, a key is malformed or has no secret, or two
            principals share a credential value.
        """
        if not principals:
            # A typo such as ``static: {principal: ...}`` is dropped by the model and leaves the map
            # empty: a provider that would 401 every caller is a startup error, not a quiet one.
            raise AKConfigError("identity.provider.static has no principals; list at least one under static.principals")
        manager = secrets if secrets is not None else SecretManager.current()
        self._entries: list[tuple[bytes, Principal]] = []
        seen: dict[bytes, str] = {}
        for key, fields in principals.items():
            try:
                value = manager.get(key)
            except SecretNotFoundError as exc:
                raise AKConfigError(f"identity.provider.static.principals: secret '{key}' not found: {exc}") from exc
            except ValueError as exc:
                raise AKConfigError(f"identity.provider.static.principals: '{key}' is not a secret key: {exc}") from exc
            encoded = (value or "").encode("utf-8")
            if encoded in seen:
                raise AKConfigError(f"identity.provider.static.principals: '{key}' and '{seen[encoded]}' resolve to the same credential")
            seen[encoded] = key
            self._entries.append((encoded, Principal(**fields, provider=self.name, namespace=self.NAMESPACE)))
        self._log.info(f"Static identity provider holds {len(self._entries)} principal(s)")

    @classmethod
    def from_config(cls, config: "_IdentityProviderConfig", secrets: SecretManager | None = None) -> "StaticIdentityProvider":
        """Build the provider from an ``identity.provider`` block of type ``static``.

        :param config: The provider block; its ``static`` section is required by the config validator.
        :param secrets: The secret manager to resolve the keys through; the process-wide one when omitted.
        :return: The provider.
        :raises AKConfigError: As the constructor.
        """
        if config.static is None:
            raise AKConfigError("identity.provider.type static requires the identity.provider.static block")
        return cls({key: entry.model_dump() for key, entry in config.static.principals.items()}, secrets=secrets)

    async def authenticate(self, credential: str, context: RequestContext | None = None) -> Principal:
        presented = credential.encode("utf-8")
        matched: Principal | None = None
        # Every entry is compared, match or not, so the time taken does not say which entry matched.
        for value, principal in self._entries:
            if hmac.compare_digest(value, presented):
                matched = principal
        if matched is None:
            raise AuthenticationError("no static principal matches the presented credential")
        return matched
