import logging

from ...core.config import AKConfig
from ...core.util.factory import AKConfigError, resolve_dotted
from ..transport.base import QueueTransportFactory
from .base import ResponseStore

_log = logging.getLogger("ak.pipeline.response_store")

_BUILTIN_TYPES = ("in_memory", "redis", "valkey", "dynamodb")


class ResponseStoreFactory:
    """Resolves ``execution.response_store`` to a :class:`ResponseStore` (#541 house pattern).

    Owns the pipeline's resolution defaults in one place: with nothing configured, the
    single-process topology (in_memory transport) gets the in-memory store, while broker
    transports fail fast because they need a store shared across processes. Built-in short
    names resolve by branch; any dotted path resolves to a bring-your-own ``ResponseStore``
    subclass.
    """

    @classmethod
    def create(cls) -> ResponseStore:
        """Create the effective response store for the current configuration."""
        config = AKConfig.get()
        response_store_config = config.execution.response_store if config.execution else None
        configured_type = response_store_config.type if response_store_config is not None else None

        # Bring-your-own store: a dotted path to a ResponseStore subclass.
        if configured_type and "." in configured_type:
            return resolve_dotted(configured_type, base=ResponseStore)()

        if configured_type in (None, "in_memory"):
            if configured_type == "in_memory" or QueueTransportFactory.resolve_type() == "in_memory":
                from .in_memory import InMemoryResponseStore

                return InMemoryResponseStore()
            raise AKConfigError(
                "execution.response_store is required on broker transports: configure one of "
                f"{list(_BUILTIN_TYPES)} or a dotted path to a ResponseStore subclass (the in_memory "
                "store is single-process only)"
            )

        if configured_type == "redis" and response_store_config.redis is not None:
            from .redis import RedisResponseStore

            redis_config = response_store_config.redis
            return RedisResponseStore(url=redis_config.url, prefix=redis_config.prefix, ttl=redis_config.ttl)

        if configured_type == "valkey" and response_store_config.valkey is not None:
            try:
                from .valkey import ValkeyResponseStore
            except ImportError as e:
                raise ImportError(
                    "The 'valkey' package is required for execution.response_store.type: valkey. Install it with: pip install agentkernel[valkey]"
                ) from e

            valkey_config = response_store_config.valkey
            return ValkeyResponseStore(url=valkey_config.url, prefix=valkey_config.prefix, ttl=valkey_config.ttl)

        if configured_type == "dynamodb" and response_store_config.dynamodb is not None:
            from .dynamodb import DynamoDBResponseStore

            dynamodb_config = response_store_config.dynamodb
            return DynamoDBResponseStore(
                table_name=dynamodb_config.table_name,
                region=None,  # Will use default AWS region from environment/IAM role
                ttl=dynamodb_config.ttl,
            )

        raise AKConfigError(
            f"no valid response store configured for type '{configured_type}': expected one of "
            f"{list(_BUILTIN_TYPES)} (with its backend block) or a dotted path to a ResponseStore subclass"
        )
