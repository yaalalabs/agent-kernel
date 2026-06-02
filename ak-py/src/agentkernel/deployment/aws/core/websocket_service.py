import json
import logging
import time
from typing import Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ...common.websocket_connection_store import WebSocketConnectionStoreABC


class WebSocketConnectionStore(WebSocketConnectionStoreABC):
    """
    Internal DynamoDB data access layer.
    Handles only storage/query operations.
    """

    def __init__(self, table_name: str, ttl: int):
        """
        Initialize the WebSocket connection store.

        :param table_name: DynamoDB table name for storing connections
        :param ttl: Time-to-live in seconds for automatic cleanup of stale connections
        :return: None
        """
        self._table = boto3.resource("dynamodb").Table(table_name)
        self._ttl = ttl
        self._log = logging.getLogger("ak.websocket.connection_store")

    def add_connection(self, user_id: str, connection_id: str) -> None:
        """
        Store a WebSocket connection for a user.

        Stores the connection with an expiry_time attribute for automatic cleanup
        via DynamoDB TTL.

        :param user_id: User identifier
        :param connection_id: WebSocket connection identifier
        :return: None
        """
        expiry_time = int(time.time()) + self._ttl

        self._table.put_item(
            Item={
                "user_id": user_id,
                "connection_id": connection_id,
                "expiry_time": expiry_time,
            }
        )

    def get_connections(self, user_id: str) -> List[str]:
        """
        Retrieve all connection IDs for a given user.

        :param user_id: User identifier
        :return: List of connection IDs
        """
        resp = self._table.query(KeyConditionExpression=Key("user_id").eq(user_id))

        return [item["connection_id"] for item in resp.get("Items", [])]

    def get_user_id(self, connection_id: str) -> Optional[str]:
        """
        Retrieve the user ID for a given connection ID using GSI: connection_id-index.

        :param connection_id: WebSocket connection identifier
        :return: User ID if found, None otherwise
        """

        resp = self._table.query(
            IndexName="connection_id-index",
            KeyConditionExpression=Key("connection_id").eq(connection_id),
        )

        items = resp.get("Items", [])

        if not items:
            return None

        if len(items) > 1:
            self._log.warning(f"Multiple users found for connection_id={connection_id}. Selecting first result.")

        return items[0]["user_id"]

    def delete_connection(self, user_id: str, connection_id: str) -> None:
        """
        Delete a specific connection for a user.

        :param user_id: User identifier
        :param connection_id: WebSocket connection identifier
        :return: None
        """
        self._table.delete_item(
            Key={
                "user_id": user_id,
                "connection_id": connection_id,
            }
        )

    def delete_by_connection_id(self, connection_id: str) -> None:
        """
        Delete a connection by its connection ID using GSI: connection_id-index.

        :param connection_id: WebSocket connection identifier
        :return: None
        """

        resp = self._table.query(
            IndexName="connection_id-index",
            KeyConditionExpression=Key("connection_id").eq(connection_id),
        )

        for item in resp.get("Items", []):
            self.delete_connection(item["user_id"], connection_id)


class WebSocketHandler:
    """
    Main public WebSocket interface.
    Users interact ONLY with this class.
    """

    def __init__(self, conn_table_name: str, ttl: int):
        """
        Initialize the WebSocket handler.

        :param conn_table_name: DynamoDB table name for storing connections
        :param ttl: Time-to-live in seconds for automatic cleanup of stale connections
        :return: None
        """
        self._connection_store = WebSocketConnectionStore(conn_table_name, ttl)
        self._clients: Dict[str, any] = {}
        self._log = logging.getLogger("ak.websocket.manager")

    # internal client resolver (cached per endpoint)
    def _get_api_gateway(self, endpoint_url: str):
        """
        Get or create a cached boto3 API Gateway Management API client for the given endpoint.

        :param endpoint_url: The API Gateway endpoint URL
        :return: Boto3 API Gateway Management API client
        """
        if endpoint_url not in self._clients:
            self._clients[endpoint_url] = boto3.client(
                "apigatewaymanagementapi",
                endpoint_url=endpoint_url,
            )
        return self._clients[endpoint_url]

    @staticmethod
    def construct_endpoint_url_from_event(event: dict) -> str:
        """
        Construct the API Gateway endpoint URL from a WebSocket event.

        :param event: WebSocket event dictionary
        :return: Constructed endpoint URL string
        """
        request_context = event["requestContext"]
        domain_name = request_context["domainName"]
        stage = request_context["stage"]
        return f"https://{domain_name}/{stage}"

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
    def send(self, endpoint_url: str, connection_id: str, message: dict) -> None:
        """
        Send a message to a specific WebSocket connection.

        :param endpoint_url: API Gateway endpoint URL
        :param connection_id: WebSocket connection identifier
        :param message: Message dictionary to send
        :return: None
        """
        try:
            api_gateway = self._get_api_gateway(endpoint_url)

            api_gateway.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps(message).encode("utf-8"),
            )

        except ClientError as e:
            error_code = e.response["Error"]["Code"]

            if error_code == "GoneException":
                self._log.info(f"Cleaning stale connection: {connection_id}")
                self.delete_by_connection_id(connection_id)

            else:
                self._log.exception(f"Failed to send message to connection_id={connection_id}")

    def broadcast(
        self,
        endpoint_url: str,
        message: dict,
        user_id: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Broadcast a message to multiple WebSocket connections.

        :param endpoint_url: API Gateway endpoint URL
        :param message: Message dictionary to broadcast
        :param user_id: User identifier to broadcast to (retrieves all connections for user)
        :param connection_ids: Specific connection IDs to broadcast to
        :return: None
        :raises ValueError: If neither user_id nor connection_ids is provided
        """

        if not user_id and not connection_ids:
            raise ValueError("Provide either user_id or connection_ids")

        if user_id:
            connection_ids = self.get_connections(user_id)

        for connection_id in connection_ids:
            self.send(endpoint_url=endpoint_url, connection_id=connection_id, message=message)
