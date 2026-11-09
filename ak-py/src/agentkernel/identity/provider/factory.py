"""IdentityProviderFactory: builds the IdentityProvider named by ``identity.provider.type``."""

import logging
from threading import RLock
from typing import TYPE_CHECKING, ClassVar

from ...core.config import AKConfig
from ...core.util.factory import AKConfigError, resolve_dotted
from .base import IdentityProvider

if TYPE_CHECKING:
    from ...core.config import _IdentityConfig

_BUILTIN_PROVIDERS = ["oidc", "cognito", "entra", "firebase", "static"]
# Named in the config today, shipped with the OIDC provider family (plan iteration 5).
_PENDING_PROVIDERS = ("oidc", "cognito", "entra", "firebase")


class IdentityProviderFactory:
    """Creates the configured identity provider, wrapped with the role mapper when one is configured."""

    _instance: ClassVar[IdentityProvider | None] = None
    _lock: ClassVar[RLock] = RLock()
    _log = logging.getLogger("ak.identity.provider.factory")

    @staticmethod
    def create(identity_config: "_IdentityConfig") -> IdentityProvider:
        """Build the provider the ``identity`` block names.

        :param identity_config: The ``identity`` block.
        :return: The provider, wrapped in a ``MappedIdentityProvider`` when ``role_mapper`` is set.
        :raises AKConfigError: If the type is neither a built-in nor a resolvable dotted path, or
            the provider's own settings are unusable.
        """
        provider_type = identity_config.provider.type
        IdentityProviderFactory._log.info(f"Building '{provider_type}' identity provider")
        key = provider_type.lower()
        provider: IdentityProvider
        if key in _PENDING_PROVIDERS:
            raise AKConfigError(f"identity.provider.type: {key} arrives with the OIDC provider family; use static or a dotted path until then")
        elif key == "static":
            from .static import StaticIdentityProvider

            provider = StaticIdentityProvider.from_config(identity_config.provider)
        elif "." in provider_type:
            # A bring-your-own provider receives the whole provider block.
            provider = resolve_dotted(provider_type, base=IdentityProvider)(identity_config.provider)
        else:
            raise AKConfigError(
                f"unknown identity provider type '{provider_type}'; expected one of {_BUILTIN_PROVIDERS} or a dotted path to an IdentityProvider subclass"
            )
        if identity_config.role_mapper is not None:
            from .roles import MappedIdentityProvider, RoleMapperFactory

            provider = MappedIdentityProvider(provider, RoleMapperFactory.create(identity_config.role_mapper))
        return provider

    @classmethod
    def get(cls) -> IdentityProvider | None:
        """Return the process-wide provider, or None when no ``identity`` block is configured.

        The None return is the enabled-check: every surface that authenticates reads it once.

        :return: The shared provider, built on first access, or None.
        :raises AKConfigError: If the block cannot be built into a provider.
        """
        config = AKConfig.get().identity
        if config is None:
            return None
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls.create(config)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared provider so the next get() rebuilds from config. Intended for testing."""
        with cls._lock:
            cls._instance = None
