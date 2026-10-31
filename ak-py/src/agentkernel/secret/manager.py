import logging
import os
import re
from threading import RLock
from typing import Any, ClassVar, Optional

from ..core.config import AKConfig
from .base import SecretProvider
from .cache import SecretCache
from .errors import SecretNotFoundError
from .factory import SecretProviderFactory

# Uppercase-only so one secret has exactly one spelling across the cache, the provider and os.environ.
_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

_UNSET: Any = object()  # "no default supplied"; typed Any so it can default an Optional[str] parameter


class SecretManager:
    """Resolves an environment-variable-style key to a secret value: environment -> cache -> provider.

    A set, non-empty environment variable always wins. Provider-resolved values are cached, never
    written to os.environ.
    """

    _instance: ClassVar[Optional["SecretManager"]] = None
    _instance_lock: ClassVar[RLock] = RLock()
    _log = logging.getLogger("ak.secret.manager")

    def __init__(self, provider: SecretProvider, cache_ttl: int = 300) -> None:
        """Create a manager over an explicit provider.

        :param provider: The backend consulted when the environment and the cache both miss.
        :param cache_ttl: Seconds a provider hit is served from the cache; 0 disables caching.
        :raises AKConfigError: If cache_ttl is negative.
        """
        self._provider = provider
        self._cache = SecretCache(cache_ttl)

    @classmethod
    def current(cls) -> "SecretManager":
        """Return the configured process-wide manager, building it on first access.

        :return: The shared manager.
        :raises AKConfigError: If `secret.provider.type`, `secret.prefix` or `secret.cache_ttl`
                               cannot be resolved to a usable manager.
        """
        with cls._instance_lock:
            if cls._instance is None:
                config = AKConfig.get().secret
                cls._instance = cls(provider=SecretProviderFactory.get(config), cache_ttl=config.cache_ttl)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared instance so the next current() rebuilds from config. For testing."""
        with cls._instance_lock:
            cls._instance = None

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
            raise SecretNotFoundError(key, self.describe(key))
        return default

    def describe(self, key: str, field: Optional[str] = None) -> str:
        """Every place `key` can be set, for an error message that tells the user what to create.

        For example "whatsapp.access_token, the AK_WHATSAPP__ACCESS_TOKEN environment variable or SSM
        parameter /ak/myapp-dev/ak_whatsapp__access_token".

        :param key: An environment-variable-style name matching ^[A-Z][A-Z0-9_]*$.
        :param field: The AKConfig field consulted before the secret fallback, if any.
        :return: The places, in resolution order.
        :raises ValueError: If `key` is malformed.
        """
        self._validate_key(key)
        places = [field] if field else []
        places.append(f"the {key} environment variable")
        location = self._provider.describe(key)
        if location:
            places.append(location)
        return places[0] if len(places) == 1 else f"{', '.join(places[:-1])} or {places[-1]}"

    def invalidate(self, key: str) -> None:
        """Drop the cached value for `key` so the next `get` re-resolves it.

        :raises ValueError: If `key` is malformed.
        """
        self._validate_key(key)
        self._cache.invalidate(key)

    def clear(self) -> None:
        """Drop every cached value."""
        self._cache.clear()

    def _resolve(self, key: str) -> Optional[str]:
        env_value = os.environ.get(key)
        if env_value:  # "" is a miss
            return env_value
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        value = self._provider.get_secret(key)
        if value is not None:
            self._cache.set(key, value)
        return value

    @staticmethod
    def _validate_key(key: str) -> None:
        """:raises ValueError: If key does not match ^[A-Z][A-Z0-9_]*$."""
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise ValueError(f"invalid secret key {key!r}: expected an environment-variable-style name matching {_KEY_PATTERN.pattern}")
