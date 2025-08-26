from abc import abstractmethod, ABC

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
