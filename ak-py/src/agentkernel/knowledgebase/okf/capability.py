"""The process-wide owner of everything the ``okf`` configuration block describes.

This module is the **single** reader of that block. ``OKFManager``, ``DocumentStore`` and
``KnowledgeBuilder`` keep taking explicit constructor parameters and never call
``AKConfig.get()``, so everything below them stays constructible from a test or from an
application that wires OKF programmatically.

Construction is lazy and per database because ``OKFManager.connect()`` walks the whole store
from ``__init__``. Building every configured bundle eagerly would move N store walks into agent
construction; instead a bundle is walked the first time something actually reaches it.
"""

import logging
from threading import RLock
from typing import TYPE_CHECKING, ClassVar, Dict, Mapping, Optional

from ...core.config import AKConfig
from ...core.util.factory import AKConfigError, resolve_dotted
from ..knowledgebuilder import KnowledgeBuilder
from ..store.base import DocumentStore
from .roles import OKFRoleRegistry

if TYPE_CHECKING:
    from ...core.config import _OKFConfig, _OKFDatabaseConfig
    from .manager import OKFManager

log = logging.getLogger("ak.knowledgebase.okf")

# The one scheme the built-in type names disagree about. Kept here rather than imported from
# store/base.py: this is the agreement check on configuration text, not URI parsing.
_S3_SCHEME = "s3://"

_LOCAL = "local"
_S3 = "s3"


class OKFCapabilityManager:
    """Resolves the ``okf`` block into stores, backends and per-agent tool builders.

    A singleton in the ``ScheduleManager`` shape, including :meth:`get` returning ``None`` when
    the capability is not configured — callers use that None check as the enabled check for the
    whole layer.
    """

    _instance: ClassVar[Optional["OKFCapabilityManager"]] = None
    _lock: ClassVar[RLock] = RLock()

    def __init__(self, config: "_OKFConfig") -> None:
        """
        Initialize from a parsed config block. Use :meth:`get`, not this constructor.

        The role validations run here, so an unusable block fails as soon as anything reaches
        the capability rather than inside the first tool call.

        :param config: The parsed ``okf`` block.
        :return: None.
        :raises AKConfigError: If a database names no agent, or names one agent as both its
                               producer and its curator.
        """
        self._databases: Dict[str, "_OKFDatabaseConfig"] = dict(config.databases)
        self._roles = OKFRoleRegistry.from_config(self._databases)

        # Reentrant because builder_for() resolves backends while already holding it.
        self._cache_lock = RLock()
        self._stores: Dict[str, DocumentStore] = {}
        self._backends: Dict[str, "OKFManager"] = {}
        self._builders: Dict[str, KnowledgeBuilder] = {}

    @classmethod
    def get(cls) -> Optional["OKFCapabilityManager"]:
        """
        Return the shared manager, or None when no ``okf`` block is configured.

        :return: The shared instance, or None when the capability is disabled.
        :raises AKConfigError: If the block is present but unusable.
        """
        config = getattr(AKConfig.get(), "okf", None)
        if config is None:
            return None
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Drop the shared instance so the next get() rebuilds from config. Intended for testing.

        :return: None.
        """
        with cls._lock:
            cls._instance = None

    @property
    def roles(self) -> OKFRoleRegistry:
        """
        Return the role registry built from the block.

        :return: The registry.
        """
        return self._roles

    @property
    def databases(self) -> Mapping[str, "_OKFDatabaseConfig"]:
        """
        Return the configured databases, keyed by backend name.

        :return: The parsed database configurations.
        """
        return self._databases

    def backend(self, database: str) -> "OKFManager":
        """
        Return the manager for one database, constructing and caching it on first use.

        One manager per database, shared by every agent's builder: two agents reading the same
        bundle pay one store walk and one refresh cycle rather than two.

        :param database: Configured database name.
        :return: The backend for that bundle.
        :raises AKConfigError: If no such database is configured, or its store cannot be resolved.
        """
        if database not in self._databases:
            raise AKConfigError(f"No OKF database named '{database}' is configured. Configured databases: {sorted(self._databases)}.")

        with self._cache_lock:
            manager = self._backends.get(database)
            if manager is None:
                # Imported here rather than at module scope: manager.py pulls the whole storage
                # and parsing tier, and reading configuration must not require walking a bundle.
                from .manager import OKFManager

                config = self._databases[database]
                manager = OKFManager(
                    store=self.store(database),
                    name=database,
                    description=config.description,
                    refresh_seconds=config.refresh_seconds,
                )
                self._backends[database] = manager
            return manager

    def builder_for(self, agent_name: str) -> Optional[KnowledgeBuilder]:
        """
        Return this agent's tool builder, over only the databases it holds a role in.

        Scoping the builder per agent is what makes read-side isolation structural: a database
        the agent holds no role in is simply not registered, so routing a tool at it returns
        ``KnowledgeBuilder``'s existing unknown-backend message with no extra enforcement.

        :param agent_name: Agent to build for.
        :return: The builder, or None when the agent holds no role anywhere.
        :raises AKConfigError: If one of the agent's databases cannot be resolved.
        """
        databases = self._roles.databases_for(agent_name)
        if not databases:
            return None

        with self._cache_lock:
            builder = self._builders.get(agent_name)
            if builder is None:
                semantic_maps = {name: dict(self._databases[name].semantic_map or {}) for name in databases if self._databases[name].semantic_map}
                builder = KnowledgeBuilder(
                    [self.backend(name) for name in databases],
                    backend_semantic_maps=semantic_maps or None,
                )
                self._builders[agent_name] = builder
            return builder

    def store(self, database: str) -> DocumentStore:
        """
        Return the resolved document store for one database, caching it on first use.

        Resolution does not walk the store, so this is safe to call during validation.

        :param database: Configured database name.
        :return: The store.
        :raises AKConfigError: If the declared type and uri disagree, or the type resolves to
                               nothing usable.
        """
        with self._cache_lock:
            store = self._stores.get(database)
            if store is None:
                store = self._resolve_store(database)
                self._stores[database] = store
            return store

    def validate_configuration(self) -> None:
        """
        Force every check the block can answer without walking a store.

        Called before any tool is built, so a bad block fails at agent construction rather than
        inside the first tool call. Store contents stay lazy: this resolves each store and reads
        its declared writability, and walks nothing.

        :return: None.
        :raises AKConfigError: If any database's type and uri disagree, or a type does not resolve.
        """
        for database, config in self._databases.items():
            store = self.store(database)
            if store.writable:
                continue

            writers = sorted({name.strip() for name in (*(config.producer or []), *(config.curator or [])) if name and name.strip()})
            if writers:
                # Warned rather than raised (design decision 19): the block's other validations
                # check config text and are wrong wherever they run, while this one checks the
                # environment -- the same file is legitimately correct in production while the
                # bundle is read-only in CI or under a read-only volume mount. The message names
                # the consequence, because the symptom is otherwise hard to trace back to config.
                log.warning(
                    "OKF database '%s' has a read-only store but names writable agents %s; their write_kb calls will be refused.",
                    database,
                    writers,
                )

    def _resolve_store(self, database: str) -> DocumentStore:
        """
        Resolve one database's ``type`` and ``uri`` to a store instance.

        ``type`` is redundant with the uri's scheme and kept anyway, so the redundancy becomes a
        startup agreement check rather than a second source of truth. The check applies to the
        two built-in names only: a bring-your-own store defines what its own uri means.

        :param database: Configured database name.
        :return: The resolved store.
        :raises AKConfigError: If the type and uri disagree, or the type does not resolve.
        """
        config = self._databases[database]
        declared, uri = (config.type or "").strip(), (config.uri or "").strip()

        if declared == _LOCAL:
            if uri.startswith(_S3_SCHEME):
                raise self._disagreement(database, declared, uri, "an s3:// uri needs type 's3'")
            return DocumentStore.from_uri(uri)

        if declared == _S3:
            if not uri.startswith(_S3_SCHEME):
                raise self._disagreement(database, declared, uri, "type 's3' needs an s3://bucket/prefix uri")
            return DocumentStore.from_uri(uri)

        return resolve_dotted(declared, base=DocumentStore, error=AKConfigError)(uri)

    @staticmethod
    def _disagreement(database: str, declared: str, uri: str, requirement: str) -> AKConfigError:
        """
        Build the error raised when a database's type and uri contradict each other.

        :param database: Database the mismatch was found in.
        :param declared: The configured type.
        :param uri: The configured uri.
        :param requirement: What the pairing would have needed, phrased for the user.
        :return: The error to raise.
        """
        return AKConfigError(f"OKF database '{database}' declares type {declared!r} with uri {uri!r}: {requirement}.")
