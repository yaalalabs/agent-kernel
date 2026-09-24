"""SecretManager — resolves an environment-variable-style key to a secret value.

Resolution order is fixed: the process environment, then the process cache, then the configured
provider. A set, non-empty environment variable always wins; the provider only supplies keys the
environment does not. Nothing here ever writes os.environ.
"""

import logging
import os
import re
from threading import RLock
from typing import Any, ClassVar, Optional

from ..core.config import AKConfig, _SecretConfig
from .base import SecretProvider
from .cache import SecretCache
from .errors import SecretNotFoundError
from .factory import SecretProviderFactory

# Environment-variable-style keys: the names the SDKs already read. Uppercase-only so one secret has
# exactly one spelling across the cache, the provider and os.environ.
_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

_UNSET: Any = object()  # "no default supplied"; typed Any so it can default an Optional[str] parameter


class SecretManager:
    """Resolves an environment-variable-style key to a secret value: environment -> cache -> provider.

    The process-wide instance is SecretManager.current(). Keys are the same names the SDKs already
    read from the environment (OPENAI_API_KEY, NEO4J_PASSWORD), so nothing here renames, prefixes or
    case-folds them. A set, non-empty environment variable always wins. Provider-resolved values are
    returned to the caller and held in the cache only; nothing here ever writes os.environ.
    """

    # Guards construction in current()/reset() only. Resolution takes no manager lock: the cache
    # owns its own write lock, and the provider is called outside any lock.
    _instance: ClassVar[Optional["SecretManager"]] = None
    _instance_lock: ClassVar[RLock] = RLock()
    _log = logging.getLogger("ak.secret.manager")

    def __init__(self, provider: SecretProvider, cache_ttl: int = 300) -> None:
        """Constructor arguments are explicit; config reading stays in current()/from_config.

        :param provider: The backend consulted when the environment and the cache both miss.
        :param cache_ttl: Seconds a provider hit is served from the cache; 0 disables caching.
        :raises AKConfigError: If cache_ttl is negative.
        """
        self._provider = provider
        self._cache = SecretCache(cache_ttl)

    @classmethod
    def from_config(cls, config: _SecretConfig) -> "SecretManager":
        """Build a manager from the `secret` block.

        :param config: The `secret` configuration block.
        :return: The manager.
        :raises AKConfigError: If the configured provider or its own settings are unusable.
        """
        return cls(provider=SecretProviderFactory.create(config), cache_ttl=config.cache_ttl)

    @classmethod
    def current(cls) -> "SecretManager":
        """Return the configured process-wide manager, building it on first access.

        Unlike ScheduleManager.get(), this never returns None: the capability is always available
        and its default (env provider) costs nothing.

        :return: The shared manager.
        :raises AKConfigError: If `secret.provider.type`, `secret.prefix` or `secret.cache_ttl`
                               cannot be resolved to a usable manager.
        """
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls.from_config(AKConfig.get().secret)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared instance so the next current() rebuilds from config. For testing."""
        with cls._instance_lock:
            cls._instance = None

    # -- public API ----------------------------------------------------------------------

    def get(self, key: str, default: Optional[str] = _UNSET) -> Optional[str]:
        """Resolve `key`: environment, then cache, then provider; first hit wins.

        :param key: An environment-variable-style name matching ^[A-Z][A-Z0-9_]*$.
        :param default: Returned when no layer has the key. Omitted, a miss raises.
        :return: The resolved value, or `default` on a miss.
        :raises ValueError: If `key` is malformed.
        :raises SecretNotFoundError: If no layer has the key and no `default` was supplied.
        :raises SecretError: If the provider failed; never masked by `default`.
        """
        self._validate_key(key)
        value = self._resolve(key)
        if value is not None:
            return value
        if default is _UNSET:
            raise SecretNotFoundError(key)
        return default

    def invalidate(self, key: str) -> None:
        """Drop the cached value for `key` so the next `get` re-resolves it.

        :raises ValueError: If `key` is malformed.
        """
        self._validate_key(key)
        self._cache.invalidate(key)

    def clear(self) -> None:
        """Drop every cached value."""
        self._cache.clear()

    # -- internals -----------------------------------------------------------------------

    def _resolve(self, key: str) -> Optional[str]:
        """Environment -> cache -> provider, first hit wins. Holds no lock across the sequence."""
        env_value = os.environ.get(key)
        if env_value:  # set and non-empty wins; "" is a miss. Never cached, so re-read every call.
            return env_value
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        value = self._provider.get_secret(key)  # outside any lock; may raise SecretError
        if value is not None:
            self._cache.set(key, value)
        return value

    @staticmethod
    def _validate_key(key: str) -> None:
        """:raises ValueError: If key does not match ^[A-Z][A-Z0-9_]*$."""
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise ValueError(f"invalid secret key {key!r}: expected an environment-variable-style name matching {_KEY_PATTERN.pattern}")
