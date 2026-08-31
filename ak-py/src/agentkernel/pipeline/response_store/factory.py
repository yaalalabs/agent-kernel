import logging
from typing import Any, Optional

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
    def create(cls, response_store_config: Any = None, transport_type: Optional[str] = None, ttl: Optional[int] = None) -> ResponseStore:
        """Create the effective response store.

        With every parameter omitted this reads ``execution.response_store`` and the chat
        pipeline's transport type exactly as before (#503 seam). The sandbox queue broker
        passes its own ``sandbox.broker.response_store`` block, its own transport's resolved
        type (for the in_memory-pairing rule), and ``ttl=sandbox.broker.response_ttl``, which
        overrides the backend block's ``ttl`` so one knob governs sandbox record retention.
        """
        if response_store_config is None:
            config = AKConfig.get()
            response_store_config = config.execution.response_store if config.execution else None
        configured_type = response_store_config.type if response_store_config is not None else None

        # Bring-your-own store: a dotted path to a ResponseStore subclass.
        if configured_type and "." in configured_type:
            return resolve_dotted(configured_type, base=ResponseStore)()

        if configured_type in (None, "in_memory"):
            # The transport lookup stays behind the `or` short-circuit: an explicit in_memory
            # store never consults the transport config (pre-seam behavior, kept verbatim).
            if (
                configured_type == "in_memory"
                or (transport_type if transport_type is not None else QueueTransportFactory.resolve_type()) == "in_memory"
            ):
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
            return RedisResponseStore(url=redis_config.url, prefix=redis_config.prefix, ttl=ttl if ttl is not None else redis_config.ttl)

        if configured_type == "valkey" and response_store_config.valkey is not None:
            try:
                from .valkey import ValkeyResponseStore
            except ImportError as e:
                raise ImportError(
                    "The 'valkey' package is required for execution.response_store.type: valkey. Install it with: pip install agentkernel[valkey]"
                ) from e

            valkey_config = response_store_config.valkey
            return ValkeyResponseStore(url=valkey_config.url, prefix=valkey_config.prefix, ttl=ttl if ttl is not None else valkey_config.ttl)

        if configured_type == "dynamodb" and response_store_config.dynamodb is not None:
            from .dynamodb import DynamoDBResponseStore

            dynamodb_config = response_store_config.dynamodb
            return DynamoDBResponseStore(
                table_name=dynamodb_config.table_name,
                region=None,  # Will use default AWS region from environment/IAM role
                ttl=ttl if ttl is not None else dynamodb_config.ttl,
            )

        raise AKConfigError(
            f"no valid response store configured for type '{configured_type}': expected one of "
            f"{list(_BUILTIN_TYPES)} (with its backend block) or a dotted path to a ResponseStore subclass"
        )
