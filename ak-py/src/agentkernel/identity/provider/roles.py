"""Role mapping: the one producer of ``Principal.roles``."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ...core.model import Principal
from ...core.util.factory import AKConfigError, resolve_dotted
from .base import ClaimPath, IdentityProvider, RequestContext

if TYPE_CHECKING:
    from ...core.config import _RoleMapperConfig

_BUILTIN_ROLE_MAPPERS = ["mapping"]


class RoleMapper(ABC):
    """Derives the Agent Kernel roles of a principal from what its provider asserted."""

    @abstractmethod
    def map(self, principal: Principal) -> list[str]:
        """Return the roles for ``principal``, de-duplicated, in a stable order.

        :param principal: The principal as the provider returned it (its ``roles`` are not an input).
        :return: The roles; empty when nothing applies.
        """
        raise NotImplementedError


class MappingRoleMapper(RoleMapper):
    """The built-in mapper: a dictionary from group name or listed claim value to roles, plus a pass-through claim path.

    Only the principal's ``groups`` reach ``mapping`` by default. A claim is looked up only when its
    path is listed in ``claims``, because a user sets many of their own claims (a display name, a
    sign-up username, an email address), and matching every claim value would let one of those
    grant a role. Boolean flags and nested claim objects are not mapped (Q14): a deployment whose
    provider expresses roles that way brings a ``RoleMapper`` of its own by dotted path.
    """

    def __init__(self, mapping: dict[str, list[str]], pass_through: str | None = None, claims: Iterable[str] = ()):
        """
        :param mapping: Group name or string claim value -> the roles it grants.
        :param pass_through: Dotted claim path whose string or list value becomes roles as it is, or None.
        :param claims: Claim paths whose string or list values are looked up in ``mapping`` beside the groups.
        """
        self._mapping = mapping
        self._pass_through = pass_through
        self._claims = list(claims)

    def map(self, principal: Principal) -> list[str]:
        roles: list[str] = []
        for key in [*principal.groups, *self._claim_values(principal.claims)]:
            roles.extend(self._mapping.get(key, []))
        if self._pass_through:
            roles.extend(self._strings(ClaimPath.read(principal.claims, self._pass_through)))
        return list(dict.fromkeys(roles))

    def _claim_values(self, claims: dict[str, Any]) -> Iterable[str]:
        """The string values at the listed claim paths, list items included; anything else is skipped."""
        for path in self._claims:
            yield from self._strings(ClaimPath.read(claims, path))

    @staticmethod
    def _strings(value: Any) -> list[str]:
        """A string as a one-element list, a list's string items, nothing for any other value."""
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return []


class RoleMapperFactory:
    """Creates the RoleMapper named by ``identity.role_mapper.type``."""

    _log = logging.getLogger("ak.identity.provider.roles")

    @staticmethod
    def create(config: "_RoleMapperConfig") -> RoleMapper:
        """Build the configured mapper.

        :param config: The ``identity.role_mapper`` block.
        :return: The mapper; a dotted-path mapper receives the whole block.
        :raises AKConfigError: If the type is neither the built-in nor a resolvable dotted path.
        """
        mapper_type = config.type
        RoleMapperFactory._log.info(f"Building '{mapper_type}' role mapper")
        if mapper_type.lower() == "mapping":
            return MappingRoleMapper(dict(config.mapping), config.pass_through, config.claims)
        if "." not in mapper_type:
            raise AKConfigError(
                f"unknown identity.role_mapper.type '{mapper_type}'; expected one of {_BUILTIN_ROLE_MAPPERS} or a dotted path to a RoleMapper subclass"
            )
        return resolve_dotted(mapper_type, base=RoleMapper)(config)


class MappedIdentityProvider(IdentityProvider):
    """A provider whose principals carry the roles the configured mapper derives.

    The factory wraps every provider in one when a ``role_mapper`` block exists, so each
    provider's output is mapped the same way and ``Principal.roles`` has exactly one producer:
    whatever roles the provider itself set are replaced, never merged.
    """

    def __init__(self, provider: IdentityProvider, mapper: RoleMapper):
        self._provider = provider
        self._mapper = mapper

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._provider.name

    async def authenticate(self, credential: str, context: RequestContext | None = None) -> Principal:
        principal = await self._provider.authenticate(credential, context)
        return principal.model_copy(update={"roles": self._mapper.map(principal)})

    def security_scheme(self) -> tuple[str, dict[str, Any]]:
        return self._provider.security_scheme()

    async def close(self) -> None:
        await self._provider.close()
