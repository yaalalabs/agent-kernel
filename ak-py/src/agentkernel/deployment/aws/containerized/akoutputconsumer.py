from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ....core.config import AKConfig
from ....core.model import ExecutionMode, StreamChunk
from ..core.response_store import ResponseDBHandler
from ..core.sqs_handler import SQSHandler
from ..core.websocket_service import AWSWebSocketHandler, WebSocketConnectionStore
from .core import ECSSQSConsumer


class ECSOutputConsumer(ECSSQSConsumer):
    """
    ECS Output Consumer — polls the Output Queue and delivers results: pushed over
    WebSocket in ASYNC mode, else written to the Response Store.

    Extends ECSSQSConsumer so it inherits the blocking SQS poll loop via
    run(). Started as Thread 2 by ECSIOHandler.
    """

    _log = logging.getLogger("ak.ecs.outputconsumer")
    _config = AKConfig.get()
    max_receive_count = _config.execution.queues.output.max_receive_count
    num_consumers = _config.execution.queues.output.no_of_consumers

    _response_store = None
    _websocket_handler = None

    @classmethod
    def get_queue_url(cls) -> str:
        return cls._config.execution.queues.output.url

    @classmethod
    def _get_response_store(cls):
        if cls._response_store is None:
            cls._response_store = ResponseDBHandler().get_store()
        return cls._response_store

    @classmethod
    def _get_websocket_handler(cls) -> AWSWebSocketHandler:
        if cls._websocket_handler is None:
            ws_cfg = cls._config.websocket_api
            if not ws_cfg.connection_table or not ws_cfg.connection_table.table_name:
                raise ValueError("websocket_api.connection_table.table_name is required for WebSocket mode")
            connection_store = WebSocketConnectionStore(
                table_name=ws_cfg.connection_table.table_name,
                ttl=ws_cfg.connection_table.ttl,
            )
            cls._websocket_handler = AWSWebSocketHandler(connection_store=connection_store)
        return cls._websocket_handler

    @classmethod
    def process_message(cls, record: Dict[str, Any]) -> None:
        """
        Process one Output Queue message: push over WebSocket (ASYNC) or write to the Response Store.

        :param record: boto3 SQS ``receive_message`` record
        """
        message_id = record.get("MessageId")
        cls._log.info(f"[OUTPUT START] Processing output message {message_id}")

        exec_mode = cls._config.execution.mode
        message_type = None
        if exec_mode == ExecutionMode.ASYNC:
            message_type = AWSWebSocketHandler.MessageType.CHAT_RESPONSE
        elif exec_mode == ExecutionMode.STREAM:
            message_type = AWSWebSocketHandler.MessageType.STREAM_CHUNK

        if exec_mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
            cls._broadcast_via_websocket(record, message_type=message_type)
            cls._log.info(f"[OUTPUT DONE] Broadcasted {message_type.value} {message_id} via WebSocket")
            return

        message = cls._construct_message_for_store(record)
        cls._log.info(
            f"[OUTPUT STORE] Writing to DynamoDB — request_id={message['request_id']}, "
            f"session_id={message['session_id']}, body_keys={list(message.get('body', {}).keys()) if isinstance(message.get('body'), dict) else 'N/A'}"
        )
        cls._get_response_store().add_message(message)
        cls._log.info(f"[OUTPUT DONE] Stored response — session_id={message['session_id']} " f"request_id={message['request_id']}")

    @classmethod
    def on_permanent_failure(cls, record: Dict[str, Any]) -> None:
        """
        Handle an output message that exceeded ``max_receive_count``: push an error over
        WebSocket (ASYNC), or write an error entry to the Response Store so the waiting
        HTTP caller gets a response instead of hanging.

        :param record: boto3 SQS ``receive_message`` record
        """
        max_retries = cls._config.execution.queues.output.max_receive_count
        cls._log.error(f"Permanent failure for output message {record.get('MessageId')} " f"after {max_retries} retries")

        try:
            message_attributes = SQSHandler.get_message_custom_attributes(record)
            request_id = message_attributes.get("request_id")
            session_id = SQSHandler.get_message_system_attributes(record).get("MessageGroupId")
            error_payload = {
                "error": f"Failed to process message after {max_retries} retries",
                "request_id": request_id,
            }
            if session_id:
                error_payload["session_id"] = session_id

            exec_mode = cls._config.execution.mode
            message_type = None
            if exec_mode == ExecutionMode.ASYNC:
                message_type = AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE
            elif exec_mode == ExecutionMode.STREAM:
                message_type = AWSWebSocketHandler.MessageType.STREAM_CHUNK

            if exec_mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
                if message_type == AWSWebSocketHandler.MessageType.STREAM_CHUNK:
                    error_message = StreamChunk(error=error_payload["error"], done=True).model_dump(exclude_none=True)
                    if session_id:
                        error_message["session_id"] = session_id
                else:
                    error_message = error_payload

                endpoint_url = message_attributes.get("endpoint_url")
                user_id = message_attributes.get("user_id")
                if endpoint_url and user_id:
                    cls._get_websocket_handler().broadcast(
                        endpoint_url=endpoint_url,
                        message=error_message,
                        user_id=user_id,
                        message_type=message_type,
                    )
                    cls._log.info(f"Broadcasted permanent-failure {message_type.value} via WebSocket — user_id={user_id}")
                else:
                    cls._log.warning(f"Cannot broadcast permanent-failure {message_type.value}: endpoint_url or user_id missing")
                return

            error_body = json.dumps(error_payload)
            message = cls._construct_message_for_store(record, body=error_body)
            cls._get_response_store().add_message(message)
            cls._log.info(f"Stored permanent-failure error — " f"session_id={message['session_id']} " f"request_id={message['request_id']}")
        except Exception:
            cls._log.exception("Failed to handle permanent-failure output message")

    @classmethod
    def _construct_message_for_store(cls, record: Dict[str, Any], body: Any = None) -> Dict[str, Any]:
        """
        Build the dict to write into the Response Store.

        :param record: boto3 SQS record
        :param body: Override body (string or dict). Defaults to record["Body"].
        :raises ValueError: If request_id is missing from message attributes.
        """
        message_body = body if body is not None else record.get("Body", "{}")
        if isinstance(message_body, str):
            message_body = json.loads(message_body)

        message_attributes = SQSHandler.get_message_custom_attributes(record)
        request_id = message_attributes.get("request_id")
        if not request_id:
            raise ValueError("request_id is required in SQS message attributes")

        return {
            "session_id": message_body.get("session_id"),
            "request_id": request_id,
            "body": message_body,
        }

    @classmethod
    def _broadcast_via_websocket(cls, record: Dict[str, Any], message_type: AWSWebSocketHandler.MessageType) -> None:
        """
        Push an output message to the client over WebSocket.

        :param record: boto3 SQS record
        :param message_type: Envelope type to broadcast with (CHAT_RESPONSE for ASYNC, STREAM_CHUNK for STREAM)
        :raises ValueError: If endpoint_url or user_id is missing.
        """
        message_attributes = SQSHandler.get_message_custom_attributes(record)
        endpoint_url = message_attributes.get("endpoint_url")
        user_id = message_attributes.get("user_id")

        if not endpoint_url:
            raise ValueError("endpoint_url is required in SQS message attributes for WebSocket mode")
        if not user_id:
            raise ValueError("user_id is required in SQS message attributes for WebSocket mode")

        message_body = record.get("Body", "{}")
        if isinstance(message_body, str):
            message_body = json.loads(message_body)

        cls._log.info(f"Broadcasting via WebSocket — user_id={user_id} endpoint={endpoint_url}")
        cls._get_websocket_handler().broadcast(
            endpoint_url=endpoint_url,
            message=message_body,
            user_id=user_id,
            message_type=message_type,
        )
