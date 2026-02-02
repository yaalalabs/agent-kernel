import logging
from enum import StrEnum
from typing import Any, List, Self

from .config import AKConfig
from .session import SessionCache, SessionStore


class Builder:
    """
    Builder base class for constructing various components.
    """

    _log = logging.getLogger("ak.builder")


class A2ACardBuilder(Builder):
    """
    Builder class for creating A2ACard instances based on configuration.

    This class implements the Builder pattern to construct A2ACard instances
    according to the application configuration.
    """

    @staticmethod
    def build(name: str, description: str, skills: List[Any]) -> Any:
        """
        Build and return an A2A AgentCard instance.
        :param name: Name of the agent.
        :param description: Description of the agent.
        :param skills: List of AgentSkill objects.
        :return: An A2A AgentCard instance.
        """
        from a2a.types import AgentCapabilities, AgentCard

        return AgentCard(
            name=name,
            description=description,
            url=f"{AKConfig.get().a2a.url}/{name}",
            version=AKConfig.get().library_version,
            default_input_modes=["text"],
            default_output_modes=["json"],
            preferred_transport="HTTP+JSON",
            capabilities=AgentCapabilities(streaming=False),
            skills=skills,
        )


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

    class Types(StrEnum):
        """
        Enumeration of supported session store types.
        """

        IN_MEMORY = "IN_MEMORY"
        REDIS = "REDIS"
        DYNAMODB = "DYNAMODB"

        @classmethod
        def from_str(cls, type_str: str) -> Self:
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
                return SessionStoreBuilder.Types.IN_MEMORY

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

        :raises: Any exceptions raised by SessionStoreBuilder.Types.from_str(), AKConfig.get(),
            RedisDriver(), RedisSessionStore(), or InMemorySessionStore() initialization.
        """
        session_store_type: SessionStoreBuilder.Types = SessionStoreBuilder.Types.from_str(AKConfig.get().session.type)
        Builder._log.info(f"Building {session_store_type} session store")
        if session_store_type == SessionStoreBuilder.Types.REDIS:
            from .session.redis import RedisSessionStore

            return RedisSessionStore(cache=SessionCacheBuilder.build())
        elif session_store_type == SessionStoreBuilder.Types.DYNAMODB:
            from .session.dynamodb import DynamoDBSessionStore

            return DynamoDBSessionStore(cache=SessionCacheBuilder.build())
        else:
            from .session.in_memory import InMemorySessionStore

            return InMemorySessionStore()
