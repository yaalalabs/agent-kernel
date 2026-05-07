import json
import time
import boto3
import logging
from typing import List
from boto3.dynamodb.conditions import Key
from typing import Optional

from botocore.exceptions import ClientError

from ...common.websocket_connection_store import WebSocketConnectionStoreABC


class WebSocketConnectionStore:
    """
    Internal DynamoDB data access layer.
    Handles only storage/query operations.
    """

    def __init__(self, table_name: str, ttl: int):
        self._table = boto3.resource("dynamodb").Table(table_name)
        self._ttl = ttl
        self._log = logging.getLogger("ak.websocket.connection_store")

    def add_connection(self, user_id: str, connection_id: str) -> None:
        expiry_time = int(time.time()) + self._ttl

        self._table.put_item(
            Item={
                "user_id": user_id,
                "connection_id": connection_id,
                "expiry_time": expiry_time,
            }
        )

    def get_connections(self, user_id: str) -> List[str]:
        resp = self._table.query(
            KeyConditionExpression=Key("user_id").eq(user_id)
        )

        return [item["connection_id"] for item in resp.get("Items", [])]

    def get_user_id(self, connection_id: str) -> Optional[str]:
        """
        Uses GSI: connection_id-index
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
        self._table.delete_item(
            Key={
                "user_id": user_id,
                "connection_id": connection_id,
            }
        )

    def delete_by_connection_id(self, connection_id: str) -> None:
        """
        Uses GSI: connection_id-index
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
    def __init__(self, endpoint_url: str, conn_table_name: str, ttl: int):
        self._connection_store = WebSocketConnectionStore(conn_table_name, ttl)
        self._api_gateway = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=endpoint_url,
        )
        self._log = logging.getLogger("ak.websocket.manager")

    # Connection Store Public API
    def add_connection(self, user_id: str, connection_id: str) -> None:
        self._connection_store.add_connection(user_id, connection_id)

    def get_connections(self, user_id: str) -> List[str]:
        return self._connection_store.get_connections(user_id)

    def get_user_id(self, connection_id: str) -> Optional[str]:
        return self._connection_store.get_user_id(connection_id)

    def delete_connection(self, user_id: str, connection_id: str) -> None:
        self._connection_store.delete_connection(user_id, connection_id)

    def delete_by_connection_id(self, connection_id: str) -> None:
        self._connection_store.delete_by_connection_id(connection_id)

    # WebSocket Lifecycle Methods
    def on_connect(self, connection_id: str, user_id: str) -> None:
        if not user_id:
            raise ValueError("user_id is required")
        self.add_connection(user_id, connection_id)
        self._log.info(f"Connected: user_id={user_id}, connection_id={connection_id}")

    def on_disconnect(self, connection_id: str) -> None:
        self.delete_by_connection_id(connection_id)
        self._log.info(f"Disconnected: connection_id={connection_id}")

    def on_default(self) -> None:
        self._log.warning("Unknown websocket route")

    # Message sending operations
    def send(self, connection_id: str, message: dict) -> None:
        try:
            self._api_gateway.post_to_connection(
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
        message: dict,
        user_id: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
    ) -> None:
        if not user_id and not connection_ids:
            raise ValueError("Provide either user_id or connection_ids")

        if user_id:
            connection_ids = self.get_connections(user_id)

        for connection_id in connection_ids:
            self.send(connection_id=connection_id, message=message)