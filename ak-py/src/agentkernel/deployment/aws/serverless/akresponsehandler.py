import json
import logging
from typing import Any, Dict, Optional

from ....core.config import AKConfig
from ....core.model import ExecutionMode, StreamChunk
from ....pipeline.envelope import ATTR_STATUS_CODE
from ..core.response_store import ResponseStoreFactory
from ..core.sqs_handler import SQSHandler
from .core import LambdaSQSConsumer
from .core.router.ws_lambda import LambdaWSHandler


class ResponseHandler(LambdaSQSConsumer):
    """
    Lambda SQS consumer that processes response messages and stores them in the configured response store.
    """

    _log = logging.getLogger("ak.aws.responsehandler")
    _response_store = None
    _base_ws_handler = None
    # A reply sent without a status predates the runner forwarding one, so it keeps its old meaning.
    _DEFAULT_STATUS_CODE = 200
    _PERMANENT_FAILURE_STATUS_CODE = 500

    @classmethod
    def _get_max_receive_count(cls) -> int:
        return AKConfig.get().execution.queues.output.max_receive_count

    @classmethod
    def _get_response_store(cls):
        if cls._response_store is None:
            cls._response_store = ResponseStoreFactory.create()
        return cls._response_store

    @classmethod
    def _get_base_ws_handler(cls):
        if cls._base_ws_handler is None:
            cls._base_ws_handler = LambdaWSHandler()
        return cls._base_ws_handler

    @classmethod
    def _construct_message_for_store(cls, record: Dict[str, Any], body: Optional[Any] = None, status_code: Optional[int] = None) -> Dict[str, Any]:
        """
        Construct the message object to be stored in the response store.

        :param record: SQS record
        :param body: Optional message body payload. If not provided, uses record["body"]
        :param status_code: Status to store; when omitted it is read from the status the agent
            runner forwarded on the record
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
        return {
            "session_id": session_id,
            "request_id": request_id,
            "status_code": status_code if status_code is not None else cls._resolve_status_code(message_attributes),
            "body": message_body,
        }

    @classmethod
    def _resolve_status_code(cls, message_attributes: Dict[str, Any]) -> int:
        """
        Resolve the status the agent runner forwarded on the output message.

        :param message_attributes: Custom attributes of the output SQS record
        :return: The forwarded status, or 200 when it is absent or unparseable
        """
        raw_status_code = message_attributes.get(ATTR_STATUS_CODE)
        if raw_status_code is None:
            return cls._DEFAULT_STATUS_CODE
        try:
            return int(raw_status_code)
        except (TypeError, ValueError):
            cls._log.warning(f"Ignoring unparseable {ATTR_STATUS_CODE} attribute '{raw_status_code}'")
            return cls._DEFAULT_STATUS_CODE

    @classmethod
    def _broadcast_via_websocket(cls, record: Dict[str, Any], message_type: Optional[LambdaWSHandler.MessageType] = None) -> None:
        """
        Broadcast a message via WebSocket; wraps the body in a typed envelope when message_type is given, else sends it raw.

        :param record: SQS record containing the response payload
        :param message_type: Optional envelope type; if None the body is broadcast directly
        :raises ValueError: If endpoint_url or user_id is missing in message attributes
        """
        message_attributes = SQSHandler.get_message_custom_attributes(record)
        endpoint_url = message_attributes.get("endpoint_url")
        user_id = message_attributes.get("user_id")

        if not endpoint_url:
            raise ValueError("endpoint_url is required in SQS message attributes")
        if not user_id:
            raise ValueError("user_id is required in SQS message attributes")

        message_body = record.get("body")
        if isinstance(message_body, str):
            message_body = json.loads(message_body)
        if not isinstance(message_body, dict):
            raise ValueError("SQS record body must be a JSON object")

        base_ws = cls._get_base_ws_handler()
        cls._log.info(f"Broadcasting message via WebSocket for user_id: {user_id}, endpoint_url: {endpoint_url}")
        base_ws.broadcast(endpoint_url=endpoint_url, message=message_body, user_id=user_id, message_type=message_type)
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

        if AKConfig.get().execution.mode == ExecutionMode.ASYNC:
            cls._broadcast_via_websocket(record, message_type=LambdaWSHandler.MessageType.CHAT_RESPONSE)
        elif AKConfig.get().execution.mode == ExecutionMode.STREAM:
            cls._broadcast_via_websocket(record, message_type=LambdaWSHandler.MessageType.STREAM_CHUNK)
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
        cls._log.error(f"Permanent failure: {record}: Retried message {cls._get_max_receive_count()} times")

        try:
            message_attributes = SQSHandler.get_message_custom_attributes(record)
            session_id = message_attributes["message_group_id"]
            error_message = {
                "error": f"Failed to process message after {cls._get_max_receive_count()} retries",
                "request_id": message_attributes.get("request_id"),
            }

            if AKConfig.get().execution.mode == ExecutionMode.ASYNC:
                # Broadcast error via WebSocket for ASYNC mode
                endpoint_url = message_attributes.get("endpoint_url")
                user_id = message_attributes.get("user_id")

                if endpoint_url and user_id:
                    base_ws = cls._get_base_ws_handler()
                    cls._log.info(f"Broadcasting permanent failure error via WebSocket for user_id: {user_id}")
                    error_message["session_id"] = session_id
                    base_ws.broadcast(
                        endpoint_url=endpoint_url,
                        message=error_message,
                        user_id=user_id,
                        message_type=LambdaWSHandler.MessageType.SYSTEM_RESPONSE,
                    )
                    cls._log.info(f"Successfully broadcasted permanent failure error for user_id: {user_id}")
                else:
                    cls._log.warning("Cannot broadcast permanent failure error: endpoint_url or user_id missing in message attributes")
            elif AKConfig.get().execution.mode == ExecutionMode.STREAM:
                # Broadcast error chunk via WebSocket for STREAM mode
                endpoint_url = message_attributes.get("endpoint_url")
                user_id = message_attributes.get("user_id")

                if endpoint_url and user_id:
                    error_chunk = StreamChunk(
                        error=f"Failed to process message after {cls._get_max_receive_count()} retries",
                        done=True,
                    )
                    error_chunk_body = error_chunk.model_dump(exclude_none=True)
                    error_chunk_body["session_id"] = session_id
                    base_ws = cls._get_base_ws_handler()
                    cls._log.info(f"Broadcasting permanent failure stream chunk via WebSocket for user_id: {user_id}")
                    base_ws.broadcast(
                        endpoint_url=endpoint_url,
                        message=error_chunk_body,
                        user_id=user_id,
                        message_type=LambdaWSHandler.MessageType.STREAM_CHUNK,
                    )
                    cls._log.info(f"Successfully broadcasted permanent failure stream chunk for user_id: {user_id}")
                else:
                    cls._log.warning("Cannot broadcast permanent failure stream chunk: endpoint_url or user_id missing in message attributes")
            else:
                # Store error message in response store for non-ASYNC/STREAM modes
                message = cls._construct_message_for_store(record, body=error_message, status_code=cls._PERMANENT_FAILURE_STATUS_CODE)
                cls._get_response_store().add_message(message)
                cls._log.info(f"Stored permanent failure message for session_id: {message['session_id']}, request_id: {message['request_id']}")
        except Exception as e:
            # Catch the error to prevent this message from being returned as batchItemFailures for another retry
            cls._log.error(f"Failed to handle permanent failure message due to error: {str(e)}")
