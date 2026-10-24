import logging
from typing import Any

from .config import AKConfig
from .session import SessionCache, SessionStore
from .util.factory import AKConfigError, require_extra, resolve_dotted

_BUILTIN_SESSION_STORES = ["in_memory", "redis", "valkey", "dynamodb", "cosmosdb", "firestore"]


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

    PROTOCOL_BINDING = "HTTP+JSON"
    """
    The one binding served: REST
    """
    PROTOCOL_VERSION = "1.0"
    """
    The one A2A protocol version served; 0.3 clients are not
    """

    @classmethod
    def build(cls, name: str, description: Any, skills: list[Any]) -> Any:
        """
        Build and return an A2A AgentCard instance.
        :param name: Name of the agent.
        :param description: Description of the agent; anything but a str is replaced by "".
        :param skills: List of AgentSkill objects; any with empty tags is tagged with the agent name.
        :return: An A2A AgentCard instance.
        """
        from a2a.types import AgentCapabilities, AgentCard, AgentInterface

        return AgentCard(
            name=name,
            description=cls._description(name, description),
            supported_interfaces=[
                AgentInterface(url=f"{AKConfig.get().a2a.url}/{name}", protocol_binding=cls.PROTOCOL_BINDING, protocol_version=cls.PROTOCOL_VERSION)
            ],
            version=AKConfig.get().library_version,
            default_input_modes=["text"],
            default_output_modes=["json"],
            capabilities=AgentCapabilities(streaming=False),
            skills=cls._tag_untagged(name, skills),
        )

    @classmethod
    def _description(cls, name: str, description: Any) -> str:
        """
        The card's description: a str as is, anything else "" with a warning.
        A non-str (OpenAI instructions may be a callable) would otherwise fail the whole A2A mount.
        :param name: Name of the agent, for the warning.
        :param description: The description the adapter supplied.
        :return: The description to put on the card.
        """
        if isinstance(description, str):
            return description
        cls._log.warning(f"Agent '{name}' has a non-string description ({type(description).__name__}); its A2A card uses an empty one")
        return ""

    @staticmethod
    def _tag_untagged(name: str, skills: list[Any]) -> list[Any]:
        """
        Tag each skill that has no tags with the agent name; A2A requires at least one tag.
        :param name: Name of the agent.
        :param skills: List of AgentSkill objects, changed in place.
        :return: The same skills.
        """
        for skill in skills:
            if not skill.tags:
                skill.tags.append(name)
        return skills


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
        Build and return a SessionStore instance based on the configured ``session.type``.

        ``type`` is a built-in short name (in_memory, redis, valkey, dynamodb, cosmosdb,
        firestore) or a dotted path to a user-supplied ``SessionStore`` subclass
        (bring-your-own). An unknown, non-dotted value raises ``AKConfigError``.
        """
        store_type = AKConfig.get().session.type
        Builder._log.info(f"Building '{store_type}' session store")
        cache = SessionCacheBuilder.build()
        key = store_type.lower()
        if key == "in_memory":
            from .session.in_memory import InMemorySessionStore

            return InMemorySessionStore()
        if key == "redis":
            with require_extra("redis", "session.type: redis"):
                from .session.redis import RedisSessionStore

            return RedisSessionStore(cache=cache)
        if key == "valkey":
            with require_extra("valkey", "session.type: valkey"):
                from .session.valkey import ValkeySessionStore

            return ValkeySessionStore(cache=cache)
        if key == "dynamodb":
            with require_extra("aws", "session.type: dynamodb"):
                from .session.dynamodb import DynamoDBSessionStore

            return DynamoDBSessionStore(cache=cache)
        if key == "cosmosdb":
            with require_extra("azure", "session.type: cosmosdb"):
                from .session.cosmosdb import CosmosDBSessionStore

            return CosmosDBSessionStore(cache=cache)
        if key == "firestore":
            with require_extra("gcp", "session.type: firestore"):
                from .session.firestore import FirestoreSessionStore

            return FirestoreSessionStore(cache=cache)
        if "." not in store_type:
            raise AKConfigError(
                f"unknown session store type '{store_type}'; expected one of {_BUILTIN_SESSION_STORES} or a dotted path to a SessionStore subclass"
            )
        return resolve_dotted(store_type, base=SessionStore)(cache=cache)
