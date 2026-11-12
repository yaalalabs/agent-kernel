"""The IdentityProvider seam: turning an inbound credential into a Principal."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel

from ...core.model import Principal


class RequestContext(BaseModel):
    """What a provider may know about the request a credential arrived on.

    Three optional fields, the shape the removed ``agentkernel.auth`` validation context had, so a
    provider that signs or scopes per route can see where the credential was presented.
    """

    path: str | None = None
    http_method: str | None = None
    headers: dict[str, Any] | None = None


class ClaimPath:
    """Reads a dotted path out of a claims mapping, the way the claim-path settings name one."""

    @staticmethod
    def read(payload: Mapping[str, Any], path: str) -> Any:
        """Return the value at ``path`` in ``payload``, or None when any segment is missing.

        The whole path is tried as one claim name first: Auth0 namespaces its custom claims as
        URLs (``https://acme.com/roles``), which contain dots but are single keys. Only when no
        such key exists is the path split on dots and walked.

        :param payload: The claims (a validated token payload, or ``Principal.claims``).
        :param path: A claim name, or dotted segments such as ``realm_access.roles``.
        :return: The value, or None when the path does not resolve to one.
        """
        if path in payload:
            return payload[path]
        current: Any = payload
        for segment in path.split("."):
            if not isinstance(current, Mapping) or segment not in current:
                return None
            current = current[segment]
        return current


class IdentityProvider(ABC):
    """A backend that authenticates an inbound credential and says who presented it.

    Providers return the facts they can vouch for (subject, groups, claims, the namespace the
    subject is unique within) and never write ``roles``: the configured ``RoleMapper`` is the one
    producer of those. A provider reads no configuration in its methods; the factory hands every
    setting to the constructor.
    """

    # The short name the factory selects the provider by, and the value of ``Principal.provider``.
    name: ClassVar[str]

    @abstractmethod
    async def authenticate(self, credential: str, context: RequestContext | None = None) -> Principal:
        """Validate ``credential`` and return the principal it authenticates.

        :param credential: The raw credential as the surface extracted it (a bearer token, a static secret).
        :param context: Where the credential was presented, when the surface knows.
        :return: A non-anonymous principal with ``provider`` set to this provider's name.
        :raises AuthenticationError: If the credential is not accepted; the reason is logged, never returned.
        """
        raise NotImplementedError

    def security_scheme(self) -> tuple[str, dict[str, Any]]:
        """The security scheme an agent card advertises for this provider.

        :return: A scheme name and its settings; bearer with no settings unless a provider says otherwise.
        """
        return ("bearer", {})

    async def close(self) -> None:
        """Release any client the provider holds; a no-op unless a provider opens one."""
        return None
