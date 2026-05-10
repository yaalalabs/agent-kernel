import json
import logging
from typing import Any, Dict, Optional

from ....core.config import AKConfig
from ....core.model import ExecutionMode
from ..core.response_store import ResponseDBHandler
from ..core.sqs_handler import SQSHandler
from ..core.websocket_service import WebSocketHandler
from .core import LambdaSQSConsumer


class ResponseHandler(LambdaSQSConsumer):
    """
    Lambda SQS consumer that processes response messages and stores them in the configured response store.
    """

    _log = logging.getLogger("ak.aws.responsehandler")
    _response_store = None
    _websocket_handler = None
    _config = AKConfig.get()
    max_receive_count: int = _config.execution.queues.output.max_receive_count

    @classmethod
    def _get_response_store(cls):
        if cls._response_store is None:
            cls._response_store = ResponseDBHandler().get_store()
        return cls._response_store

    @classmethod
    def _get_websocket_handler(cls):
        if cls._websocket_handler is None:
            ws_config = cls._config.websocket_api
            if not ws_config.connection_table or not ws_config.connection_table.table_name:
                raise ValueError("websocket_api.connection_table.table_name is required for WebSocket handler")
            cls._websocket_handler = WebSocketHandler(
                conn_table_name=ws_config.connection_table.table_name,
                ttl=ws_config.connection_table.ttl
            )
        return cls._websocket_handler

    @classmethod
    def _construct_message_for_store(cls, record: Dict[str, Any], body: Optional[Any] = None) -> Dict[str, Any]:
        """
        Construct the message object to be stored in the response store.

        :param record: SQS record
        :param body: Optional message body payload. If not provided, uses record["body"]
        :return: Message dictionary for storage
        :raises ValueError: If request_id is missing in SQS message attributes
        """
        message_body = body if body is not None else record.get("body")
        if isinstance(message_body, str):
            message_body = json.loads(message_body)
        session_id = message_body.get("session_id")

        message_attributes = SQSHandler.get_message_custom_attributes(record)
        request_id = message_attributes.get("request_id")
        if not request_id:
            raise ValueError("request_id is required in SQS message attributes")
        message = {"session_id": session_id, "request_id": request_id, "body": message_body}
        return message

    @classmethod
    def _broadcast_via_websocket(cls, record: Dict[str, Any]) -> None:
        """
        Broadcast the message via WebSocket for ASYNC execution mode.

        Extracts endpoint_url, user_id from custom attributes and broadcasts the message body.

        :param record: SQS record containing the response payload
        :return: None
        :raises ValueError: If endpoint_url or user_id is missing in message attributes
        """
        message_attributes = SQSHandler.get_message_custom_attributes(record)
        endpoint_url = message_attributes.get("endpoint_url")
        user_id = message_attributes.get("user_id")

        if not endpoint_url:
            raise ValueError("endpoint_url is required in SQS message attributes for ASYNC mode")
        if not user_id:
            raise ValueError("user_id is required in SQS message attributes for ASYNC mode")

        message_body = record.get("body")
        if isinstance(message_body, str):
            message_body = json.loads(message_body)

        cls._log.info(f"Broadcasting message via WebSocket for user_id: {user_id}, endpoint_url: {endpoint_url}")
        cls._get_websocket_handler().broadcast(
            endpoint_url=endpoint_url,
            message=message_body,
            user_id=user_id
        )
        cls._log.info(f"Successfully broadcasted message for user_id: {user_id}")

    @classmethod
    def process_message(cls, record: Dict[str, Any]) -> None:
        """
        Process a single SQS record based on execution mode.

        - ASYNC mode: Broadcast via WebSocket
        - Other modes: Store in response store

        :param record: SQS record containing the response payload
        :return: None
        """
        cls._log.info(f"Processing message: {record}")

        if cls._config.execution.mode == ExecutionMode.ASYNC:
            cls._broadcast_via_websocket(record)
        else:
            message = cls._construct_message_for_store(record)
            cls._get_response_store().add_message(message)
            cls._log.info(f"Stored message for session_id: {message['session_id']}, request_id: {message['request_id']}")

    @classmethod
    def on_permanent_failure(cls, record: Dict[str, Any]) -> None:
        """
        Handle messages that have reached their maximum retry count based on execution mode.

        - ASYNC mode: Broadcast error via WebSocket
        - Other modes: Store error message in response store

        :param record: SQS record that failed processing after all retries
        :return: None
        """
        cls._log.error(f"Permanent failure: {record}: Retried message {cls.max_receive_count} times")

        try:
            error_message = {
                "error": f"Failed to process message after {cls.max_receive_count} retries",
                "request_id": SQSHandler.get_message_custom_attributes(record).get("request_id"),
            }

            if cls._config.execution.mode == ExecutionMode.ASYNC:
                # Broadcast error via WebSocket for ASYNC mode
                message_attributes = SQSHandler.get_message_custom_attributes(record)
                endpoint_url = message_attributes.get("endpoint_url")
                user_id = message_attributes.get("user_id")

                if endpoint_url and user_id:
                    cls._log.info(f"Broadcasting permanent failure error via WebSocket for user_id: {user_id}")
                    cls._get_websocket_handler().broadcast(
                        endpoint_url=endpoint_url,
                        message=error_message,
                        user_id=user_id
                    )
                    cls._log.info(f"Successfully broadcasted permanent failure error for user_id: {user_id}")
                else:
                    cls._log.warning("Cannot broadcast permanent failure error: endpoint_url or user_id missing in message attributes")
            else:
                # Store error message in response store for non-ASYNC modes
                error_body = json.dumps(error_message)
                message = cls._construct_message_for_store(record, body=error_body)
                cls._get_response_store().add_message(message)
                cls._log.info(f"Stored permanent failure message for session_id: {message['session_id']}, request_id: {message['request_id']}")
        except Exception as e:
            # Catch the error to prevent this message from being returned as batchItemFailures for another retry
            cls._log.error(f"Failed to handle permanent failure message due to error: {str(e)}")
