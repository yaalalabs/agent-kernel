"""AuthorizerFactory: builds the Authorizer named by ``authorization.type``."""

import logging
from collections.abc import Callable, Mapping
from threading import RLock
from typing import TYPE_CHECKING, ClassVar

from ...core.config import AKConfig
from ...core.model import AccessLevel, AgentDescriptor
from ...core.tool import SystemToolFactory
from ...core.util.factory import AKConfigError, resolve_dotted
from .base import Authorizer

if TYPE_CHECKING:
    from ...core.config import _AuthorizationConfig

_BUILTIN_AUTHORIZERS = ["static"]
# Engines the design names. Each gets its branch when its adapter lands; until then the name is refused
# with where to go, instead of being read as a misspelt type.
_RESERVED_ENGINES = ("casbin", "openfga", "cedar", "authzen")


class AuthorizerFactory:
    """Creates the configured authorizer, and holds the one a process shares."""

    _instance: ClassVar[Authorizer | None] = None
    _lock: ClassVar[RLock] = RLock()
    _log = logging.getLogger("ak.identity.authz.factory")

    @staticmethod
    def create(
        authorization_config: "_AuthorizationConfig",
        descriptor_lookup: Callable[[], list[AgentDescriptor]],
        system_tiers: Callable[[str], Mapping[str, AccessLevel]] | None = None,
    ) -> Authorizer:
        """Build the authorizer the ``authorization`` block names.

        :param authorization_config: The ``authorization`` block.
        :param descriptor_lookup: Returns every descriptor the registry knows; what the static backend
            resolves a ``tag:`` entry against.
        :param system_tiers: Returns, for an agent id, the tier each system tool on that agent declares;
            what the static backend falls back to for a tool the policy gives no tier.
        :return: The authorizer. A bring-your-own one (a dotted-path type) is built with the whole block
            and neither lookup: it owns its policy.
        :raises AKConfigError: If the type is neither a built-in nor a resolvable dotted path, names an
            engine that is not shipped yet, or the policy in the block cannot be used.
        """
        authorizer_type = authorization_config.type
        AuthorizerFactory._log.info(f"Building '{authorizer_type}' authorizer")
        key = authorizer_type.lower()
        if key == "static":
            from .static import StaticAuthorizer

            return StaticAuthorizer(
                grants=authorization_config.grants,
                tools=authorization_config.tools,
                descriptor_lookup=descriptor_lookup,
                system_tiers=system_tiers,
            )
        if key in _RESERVED_ENGINES:
            raise AKConfigError(f"authorization.type: {key} is not shipped yet; use a dotted path")
        if "." in authorizer_type:
            return resolve_dotted(authorizer_type, base=Authorizer)(authorization_config)
        raise AKConfigError(
            f"unknown authorization type '{authorizer_type}'; expected one of {_BUILTIN_AUTHORIZERS} or a dotted path to an Authorizer subclass"
        )

    @classmethod
    def get(cls) -> Authorizer | None:
        """Return the process-wide authorizer, or None when no ``authorization`` block is configured.

        The None return is the enabled-check: without the block nothing is restricted. The shared
        authorizer reads the registry of whichever runtime is current when it is asked, and the tiers the
        system tools of an agent declare.

        :return: The shared authorizer, built on first access, or None.
        :raises AKConfigError: If the block cannot be built into an authorizer.
        """
        config = AKConfig.get().authorization
        if config is None:
            return None
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls.create(config, descriptor_lookup=cls._registry_descriptors, system_tiers=cls._system_tool_tiers)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared authorizer so the next get() rebuilds from config. Intended for testing."""
        with cls._lock:
            cls._instance = None

    @staticmethod
    def _registry_descriptors() -> list[AgentDescriptor]:
        """Every descriptor the current runtime's registry knows, read when a decision needs them."""
        # Imported here: the runtime reaches the authorization package, never the reverse at import time.
        from ...core.runtime import Runtime

        return Runtime.current().registry.descriptors()

    @staticmethod
    def _system_tool_tiers(agent_id: str) -> dict[str, AccessLevel]:
        """The tier each system tool attached to an agent declares, by tool name.

        Asked of the same factory an agent's tools are attached from, so it answers for an agent this
        process does not host as well, as long as both processes read the same configuration.
        """
        return {tool.name: tool.tier for tool in SystemToolFactory.get_all(agent_id)}
