"""Identity for Agent Kernel: who a request acts as, and the roles that follow from it.

Names resolve lazily through the PEP 562 ``__getattr__`` below, the ``agentkernel.knowledgebase``
pattern, so that ``import agentkernel.identity`` costs one module import and pulls no optional
SDK once the OIDC family and its JWT dependency land here.

The contract suites live in ``agentkernel.identity.provider.testing`` and are imported explicitly
from test code (they depend on pytest), so they are deliberately not re-exported.
"""

import importlib
from typing import TYPE_CHECKING, Any

# name -> submodule providing it, resolved lazily by __getattr__.
_LAZY_EXPORTS = {
    "AuthenticationError": ".errors",
    "IdentityProvider": ".provider.base",
    "RequestContext": ".provider.base",
    "IdentityProviderFactory": ".provider.factory",
    "StaticIdentityProvider": ".provider.static",
    "OIDCIdentityProvider": ".provider.oidc",
    "JWKSCache": ".provider.oidc",
    "CognitoIdentityProvider": ".provider.cognito",
    "EntraIdentityProvider": ".provider.entra",
    "FirebaseIdentityProvider": ".provider.firebase",
    "RoleMapper": ".provider.roles",
    "MappingRoleMapper": ".provider.roles",
    "MappedIdentityProvider": ".provider.roles",
    "RoleMapperFactory": ".provider.roles",
}

__all__ = sorted(_LAZY_EXPORTS)

# Not executed at runtime (preserves laziness); lets type checkers and IDEs resolve the names.
if TYPE_CHECKING:
    from .errors import AuthenticationError
    from .provider.base import IdentityProvider, RequestContext
    from .provider.cognito import CognitoIdentityProvider
    from .provider.entra import EntraIdentityProvider
    from .provider.factory import IdentityProviderFactory
    from .provider.firebase import FirebaseIdentityProvider
    from .provider.oidc import JWKSCache, OIDCIdentityProvider
    from .provider.roles import MappedIdentityProvider, MappingRoleMapper, RoleMapper, RoleMapperFactory
    from .provider.static import StaticIdentityProvider


def __getattr__(name: str) -> Any:
    try:
        module_name = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
