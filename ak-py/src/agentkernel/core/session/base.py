from abc import ABC, abstractmethod
from collections import OrderedDict
from threading import RLock

from ..base import Session


class SessionStore(ABC):
    """
    SessionStore is the base class for session storage that allows storage and retrieval of session
    data.
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
