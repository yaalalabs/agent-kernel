import logging
from typing import Any

from .config import AKConfig
from .model import AgentDescriptor
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
    Builder class for creating A2A AgentCard instances from agent descriptors.

    A card is a rendering of the agent's descriptor, the record the registry holds, with what the
    deployment adds to it: the A2A URL, the A2UI extension and the identity provider's security scheme.
    """

    PROTOCOL_BINDING = "HTTP+JSON"
    """
    The one binding served: REST
    """
    PROTOCOL_VERSION = "1.0"
    """
    The one A2A protocol version served; 0.3 clients are not
    """
    TEXT_MODE = "text/plain"
    """
    The media type of every request read and every unlabelled reply sent
    """
    SECURITY_SCHEME = "ak"
    """
    The name a card gives the one security scheme it declares
    """
    UNDESCRIBED_AGENT_TEXT = "The '{agent}' agent."
    """
    What a card says of an agent with no declared description. A2A requires the field, and an empty one is
    left out of the served JSON altogether; the agent's instructions are never the fallback
    """
    UNDESCRIBED_SKILL_TEXT = "The '{skill}' skill of the '{agent}' agent."
    """
    What a card says of a skill with no description, for the same reason
    """

    @classmethod
    def build(cls, descriptor: AgentDescriptor) -> Any:
        """
        Build and return the A2A AgentCard of an agent from its descriptor.

        The name, description, version and skills are the descriptor's; the interface URL and the A2UI
        check use its id, the name the agent is addressed by. An agent or a skill with no description
        carries a neutral sentence naming it, on the card only. Modes list only what is actually exchanged:
        text in, text out, plus the A2UI media type and extension for an agent whose JSON replies the A2UI
        capability labels. With an identity provider configured the card declares the provider's security
        scheme and requires it, on the card and on every skill.
        :param descriptor: The agent's descriptor, as the registry holds it. It is not changed.
        :return: An A2A AgentCard instance.
        """
        from a2a.types import AgentCapabilities, AgentCard, AgentExtension, AgentInterface, AgentSkill

        # Imported here: a2ui imports core, so a module-scope import risks a cycle through core/__init__
        from ..a2ui.hook import A2UIPostHook, A2UIPostHookFactory

        output_modes = [cls.TEXT_MODE]
        extensions = []
        if A2UIPostHookFactory.labels(descriptor.id):
            output_modes.append(A2UIPostHook.MEDIA_TYPE)
            extensions.append(AgentExtension(uri=A2UIPostHook.EXTENSION_URI, required=False))

        schemes, requirements = cls._security()
        skills = [
            AgentSkill(
                id=skill.id,
                name=skill.name,
                description=skill.description or cls.UNDESCRIBED_SKILL_TEXT.format(skill=skill.name, agent=descriptor.id),
                # A2A requires at least one tag; a skill declared without any is tagged with the agent id.
                tags=skill.tags or [descriptor.id],
                security_requirements=requirements,
            )
            for skill in descriptor.skills
        ]
        return AgentCard(
            name=descriptor.name,
            description=descriptor.description or cls.UNDESCRIBED_AGENT_TEXT.format(agent=descriptor.id),
            supported_interfaces=[
                AgentInterface(
                    url=f"{AKConfig.get().a2a.url}/{descriptor.id}", protocol_binding=cls.PROTOCOL_BINDING, protocol_version=cls.PROTOCOL_VERSION
                )
            ],
            version=descriptor.version,
            default_input_modes=[cls.TEXT_MODE],
            default_output_modes=output_modes,
            capabilities=AgentCapabilities(streaming=False, extensions=extensions),
            skills=skills,
            security_schemes=schemes,
            security_requirements=requirements,
        )

    @classmethod
    def _security(cls) -> tuple[dict[str, Any], list[Any]]:
        """
        The security schemes a card declares and the requirement that names them.

        Both come from the configured identity provider: OpenID Connect with the provider's discovery URL
        when it advertises one, HTTP bearer for every other provider, since a bearer token is what every
        surface reads. Without an identity block a card declares neither.
        :return: The card's security schemes by name, and its security requirements.
        """
        from a2a.types import HTTPAuthSecurityScheme, OpenIdConnectSecurityScheme, SecurityRequirement, SecurityScheme, StringList

        # Imported here: core reaches identity lazily, and get() returning None is the enabled-check.
        from ..identity.provider.factory import IdentityProviderFactory

        provider = IdentityProviderFactory.get()
        if provider is None:
            return {}, []
        name, settings = provider.security_scheme()
        if name == "openIdConnect":
            scheme = SecurityScheme(open_id_connect_security_scheme=OpenIdConnectSecurityScheme(open_id_connect_url=settings["url"]))
        else:
            scheme = SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer"))
        return {cls.SECURITY_SCHEME: scheme}, [SecurityRequirement(schemes={cls.SECURITY_SCHEME: StringList(list=[])})]


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
