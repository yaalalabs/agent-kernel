from abc import ABC, abstractmethod
from collections import OrderedDict
from threading import RLock
from typing import Any, Dict, List, Optional

from ..base import Session
from ..util.factory import AKConfigError


class WSConnectionStore(ABC):
    """The WebSocket gateway's shared connection store (spec #495 §9): the AWS
    DynamoDB-connections-table analogue, provided per backend by the session stores.

    Maps every live connection to its user and to the push endpoint of the gateway pod holding
    the socket, so a Response Handler on any pod can deliver a reply to wherever the user is
    connected *now*. Obtained via :meth:`SessionStore.get_connection_store`, so the backend
    follows the session storage configuration and each session store file carries (or explicitly
    declines) its implementation: any database with a driver can be a connection store.
    """

    @property
    def shared(self) -> bool:
        """Whether the mappings are visible across processes (multi-pod topologies require it)."""
        return True

    @abstractmethod
    def add_connection(self, user_id: str, connection_id: str, endpoint: str) -> None:
        """Register a connection with the push endpoint of the gateway pod holding its socket."""
        raise NotImplementedError

    @abstractmethod
    def get_connections(self, user_id: str) -> List[str]:
        """The user's live connection ids."""
        raise NotImplementedError

    @abstractmethod
    def get_endpoints(self, user_id: str) -> Dict[str, str]:
        """The user's live connections as ``{connection_id: gateway push endpoint}``."""
        raise NotImplementedError

    @abstractmethod
    def get_endpoint(self, connection_id: str) -> Optional[str]:
        """The push endpoint of the gateway pod holding ``connection_id``, or None."""
        raise NotImplementedError

    @abstractmethod
    def get_user_id(self, connection_id: str) -> Optional[str]:
        """The user holding ``connection_id``, or None."""
        raise NotImplementedError

    @abstractmethod
    def delete_connection(self, user_id: str, connection_id: str) -> None:
        """Deregister one connection (a missing connection is not an error)."""
        raise NotImplementedError

    def delete_by_connection_id(self, connection_id: str) -> None:
        """Deregister a connection by id alone (resolving the user; default implementation)."""
        user_id = self.get_user_id(connection_id)
        if user_id is not None:
            self.delete_connection(user_id, connection_id)


class SessionStore(ABC):
    """
    SessionStore is the base class for session storage that allows storage and retrieval of session
    data.

    Session stores also provide the WebSocket gateway's connection store on their backend via
    :meth:`get_connection_store` (spec #495 §9), so a deployment that runs Redis/Valkey or
    DynamoDB for sessions carries it on the same infrastructure. Implementing it (or overriding
    it with a specific, actionable error) is part of adding a session store type.
    """

    @abstractmethod
    def new(self, session_id: str) -> Session:
        """
        Initialize a session for a given session id.
        :param session_id: Unique identifier for the session.
        :return: The session associated with the identifier, or a new session if it does not exist.
        """
        pass

    @abstractmethod
    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Loads a session by its unique identifier.
        :param session_id: Unique identifier for the session.
        :param strict: If True, raises an exception if the session is not found.
        :return: The session associated with the identifier, or a new session if it does not exist
        in storage.
        """
        pass

    @abstractmethod
    def store(self, session: Session) -> None:
        """
        Stores a session or update it if it already exists in the storage.
        :param session: The session to store.
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        Clears all stored sessions.
        """
        pass

    def get_connection_store(self) -> WSConnectionStore:
        """
        The WebSocket gateway's connection store on this session store's backend.

        :return: A :class:`WSConnectionStore` sharing this backend's connection settings.
        :raises AKConfigError: When this backend does not provide one. Built-in stores override
            this method (in_memory/redis/valkey/dynamodb with real stores, the rest with a
            specific error); this default covers bring-your-own stores that predate the method.
        """
        raise AKConfigError(
            f"session store {type(self).__name__} does not implement get_connection_store; the WebSocket "
            "gateway's connection store follows the session storage configuration, so implement "
            "get_connection_store on this store or configure session.type as redis, valkey, dynamodb or in_memory"
        )


class SessionCache:
    """
    SessionCache is an in-memory cache for Session objects, with a maximum size limit.
    When the cache exceeds the maximum size, the least recently used session is removed.
    """

    def __init__(self, capacity: int = 256):
        """
        Initialize the session cache with a specified capacity.
        :param capacity (int, optional): The maximum number of sessions the cache can hold (default is 256).
        """
        super().__init__()
        self._lock: RLock = RLock()
        self._cache: OrderedDict[str, Session] = OrderedDict()
        self._capacity = capacity

    def capacity(self) -> int:
        """
        Get the maximum capacity of the session cache.
        :return int: The maximum number of items the session can hold.
        """
        return self._capacity

    def size(self) -> int:
        """
        Get the current size of the session cache.
        :return int: The current number of items in the session cache.
        """
        with self._lock:
            return len(self._cache)

    def set(self, session: Session) -> None:
        """
        Store a session in the cache with the given key.

        If the session already exists, it is replaced. Otherwise, if the cache
        is at capacity, the least recently used session is removed before adding
        the new session. In either case the session is marked as most recently used.

        :param session: The session object to be stored in the cache.
        """
        with self._lock:
            if session.id in self._cache:
                del self._cache[session.id]
            elif len(self._cache) >= self._capacity:
                self._cache.popitem(last=False)
            self._cache.__setitem__(session.id, session)

    def get(self, id: str) -> Session | None:
        """
        Retrieve a session by key and update its access order.

        The retrieved session is marked as most recently used.

        :param id (str): The unique identifier for the session to retrieve.
        :return Session | None: The session object if found, None otherwise.
        """
        with self._lock:
            if id in self._cache:
                self._cache.move_to_end(id)
                return self._cache[id]
            return None

    def clear(self) -> None:
        """
        Clear all sessions from the cache.
        """
        with self._lock:
            self._cache.clear()
