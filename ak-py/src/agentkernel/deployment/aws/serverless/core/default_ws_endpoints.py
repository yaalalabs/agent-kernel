import json
import logging
import os
import traceback
from typing import Any, Callable, Dict, Optional, Tuple

from .....core.model import BaseRequest
from .....core.config import AKConfig
from ....common.chat_service import ChatService
from ...core.websocket_service import WebSocketHandler


class DefaultWSRoutesHandler:
    _log = logging.getLogger("ak.aws.serverless.default_ws_endpoints")

    _ws_handler: Optional[WebSocketHandler] = None
    _chat_service: Optional[ChatService] = None

    @classmethod
    def _get_config(cls):
        return AKConfig.get()

    @classmethod
    def _get_chat_service(cls) -> ChatService:
        if cls._chat_service is None:
            cls._chat_service = ChatService()
        return cls._chat_service

    @classmethod
    def _get_ws_handler(cls) -> WebSocketHandler:
        if cls._ws_handler is not None:
            return cls._ws_handler

        cls._ws_handler = WebSocketHandler(
            endpoint_url=cls._get_config().websocket_api.endpoint_url,
            conn_table_name=cls._get_config().websocket_api.connection_table_name,
        )
        return cls._ws_handler

    @classmethod
    def _parse_body(cls, event: Dict[str, Any]) -> BaseRequest:
        body = event.get("body")
        body_dict = json.loads(body) if isinstance(body, str) and body else (body or {})
        return BaseRequest.from_payload(body_dict)

    @classmethod
    def _extract_connection_id(cls, event: Dict[str, Any]) -> str:
        request_context = event.get("requestContext", {})
        connection_id = request_context.get("connectionId")
        if not connection_id:
            raise ValueError("WebSocket event missing requestContext.connectionId")
        return connection_id

    @classmethod
    def get_routes(cls) -> Dict[str, Callable[[Dict[str, Any], Any], Any]]:
        return {
            "/$connect": cls._handle_connect,
            "/$disconnect": cls._handle_disconnect,
            "/$default": cls._handle_default,
            "/chat": cls._handle_chat,
        }

    @classmethod
    def _handle_connect(cls, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            connection_id = cls._extract_connection_id(event)

            request = cls._parse_body(event)
            user_id = request.user_id

            cls._get_ws_handler().on_connect(connection_id=connection_id, user_id=user_id)

            return 200, {"status": "CONNECTED"}
        except Exception as e:
            cls._log.error(f"WebSocket $connect failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Connect failed"}

    @classmethod
    def _handle_disconnect(cls, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            connection_id = cls._extract_connection_id(event)

            cls._get_ws_handler().on_disconnect(connection_id=connection_id)
            return 200, {"status": "DISCONNECTED"}
        except Exception as e:
            cls._log.error(f"WebSocket $disconnect failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Disconnect failed"}

    @classmethod
    def _handle_default(cls) -> Tuple[int, Dict[str, Any]]:
        try:
            cls._get_ws_handler().on_default()
            return 200, {"status": "OK"}
        except Exception as e:
            cls._log.error(f"WebSocket $default failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Default route failed"}

    @classmethod
    def _handle_chat(cls, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            connection_id = cls._extract_connection_id(event)

            request = cls._parse_body(event)
            if request.body is None:
                raise ValueError("body is required")

            status_code, res_body = cls._get_chat_service().process_chat_request(
                request.body.model_dump(exclude_none=True)
            )

            cls._get_ws_handler().broadcast(
                message={
                    "type": "chat_response", # TODO:: BaseModel here ######################
                    "statusCode": status_code,
                    **res_body,
                },
                connection_ids=[connection_id],
            )

            return 200, {"status": "SENT"}   # TODO:: CHECK THIS, MAKE BETTER? #######################
        except Exception as e:
            cls._log.error(f"WebSocket chat failed: {e}\n{traceback.format_exc()}")
            return 500, {"error": "Chat failed"}