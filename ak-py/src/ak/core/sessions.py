from abc import abstractmethod

from .base import Session

class SessionStore: 
    """
    SessionStore is the base class for session storage that allows storage and retrieval of session
    data.
    """

    @abstractmethod
    def load(self, id: str) -> Session:
        """
        Loads a session by its unique identifier.
        :param id: Unique identifier for the session.
        :return: The session associated with the identifier, or a new session if it does not exist
        in storage.
        """
        pass

    @abstractmethod
    def store(self, session: Session) -> None:
        """
        Stores a session, or update it if it already exists in the storage.
        :param session: The session to store.
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        Clears all stored sessions.
        """
        pass


class InMemorySessionStore(SessionStore):
    """
    InMemorySessionStore class provides an in-memory implementation of the SessionStore interface.
    """

    def __init__(self):
        """
        Initializes an InMemorySessionStore instance.
        """
        self._sessions = {}

    def load(self, id: str) -> Session:
        """
        Loads a session by its unique identifier.
        :param id: Unique identifier for the session.
        :return: The session associated with the identifier, or a new session if it does not exist.
        """
        session = self._sessions.get(id)
        if session is None:
            session = Session(id)
            self._sessions[id] = session
        return session

    def store(self, session: Session) -> None:
        """
        Stores a session, or updates it if it already exists in the storage.
        :param session: The session to store.
        """
        self._sessions[session.id] = session

    def clear(self) -> None:
        """
        Clears all stored sessions.
        """
        self._sessions.clear()