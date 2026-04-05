from __future__ import annotations

import json
import logging
import traceback
from typing import Any, Callable, Dict, Optional

from .....core.config import AKConfig
from .....core.model import BaseRequest, ExecutionMode
from ....common.chat_service import ChatService
from ...core.response_store import ResponseDBHandler
from ...core.sqs_handler import SQSHandler


class DefaultEndpointsHandler:
    """Provides default endpoint routes depending on EXECUTION_MODE."""

    _log = logging.getLogger("ak.aws.lambda.default_endpoints")

    _default_chat_path = "default_chat_path"
    _default_chat_method = "POST"
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
            return {cls._default_chat_path: {cls._default_chat_method: cls._handle_agent_chat}}

        if exec_mode == ExecutionMode.REST_SYNC:
            cls._log.info("Initialized REST_SYNC endpoint.")
            return {cls._default_chat_path: {cls._default_chat_method: cls._handle_rest_sync}}

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
            return {cls._default_chat_path: {cls._default_chat_method: cls._handle_stream}}

        raise ValueError(f"Unsupported EXECUTION_MODE: {exec_mode}")

    @classmethod
    def _parse_body(cls, event: Dict[str, Any]) -> BaseRequest:
        """
        Parse request body from API Gateway event.
        :param event: API Gateway event
        :return: Parsed JSON payload
        """
        body = event.get("body")
        body_dict = json.loads(body) if isinstance(body, str) else (body or {})
        return BaseRequest.from_payload(body_dict)

    @classmethod
    def _build_failure_body(cls, request_id: Optional[str] = None, status: Optional[str] = None, message: Optional[str] = None) -> Dict[str, Any]:
        error_body = {"error": message or "An unexpected error occurred"}
        if status is not None:
            error_body["status"] = status
        if request_id is not None:
            error_body["request_id"] = request_id
        return error_body

    @classmethod
    def _handle_request(
        cls,
        event: Dict[str, Any],
        operation: Callable[[BaseRequest], Dict[str, Any]],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute operation with standard request parsing and error handling.
        :param event: API Gateway event
        :param operation: Function executed with parsed payload
        :param headers: Optional response headers
        :return: API Gateway formatted response
        """
        request_id = None
        try:
            request = cls._parse_body(event)
            request_id = request.request_id
            result = operation(request)
            return (200, result)  # (statusCode, body) will be handled in aklambda.py

        # Log and hide unexpected failures behind a generic 500 response.
        except Exception as e:
            cls._log.error(f"Request failed: {e}\n{traceback.format_exc()}")
            return (500, cls._build_failure_body(request_id))  # (statusCode, body) will be handled in aklambda.py

    @classmethod
    def _send_to_queue(cls, payload: BaseRequest) -> Dict[str, Any]:
        """
        Send request payload to SQS queue.
        :param payload: Request payload containing a request_id and nested run body
        :return: Queue submission status
        """
        request_body = payload.body
        if request_body is None:
            raise ValueError("body is required")
        if not payload.request_id:
            raise ValueError("request_id is required")

        session_id = request_body.session_id
        if not session_id:
            raise ValueError("session_id is required")

        message_attributes = [SQSHandler.CustomAttribute(name="request_id", value=payload.request_id, datatype=SQSHandler.AttributeDataType.STRING)]
        if payload.user_id is not None:
            message_attributes.append(SQSHandler.CustomAttribute(name="user_id", value=payload.user_id, datatype=SQSHandler.AttributeDataType.STRING))

        response = SQSHandler.send_message(
            queue_url=cls._get_input_queue_url(),
            message_body=request_body,
            message_group_id=session_id,
            message_deduplication_id=payload.request_id,
            message_attributes=message_attributes,
        )
        return response

    @classmethod
    def _get_message(cls, payload: BaseRequest) -> Dict[str, Any]:
        """
        Fetch messages from response database.
        :param payload: Request payload containing request_id
        :return: Message for request
        """
        request_id = payload.request_id
        if not request_id:
            raise ValueError("request_id is required")
        return cls._get_response_store().get_message_with_retry(request_id=request_id, get_and_delete=True)

    @classmethod
    def _handle_rest_sync(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Send request to queue and immediately fetch response.
        :param event: API Gateway event
        :param context: Lambda context
        :return: Queue status and response data
        """

        def sync_operation(payload: BaseRequest) -> Dict[str, Any]:
            request_id = payload.request_id
            cls._log.info(f"Performing REST_SYNC operation for payload: '{payload}'")
            queue_result = cls._send_to_queue(payload)
            cls._log.info(f"Message sent to input queue, response from send_message function: '{queue_result}'")

            message = cls._get_message(payload)
            cls._log.info(f"Fetched message from database: {message}")
            message = (
                message
                if message
                else cls._build_failure_body(
                    request_id=request_id,
                    status="NOT_FOUND",
                    message=f"No response message found for request_id: '{request_id}'. Try increasing the retry_count or delay in the response store configuration.",
                )
            )
            cls._log.info(f"Returning response for REST_SYNC operation: '{message}'")

            return message

        return cls._handle_request(event, sync_operation)

    @classmethod
    def _handle_async_submit(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Submit message to queue (async mode).
        :param event: API Gateway event
        :param context: Lambda context
        :return: Queue submission response
        """

        def submit_operation(payload: BaseRequest) -> Dict[str, Any]:
            cls._log.info(f"Performing REST_ASYNC submit operation for payload: '{payload}'")
            queue_result = cls._send_to_queue(payload)

            cls._log.info(f"Message sent to input queue, response from send_message function: '{queue_result}'")
            response_body = {"status": "ACCEPTED", "request_id": payload.request_id}

            cls._log.info(f"Returning response for REST_ASYNC submit operation: '{response_body}'")
            return response_body

        return cls._handle_request(event, submit_operation)

    @classmethod
    def _handle_async_poll(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Poll database for messages (async mode).
        :param event: API Gateway event
        :param context: Lambda context
        :return: Message for request
        """

        def poll_operation(payload: BaseRequest) -> Dict[str, Any]:
            cls._log.info(f"Performing REST_ASYNC poll operation for payload: '{payload}'")

            request_id = payload.request_id
            message = cls._get_message(payload)
            cls._log.info(f"Fetched message from database: {message}")
            response_body = (
                message
                if message
                else cls._build_failure_body(
                    request_id=request_id,
                    status="NOT_FOUND",
                    message=f"No response message found for request_id '{request_id}'. The message may be unavailable. Please try again.",
                )
            )

            cls._log.info(f"Returning response for REST_ASYNC poll operation: '{response_body}'")
            return response_body

        return cls._handle_request(event, poll_operation)

    @classmethod
    def _handle_agent_chat(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Process chat request directly without queue.
        :param event: API Gateway event
        :param context: Lambda context
        :return: Chat response
        """

        try:
            request = cls._parse_body(event)
            if request.body is None:
                raise ValueError("body is required")
            status_code, res_body = cls._get_chat_service().process_chat_request(request.body.model_dump(exclude_none=True))

            return {
                "statusCode": status_code,
                "body": json.dumps(res_body),
            }

        except Exception as e:
            cls._log.error(f"Chat error: {e}\n{traceback.format_exc()}")

            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Error processing request", "session_id": None}),
            }
