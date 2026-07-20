"""
Shared database connection drivers for the Session, Multimodal, Response Store,
and Thread backends.

Drivers own the connection lifecycle (client creation, lazy connect, retry,
health-check/reconnect, TTL plumbing) and a generic command surface; data
layouts, key schemas, and serialization stay in the store classes. Drivers
never read AKConfig — all connection parameters are explicit constructor
arguments.

This package intentionally has no eager imports: ``redis``, ``valkey``,
``azure-data-tables``, and ``google-cloud-firestore`` are optional
dependencies, so consumers import the concrete module directly, e.g.
``from agentkernel.core.util.driver.redis import RedisDriver``.
"""
