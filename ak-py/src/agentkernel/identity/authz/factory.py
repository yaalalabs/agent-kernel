"""AuthorizerFactory: builds the Authorizer named by ``authorization.type``."""

import logging
from threading import RLock
from typing import TYPE_CHECKING, ClassVar

from ...core.config import AKConfig
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
    def create(authorization_config: "_AuthorizationConfig") -> Authorizer:
        """Build the authorizer the ``authorization`` block names.

        Every backend is built from the block and nothing else: a built-in one reads the section named
        after it, a bring-your-own one (a dotted-path type) is handed the whole block. What a backend
        needs beyond its settings (the registry, the tools an agent carries) it finds itself.

        :param authorization_config: The ``authorization`` block.
        :return: The authorizer.
        :raises AKConfigError: If the type is neither a built-in nor a resolvable dotted path, names an
            engine that is not shipped yet, or the backend's own settings cannot be used.
        """
        authorizer_type = authorization_config.type
        AuthorizerFactory._log.info(f"Building '{authorizer_type}' authorizer")
        key = authorizer_type.lower()
        if key == "static":
            from .static import StaticAuthorizer

            return StaticAuthorizer.from_config(authorization_config)
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

        The None return is the enabled-check: without the block nothing is restricted.

        :return: The shared authorizer, built on first access, or None.
        :raises AKConfigError: If the block cannot be built into an authorizer.
        """
        config = AKConfig.get().authorization
        if config is None:
            return None
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls.create(config)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared authorizer so the next get() rebuilds from config. Intended for testing."""
        with cls._lock:
            cls._instance = None
