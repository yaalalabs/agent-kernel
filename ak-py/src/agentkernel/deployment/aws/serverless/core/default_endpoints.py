from __future__ import annotations

import json
import logging
import traceback
import uuid
from typing import Any, Callable, Dict, Optional

import boto3

from ....common.chat_service import ChatService
from ...response_store.handler import ResponseDBHandler
from .....core.model import ExecutionMode
from .....core.config import AKConfig


class DefaultEndpointsHandler:
    """Provides default endpoint routes depending on EXECUTION_MODE."""

    _log = logging.getLogger("ak.aws.lambda.default_endpoints")

    _default_chat_path = "default_chat_path"
    _default_chat_method = "POST"
    _sqs = None
    _response_store = None
    _chat_service = None

    @classmethod
    def _get_config(cls):
        return AKConfig.get()

    @classmethod
    def _get_execution_mode(cls):
        return cls._get_config().execution.mode

    @classmethod
    def _get_input_queue_url(cls):
        return cls._get_config().execution.queues.input_queue_url

    @classmethod
    def _get_default_user_polling_method(cls):
        return "GET" if cls._get_execution_mode() == ExecutionMode.REST_ASYNC else None

    @classmethod
    def _get_sqs_client(cls):
        if cls._sqs is None:
            cls._sqs = boto3.client("sqs")
        return cls._sqs

    @classmethod
    def _get_response_store(cls):
        if cls._response_store is None:
            cls._response_store = ResponseDBHandler().get_store()
        return cls._response_store

    @classmethod
    def _get_chat_service(cls):
        if cls._chat_service is None:
            cls._chat_service = ChatService()
        return cls._chat_service

    @classmethod
    def get_default_endpoint_info(cls):
        """
        Return default endpoint configuration.
        :return: Tuple of (default_chat_path, default_chat_method, default_user_polling_method)
        """
        return (
            cls._default_chat_path,
            cls._default_chat_method,
            cls._get_default_user_polling_method(),
        )

    @classmethod
    def get_routes(cls) -> Dict[str, Dict[str, Callable]]:
        """
        Return route mappings based on execution mode.
        :return: Dictionary mapping paths → HTTP methods → handler functions
        """

        input_queue_url = cls._get_input_queue_url()
        exec_mode = cls._get_execution_mode()

        if not input_queue_url:
            cls._log.warning("Queues not configured; using direct chat endpoint.")
            return {
                cls._default_chat_path: {
                    cls._default_chat_method: cls._handle_agent_chat
                }
            }

        if exec_mode == ExecutionMode.REST_SYNC:
            cls._log.info("Initialized REST_SYNC endpoint.")
            return {
                cls._default_chat_path: {
                    cls._default_chat_method: cls._handle_rest_sync
                }
            }

        if exec_mode == ExecutionMode.REST_ASYNC:
            cls._log.info("Initialized REST_ASYNC endpoints.")
            return {
                cls._default_chat_path: {
                    cls._default_chat_method: cls._handle_async_submit,
                    cls._get_default_user_polling_method(): cls._handle_async_poll,
                }
            }

        if exec_mode == ExecutionMode.STREAM:
            cls._log.info("Initialized STREAM endpoint.")
            return {
                cls._default_chat_path: {cls._default_chat_method: cls._handle_stream}
            }

        raise ValueError(f"Unsupported EXECUTION_MODE: {exec_mode}")

    @classmethod
    def _handle_request(
        cls,
        event: Dict[str, Any],
        operation: Callable[[Dict[str, Any]], Dict[str, Any]],
        error_message: str = "Missing required field",
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute operation with standard request parsing and error handling.
        :param event: API Gateway event
        :param operation: Function executed with parsed payload
        :param error_message: Error message if required field missing
        :param headers: Optional response headers
        :return: API Gateway formatted response
        """

        try:
            payload = cls._parse_body(event)
            result = operation(payload)

            response = {"statusCode": 200, "body": json.dumps(result)}

            if headers:
                response["headers"] = headers

            return response

        except KeyError as e:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"{error_message}: {str(e)}"}),
            }

        except Exception as e:
            cls._log.error(f"Request failed: {e}\n{traceback.format_exc()}")
            return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    @classmethod
    def _parse_body(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse request body from API Gateway event.
        :param event: API Gateway event
        :return: Parsed JSON payload
        """
        body = event.get("body")
        return json.loads(body) if isinstance(body, str) else (body or {})

    @classmethod
    def _send_to_queue(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send request payload to SQS queue.
        :param payload: Request payload containing session_id
        :return: Queue submission status
        """

        session_id = payload["session_id"]

        response = cls._get_sqs_client().send_message(
            QueueUrl=cls._get_input_queue_url(),
            MessageBody=json.dumps(payload),
            MessageGroupId=session_id,
            MessageDeduplicationId=str(uuid.uuid4()),
        )

        return {"status": "queued", "message_id": response.get("MessageId")}

    @classmethod
    def _get_messages(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch messages from response database.
        :param payload: Request payload containing session_id
        :return: Session response messages
        """
        session_id = payload["session_id"]
        messages = cls._get_response_store().get_messages(session_id)
        return {"session_id": session_id, "messages": messages}

    @classmethod
    def _handle_async_submit(
        cls, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """
        Submit message to queue (async mode).
        :param event: API Gateway event
        :param context: Lambda context
        :return: Queue submission response
        """
        return cls._handle_request(event, cls._send_to_queue)

    @classmethod
    def _handle_async_poll(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Poll database for messages (async mode).
        :param event: API Gateway event
        :param context: Lambda context
        :return: Messages for session
        """
        return cls._handle_request(
            event,
            cls._get_messages,
            error_message="session_id is required",
        )

    @classmethod
    def _handle_rest_sync(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Send request to queue and immediately fetch response.
        :param event: API Gateway event
        :param context: Lambda context
        :return: Queue status and response data
        """

        def sync_operation(payload: Dict[str, Any]) -> Dict[str, Any]:
            queue_result = cls._send_to_queue(payload)
            db_result = cls._get_messages(payload)
            return {"queue_status": queue_result, "response": db_result}

        return cls._handle_request(event, sync_operation)

    @classmethod
    def _handle_stream(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        # TODO:: double check this implementation with AWS docs
        """
        Handle streaming request.
        :param event: API Gateway event
        :param context: Lambda context
        :return: Streaming-style response
        """

        def stream_operation(payload: Dict[str, Any]) -> Dict[str, Any]:
            queue_result = cls._send_to_queue(payload)
            db_result = cls._get_messages(payload)
            return {"queue_status": queue_result, "response": db_result}

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        return cls._handle_request(event, stream_operation, headers=headers)

    def _handle_async_request(self):
        # you should get the message from websocket coneection
        # send it to queue
        # TODO:: Implement response fetching logic
        # return as websocket message
        pass

    @classmethod
    def _handle_agent_chat(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Process chat request directly without queue.
        :param event: API Gateway event
        :param context: Lambda context
        :return: Chat response
        """

        try:
            body = cls._parse_body(event)
            response = cls._get_chat_service().process_chat_request(body)

            response_body = {"session_id": response["session_id"]}

            if response["statusCode"] == 200:
                response_body["result"] = response.get("result")
            else:
                response_body["error"] = response.get("error")

            return {
                "statusCode": response["statusCode"],
                "body": json.dumps(response_body),
            }

        except Exception as e:
            cls._log.error(f"Chat error: {e}\n{traceback.format_exc()}")

            return {
                "statusCode": 500,
                "body": json.dumps(
                    {"error": "Error processing request", "session_id": None}
                ),
            }
