"""EntraIdentityProvider: Microsoft Entra ID (v2.0) tokens."""

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar

from ...core.util.factory import AKConfigError
from ..errors import AuthenticationError
from .oidc import JWKSCache, OIDCIdentityProvider

if TYPE_CHECKING:
    from ...core.config import _IdentityProviderConfig


class EntraIdentityProvider(OIDCIdentityProvider):
    """OIDC with Entra's issuer, ``oid`` as the subject and the ``tid`` tenant check.

    Entra's ``roles`` and ``wids`` stay in ``claims`` for the role mapper. A token carrying the
    groups-overage marker (``_claim_names``) names more groups than fit in a token; the provider
    yields no groups for it and warns once per process, since resolving them needs a Graph call
    this provider does not make.
    """

    name = "entra"
    _overage_warned: ClassVar[bool] = False
    _log = logging.getLogger("ak.identity.provider.entra")

    def __init__(
        self,
        tenant_id: str,
        audience: str,
        *,
        jwks_uri: str | None = None,
        algorithms: Iterable[str] | None = None,
        leeway: int = 30,
        required_claims: Iterable[str] = (),
        subject_claim: str = "oid",
        groups_claim: str = "groups",
        jwks: JWKSCache | None = None,
    ):
        """
        :param tenant_id: The Entra tenant; forms the issuer and must equal a token's ``tid``.
        :param audience: The application id a token must be issued for.
        """
        super().__init__(
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            audience,
            jwks_uri=jwks_uri,
            algorithms=algorithms,
            leeway=leeway,
            required_claims=required_claims,
            subject_claim=subject_claim,
            groups_claim=groups_claim,
            jwks=jwks,
        )
        self._tenant_id = tenant_id

    @classmethod
    def from_config(cls, config: "_IdentityProviderConfig") -> "EntraIdentityProvider":
        if config.entra is None:
            raise AKConfigError("identity.provider.type entra requires the identity.provider.entra block")
        if not config.audience:
            raise AKConfigError("identity.provider.type entra requires identity.provider.audience (the application id)")
        return cls(
            config.entra.tenant_id,
            config.audience,
            jwks_uri=config.jwks_uri,
            algorithms=config.algorithms,
            leeway=config.leeway,
            required_claims=config.required_claims,
            subject_claim=cls._claim_path(config.claims, "subject", "oid"),
            groups_claim=cls._claim_path(config.claims, "groups", "groups"),
        )

    def _check(self, payload: dict[str, Any]) -> None:
        if payload.get("tid") != self._tenant_id:
            raise AuthenticationError("the token's tid is not the configured tenant")

    def _groups(self, payload: dict[str, Any]) -> list[str]:
        if "_claim_names" in payload:
            if not EntraIdentityProvider._overage_warned:
                EntraIdentityProvider._overage_warned = True
                self._log.warning(
                    "An Entra token carries the groups overage marker (_claim_names); its groups are read as none. Map roles from app roles or a dotted-path RoleMapper that resolves groups through Microsoft Graph"
                )
            return []
        return super()._groups(payload)
