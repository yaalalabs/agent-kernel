import json
import time
import boto3
import logging
from typing import List
from boto3.dynamodb.conditions import Key
from typing import Optional

from botocore.exceptions import ClientError

from ...common.websocket_connection_store import WebSocketConnectionStoreABC


class WebSocketConnectionStore(WebSocketConnectionStoreABC):
    def __init__(self, table_name: str, ttl: int):
        self._connection_table = boto3.resource("dynamodb").Table(table_name)
        self._ttl = ttl
        self._log = logging.getLogger("ak.websocket.connection_store")

    def add_connection(self, user_id: str, connection_id: str) -> None:
        expiry_time = int(time.time()) + self._ttl
        self._connection_table.put_item(
            Item={
                "user_id": user_id,
                "connection_id": connection_id,
                "expiry_time": expiry_time,
            }
        )

    def get_connections(self, user_id: str) -> List[str]:
        resp = self._connection_table.query(
            KeyConditionExpression=Key("user_id").eq(user_id)
        )
        return [item["connection_id"] for item in resp.get("Items", [])]

    def delete_connection(self, user_id: str, connection_id: str) -> None:
        self._connection_table.delete_item(
            Key={
                "user_id": user_id,
                "connection_id": connection_id,
            }
        )

    def delete_by_connection_id(self, connection_id: str) -> None:
        """
        Uses GSI: connection_id-index
        """
        resp = self._connection_table.query(
            IndexName="connection_id-index",
            KeyConditionExpression=Key("connection_id").eq(connection_id),
        )

        for item in resp.get("Items", []):
            self.delete_connection(item["user_id"], connection_id)

    def get_user_id(self, connection_id: str) -> Optional[str]:
        """
        Uses GSI: connection_id-index to get user_id for a given connection_id
        Returns None if no connection found
        """
        resp = self._connection_table.query(
            IndexName="connection_id-index",
            KeyConditionExpression=Key("connection_id").eq(connection_id),
        )
        items = resp.get("Items", [])
        if items:
            if len(items) > 1:
                self._log.warning(f"There is more than 1 user for connection_id {connection_id}, selecting first one")
            return items[0]["user_id"]
        return None


class WebSocketHandler:
    def __init__(self, endpoint_url: str, conn_table_name: str, ttl: int):
        self._connection_store = WebSocketConnectionStore(conn_table_name, ttl)
        self._api_gateway = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=endpoint_url,
        )
        self._log = logging.getLogger("ak.websocket.handler")

    def on_connect(self, connection_id: str, user_id: str):
        if not user_id:
            raise ValueError("user_id is required")
        self._connection_store.add_connection(user_id, connection_id)
        self._log.info(f"Connected: {user_id} -> {connection_id}")

    def on_disconnect(self, connection_id: str):
        self._connection_store.delete_by_connection_id(connection_id)
        self._log.info(f"Disconnected: {connection_id}")

    def on_default(self):
        self._log.warning("Unknown route")

    def broadcast(
        self,
        message: dict,
        user_id: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
    ):
        if not user_id and not connection_ids:
            raise ValueError("Provide user_id or connection_ids")

        if user_id:
            connection_ids = self._connection_store.get_connections(user_id)

        for connection_id in connection_ids:
            try:
                self._api_gateway.post_to_connection(
                    ConnectionId=connection_id,
                    Data=json.dumps(message).encode("utf-8"),  # utf-8 format is needed by post_to_connection()
                )

            except ClientError as e:
                if e.response["Error"]["Code"] == "GoneException":
                    self._log.info(f"Cleaning stale connection: {connection_id}")
                    self._connection_store.delete_by_connection_id(connection_id)
                else:
                    self._log.exception("Send failed")
