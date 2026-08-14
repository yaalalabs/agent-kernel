import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional


class WebSocketConnectionStoreABC(ABC):
    """Abstract base for WebSocket connection storage across cloud providers."""

    _log = logging.getLogger("ak.pipeline.ws.connection_store")

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


class WebSocketHandlerABC(ABC):
    """Abstract base for WebSocket handlers; subclasses provide the cloud-specific transport client."""

    class MessageType(str, Enum):
        """Typed WebSocket broadcast envelope kinds (shared by serverless and containerized)."""

        CHAT_RESPONSE = "CHAT_RESPONSE"
        CHAT_QUEUED = "CHAT_QUEUED"
        SYSTEM_RESPONSE = "SYSTEM_RESPONSE"
        STREAM_CHUNK = "STREAM_CHUNK"

    def __init__(self, connection_store: WebSocketConnectionStoreABC):
        """
        Initialize the WebSocket handler.

        :param connection_store: Cloud-specific connection store implementation
        """
        self._connection_store = connection_store
        self._clients: Dict[str, Any] = {}
        self._log = logging.getLogger("ak.pipeline.ws.handler")

    @abstractmethod
    def get_client(self, endpoint_url: str) -> Any:
        """
        Get or create a cached transport client for the given endpoint.

        :param endpoint_url: The WebSocket management endpoint URL
        :return: Cloud-specific client used to push messages to connections
        """
        pass

    @abstractmethod
    def construct_endpoint_url(self, *args: Any, **kwargs: Any) -> str:
        """
        Construct the WebSocket management endpoint URL from platform-specific context.

        Inputs vary per cloud framework, so each subclass defines its own signature.

        :return: Constructed endpoint URL string
        """
        pass

    @abstractmethod
    def send(self, endpoint_url: str, connection_id: str, message: dict) -> None:
        """
        Send a message to a specific WebSocket connection.

        :param endpoint_url: WebSocket management endpoint URL
        :param connection_id: WebSocket connection identifier
        :param message: Message dictionary to send
        :return: None
        """
        pass

    # Connection Store Public API
    def add_connection(self, user_id: str, connection_id: str) -> None:
        """
        Store a WebSocket connection for a user.

        :param user_id: User identifier
        :param connection_id: WebSocket connection identifier
        :return: None
        """
        self._connection_store.add_connection(user_id, connection_id)

    def get_connections(self, user_id: str) -> List[str]:
        """
        Retrieve all connection IDs for a given user.

        :param user_id: User identifier
        :return: List of connection IDs
        """
        return self._connection_store.get_connections(user_id)

    def get_user_id(self, connection_id: str) -> Optional[str]:
        """
        Retrieve the user ID for a given connection ID.

        :param connection_id: WebSocket connection identifier
        :return: User ID if found, None otherwise
        """
        return self._connection_store.get_user_id(connection_id)

    def delete_connection(self, user_id: str, connection_id: str) -> None:
        """
        Delete a specific connection for a user.

        :param user_id: User identifier
        :param connection_id: WebSocket connection identifier
        :return: None
        """
        self._connection_store.delete_connection(user_id, connection_id)

    def delete_by_connection_id(self, connection_id: str) -> None:
        """
        Delete a connection by its connection ID.

        :param connection_id: WebSocket connection identifier
        :return: None
        """
        self._connection_store.delete_by_connection_id(connection_id)

    # WebSocket Lifecycle Methods
    def on_connect(self, connection_id: str, user_id: str) -> None:
        """
        Handle WebSocket connection establishment.

        :param connection_id: WebSocket connection identifier
        :param user_id: User identifier
        :return: None
        :raises ValueError: If user_id is not provided
        """
        if not user_id:
            raise ValueError("user_id is required")
        self.add_connection(user_id, connection_id)
        self._log.info(f"Connected: user_id={user_id}, connection_id={connection_id}")

    def on_disconnect(self, connection_id: str) -> None:
        """
        Handle WebSocket connection termination.

        :param connection_id: WebSocket connection identifier
        :return: None
        """
        self.delete_by_connection_id(connection_id)
        self._log.info(f"Disconnected: connection_id={connection_id}")

    def on_default(self) -> None:
        """
        Handle unknown WebSocket routes.

        :return: None
        """
        self._log.warning("Unknown websocket route")

    # Message sending operations
    def broadcast(
        self,
        endpoint_url: str,
        message: Dict[str, Any],
        user_id: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
        message_type: Optional["WebSocketHandlerABC.MessageType"] = None,
    ) -> None:
        """
        Broadcast a message to multiple connections

        :param endpoint_url: WebSocket management endpoint URL
        :param message: Message dictionary to broadcast
        :param user_id: User to broadcast to (resolves to all their connections)
        :param connection_ids: Specific connection IDs to broadcast to
        :param message_type: Optional envelope type; wraps message when provided
        :raises ValueError: If neither user_id nor connection_ids is provided
        """

        if not user_id and not connection_ids:
            raise ValueError("Provide either user_id or connection_ids")

        if message_type is not None:
            message = {**message, "type": message_type.value}

        if user_id:
            connection_ids = self.get_connections(user_id)

        for connection_id in connection_ids:
            self.send(endpoint_url=endpoint_url, connection_id=connection_id, message=message)
