import json
import logging
import traceback
from enum import Enum
from typing import Any, Callable, Dict, Tuple

from .....core.model import BaseRequest
from .....core.config import AKConfig
from ....common.chat_service import ChatService
from ...core.websocket_service import WebSocketHandler
from ...core.sqs_handler import SQSHandler


class DefaultWSRoutesHandler:
    _log = logging.getLogger("ak.aws.serverless.default_ws_endpoints")

    class MessageType(Enum):
        """WebSocket message types."""
        CHAT_RESPONSE = "chat_response"
        CHAT_QUEUED = "chat_queued"

    def __init__(self):
        self._config = AKConfig.get()
        self._ws_handler = WebSocketHandler(
            endpoint_url=self._config.websocket_api.endpoint_url,
            conn_table_name=self._config.websocket_api.connection_table_name,
        )
        self._chat_service = ChatService()

    def _parse_body(self, event: Dict[str, Any]) -> BaseRequest:
        body = event.get("body")
        body_dict = json.loads(body) if isinstance(body, str) and body else (body or {})
        return BaseRequest.from_payload(body_dict)

    def _extract_connection_id(self, event: Dict[str, Any]) -> str:
        request_context = event.get("requestContext", {})
        connection_id = request_context.get("connectionId")
        if not connection_id:
            raise ValueError("WebSocket event missing requestContext.connectionId")
        return connection_id

    def _is_queue_mode(self) -> bool:
        """Check if queue mode is enabled (queues are configured)."""
        return (
            self._config.execution.queues.input.url is not None
            and self._config.execution.queues.output.url is not None
        )

    def _build_broadcasting_message(self, message_type: MessageType, **kwargs) -> Dict[str, Any]:
        """
        Build a standardized broadcast message format.
        
        :param message_type: The type of message from MessageType enum
        :param kwargs: Additional fields to include in the message
        :return: Standardized message dictionary
        """
        message = {
            "type": message_type.value,
        }
        message.update(kwargs)
        return message

    def get_routes(self) -> Dict[str, Callable[[Dict[str, Any], Any], Any]]:
        return {
            "/$connect": self._handle_connect,
            "/$disconnect": self._handle_disconnect,
            "/$default": self._handle_default,
            "/chat": self._handle_queue_mode_chat if self._is_queue_mode() else self._handle_direct_chat,
        }

    def _handle_connect(self, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            connection_id = self._extract_connection_id(event)

            request = self._parse_body(event)
            user_id = request.user_id

            self._ws_handler.on_connect(connection_id=connection_id, user_id=user_id)

            return 200, {"status": "CONNECTED"}
        except Exception as e:
            self._log.error(f"WebSocket $connect failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Connect failed"}

    def _handle_disconnect(self, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            connection_id = self._extract_connection_id(event)

            self._ws_handler.on_disconnect(connection_id=connection_id)
            return 200, {"status": "DISCONNECTED"}
        except Exception as e:
            self._log.error(f"WebSocket $disconnect failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Disconnect failed"}

    def _handle_default(self) -> Tuple[int, Dict[str, Any]]:
        try:
            self._ws_handler.on_default()
            return 200, {"status": "OK"}
        except Exception as e:
            self._log.error(f"WebSocket $default failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Default route failed"}

    def _handle_direct_chat(self, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            connection_id = self._extract_connection_id(event)

            request = self._parse_body(event)
            if request.body is None:
                raise ValueError("body is required")

            status_code, res_body = self._chat_service.process_chat_request(
                request.body.model_dump(exclude_none=True)
            )

            self._ws_handler.broadcast(
                message=self._build_broadcasting_message(
                    message_type=self.MessageType.CHAT_RESPONSE,
                    **res_body,
                ),
                connection_ids=[connection_id],
            )

            return 200, {"status": "SENT"}
        except Exception as e:
            self._log.error(f"WebSocket chat failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Chat failed"}

    def _handle_queue_mode_chat(self, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """
        Handle chat request in queue mode - send message to SQS input queue.
        :param event: WebSocket event
        :return: Tuple of status code and response body
        """
        try:
            connection_id = self._extract_connection_id(event)
            request = self._parse_body(event)
            request_body = request.body
            if request_body is None:
                raise ValueError("body is required")
            if not request.request_id:
                raise ValueError("request_id is required")

            session_id = request_body.session_id
            if not session_id:
                raise ValueError("session_id is required")

            self._log.info(f"Sending WebSocket chat request to queue: request_id={request.request_id}, session_id={session_id}")

            response = SQSHandler.send_message_to_input_queue(
                message_body=request_body,
                message_group_id=session_id,
                message_deduplication_id=request.request_id,
                request_id=request.request_id,
                user_id=request.user_id,
            )

            self._log.info(f"Message sent to input queue successfully: {response}")

            self._ws_handler.broadcast(
                message=self._build_broadcasting_message(
                    message_type=self.MessageType.CHAT_QUEUED,
                    status="ACCEPTED",
                    request_id=request.request_id,
                ),
                connection_ids=[connection_id],
            )

            return 200, {"status": "QUEUED", "request_id": request.request_id}
        except Exception as e:
            self._log.error(f"WebSocket queue mode chat failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Queue mode chat failed"}