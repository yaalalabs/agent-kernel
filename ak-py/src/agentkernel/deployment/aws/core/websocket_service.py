import json
import logging
import time

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ....core.model import Principal
from ...common.websocket_service import WebSocketConnectionStoreABC, WebSocketHandlerABC


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

    def add_connection(self, user_id: str, connection_id: str, principal: Principal | None = None) -> None:
        """
        Store a WebSocket connection for a user.

        Stores the connection with an expiry_time attribute for automatic cleanup via DynamoDB TTL
        and, when the surface authenticated one, the principal as JSON so later frames run as it.

        :param user_id: User identifier (the principal's subject)
        :param connection_id: WebSocket connection identifier
        :param principal: The authenticated principal the connection belongs to, when known
        :return: None
        """
        expiry_time = int(time.time()) + self._ttl

        item = {
            "user_id": user_id,
            "connection_id": connection_id,
            "expiry_time": expiry_time,
        }
        if principal is not None:
            item["principal"] = principal.model_dump_json()
        self._table.put_item(Item=item)

    def get_connections(self, user_id: str) -> list[str]:
        """
        Retrieve all connection IDs for a given user.

        :param user_id: User identifier
        :return: List of connection IDs
        """
        resp = self._table.query(KeyConditionExpression=Key("user_id").eq(user_id))

        return [item["connection_id"] for item in resp.get("Items", [])]

    def get_user_id(self, connection_id: str) -> str | None:
        """
        Retrieve the user ID for a given connection ID using GSI: connection_id-index.

        :param connection_id: WebSocket connection identifier
        :return: User ID if found, None otherwise
        """
        item = self._get_connection(connection_id)
        return item["user_id"] if item is not None else None

    def get_principal(self, connection_id: str) -> Principal | None:
        """
        Retrieve the principal stored for a connection using GSI: connection_id-index.

        :param connection_id: WebSocket connection identifier
        :return: The principal written at ``$connect``, or None when the connection is unknown or its
            row predates principals
        """
        item = self._get_connection(connection_id)
        raw = item.get("principal") if item is not None else None
        return Principal.model_validate_json(raw) if raw else None

    def _get_connection(self, connection_id: str) -> dict | None:
        """
        Query the connection row for a connection ID using GSI: connection_id-index.

        :param connection_id: WebSocket connection identifier
        :return: The first matching item, or None when there is none
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

        return items[0]

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


class AWSWebSocketHandler(WebSocketHandlerABC):
    """
    Main public WebSocket interface for AWS (API Gateway Management API + DynamoDB).
    Users interact ONLY with this class.
    """

    # internal client resolver (cached per endpoint)
    def get_client(self, endpoint_url: str):
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
    def construct_endpoint_url(event: dict) -> str:
        """
        Construct the API Gateway endpoint URL from a WebSocket event.

        :param event: WebSocket event dictionary
        :return: Constructed endpoint URL string
        """
        request_context = event["requestContext"]
        domain_name = request_context["domainName"]
        stage = request_context["stage"]
        return f"https://{domain_name}/{stage}"

    def on_connect(self, connection_id: str, principal: Principal) -> None:
        """
        Record an authenticated connection under its principal's subject.

        Overrides the base hook, which takes a bare user id: the AWS store keeps the whole principal
        beside the subject so the frames that follow can run as it.

        :param connection_id: WebSocket connection identifier
        :param principal: The principal the surface authenticated at ``$connect``
        :return: None
        """
        self._connection_store.add_connection(principal.subject, connection_id, principal)
        self._log.info(f"Connected: subject={principal.subject}, connection_id={connection_id}")

    def get_principal(self, connection_id: str) -> Principal | None:
        """
        Retrieve the principal stored for a connection.

        :param connection_id: WebSocket connection identifier
        :return: The principal written at ``$connect``, or None when unknown
        """
        return self._connection_store.get_principal(connection_id)

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
            api_gateway = self.get_client(endpoint_url)

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
