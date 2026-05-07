from abc import ABC, abstractmethod
from typing import List, Optional


class WebSocketConnectionStoreABC(ABC):
    """
    Abstract base class for WebSocket connection storage systems.
    Supports different cloud providers (AWS, GCP, Azure, etc.)
    """

    _log = __import__("logging").getLogger("ak.deployment.websocket_connection_store")

    @abstractmethod
    def add_connection(self, user_id: str, connection_id: str) -> None:
        """
        Store a WebSocket connection for a user.

        :param user_id: User identifier
        :param connection_id: WebSocket connection identifier
        :return: None
        """
        pass

    @abstractmethod
    def get_connections(self, user_id: str) -> List[str]:
        """
        Retrieve all connection IDs for a given user.

        :param user_id: User identifier
        :return: List of connection IDs
        """
        pass

    @abstractmethod
    def get_user_id(self, connection_id: str) -> Optional[str]:
        """
        Retrieve the user ID for a given connection ID.

        :param connection_id: WebSocket connection identifier
        :return: User ID if found, None otherwise
        """
        pass

    @abstractmethod
    def delete_connection(self, user_id: str, connection_id: str) -> None:
        """
        Delete a specific connection for a user.

        :param user_id: User identifier
        :param connection_id: WebSocket connection identifier
        :return: None
        """
        pass

    @abstractmethod
    def delete_by_connection_id(self, connection_id: str) -> None:
        """
        Delete a connection by its connection ID (regardless of user).

        :param connection_id: WebSocket connection identifier
        :return: None
        """
        pass
