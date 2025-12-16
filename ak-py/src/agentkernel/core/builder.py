import logging
from enum import StrEnum

from agentkernel.core.session.base import SessionCache

from .config import AKConfig
from .session import SessionStore


class Builder:
    """
    Builder base class for constructing various components.
    """

    _log = logging.getLogger("ak.builder")


class SessionStoreType(StrEnum):
    """
    Enumeration of supported session store types.

    This enum defines the available backend storage options for managing session state
    within the agent system.

    Attributes:
        IN_MEMORY: Store sessions in local memory (non-persistent).
        REDIS: Store sessions using Redis as the backend (persistent/distributed).
    """

    IN_MEMORY = "IN_MEMORY"
    REDIS = "REDIS"
    DYNAMODB = "DYNAMODB"

    @classmethod
    def from_str(cls, type_str: str) -> "SessionStoreType":
        """
        Create a SessionStoreType enum member from a string representation.

        This class method attempts to convert a string to its corresponding SessionStoreType
        enum value. If the conversion fails, it logs a warning and returns the default
        IN_MEMORY type.

        :param type_str: The string representation of the session store type. Case-insensitive input is supported.

        :returns: The corresponding SessionStoreType enum member.
            Returns SessionStoreType.IN_MEMORY as a fallback if the input string doesn't match any valid enum member.
        """
        try:
            return cls[type_str.upper()]
        except KeyError:
            Builder._log.warning(f"Invalid session store type '{type_str}', falling back to IN_MEMORY")
            return SessionStoreType.IN_MEMORY


class SessionCacheBuilder(Builder):
    """
    Builder class for creating SessionCache instances based on configuration.

    This class implements the Builder pattern to construct SessionCache instances
    according to the session cache size specified in the application configuration.
    """

    @staticmethod
    def build() -> SessionCache:
        """
        Build and return a SessionCache instance based on the configured cache size.

        This static method reads the session cache size from the application configuration
        and instantiates a SessionCache with that capacity.

        :returns: An instance of SessionCache with the configured capacity or None if caching is not configured.
        :raises: Any exceptions raised by AKConfig.get() or SessionCache() initialization.
        """
        capacity = 256
        if hasattr(AKConfig.get().session, "cache") and AKConfig.get().session.cache is not None:
            Builder._log.info(f"Building session cache with capacity {capacity}")
            return SessionCache(capacity=AKConfig.get().session.cache.size)
        return None


class SessionStoreBuilder(Builder):
    """
    Builder class for creating SessionStore instances based on configuration.

    This class implements the Builder pattern to construct appropriate SessionStore
    implementations based on the session store type specified in the application
    configuration.
    """

    @staticmethod
    def build() -> SessionStore:
        """
        Build and return a SessionStore instance based on the configured session store type.

        This static method reads the session store type from the application configuration
        and instantiates the appropriate SessionStore implementation. Currently supports
        Redis-backed, DynamoDB-backed, and in-memory session stores.

        :returns: An instance of RedisSessionStore (if configured type is REDIS),
            DynamoDBSessionStore (if configured type is DYNAMODB),
            or InMemorySessionStore (for all other types).

        :raises: Any exceptions raised by SessionStoreType.from_str(), AKConfig.get(),
            RedisDriver(), RedisSessionStore(), or InMemorySessionStore() initialization.
        """
        session_store_type: SessionStoreType = SessionStoreType.from_str(AKConfig.get().session.type)
        Builder._log.info(f"Building {session_store_type} session store")
        if session_store_type == SessionStoreType.REDIS:
            from .session.redis import RedisSessionStore

            return RedisSessionStore(cache=SessionCacheBuilder.build())
        elif session_store_type == SessionStoreType.DYNAMODB:
            from .session.dynamodb import DynamoDBSessionStore

            return DynamoDBSessionStore(cache=SessionCacheBuilder.build())
        else:
            from .session.in_memory import InMemorySessionStore

            return InMemorySessionStore()
