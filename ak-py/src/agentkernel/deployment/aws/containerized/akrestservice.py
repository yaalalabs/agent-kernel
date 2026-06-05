from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict

from ....api.http import RESTAPI
from ....core.config import AKConfig
from ....core.model import ExecutionMode
from ..core.response_store import ResponseDBHandler
from ..core.sqs_handler import SQSHandler
from ..core.websocket_service import WebSocketHandler
from .sqs_poller import SQSPoller


class ECSRESTService:
    """
    ECS REST Service — handles all queue-based execution modes:

    - **REST Sync** (``execution.mode = rest_sync``)
      Thread 2 writes output messages to the DynamoDB Response Store.
      Thread 1 (FastAPI) waits on the same store and returns the response
      on the original HTTP connection.

    - **REST Async** (``execution.mode = rest_async``)
      Same as REST Sync for the output-queue side.  Thread 1 exposes a
      separate ``GET`` endpoint that the client polls.

    - **WebSocket / Async** (``execution.mode = async``)
      Thread 2 pushes output messages directly to the client over the
      still-open WebSocket connection via API Gateway Management API
      (PostToConnection).  No DynamoDB response store is used.

    Runs two threads:

    - **Thread 1** — FastAPI/uvicorn (via ``RESTAPI.run``).
    - **Thread 2** — ``SQSPoller`` daemon on the Output Queue.

    Can be used standalone — just set ``execution.mode`` in ``config.yaml``
    (or via env vars) and call ``ECSRESTService.run()``.

    Usage::

        from agentkernel.deployment.aws.containerized import ECSRESTService

        if __name__ == "__main__":
            ECSRESTService.run()
    """

    _log = logging.getLogger("ak.ecs.restservice")
    _config = AKConfig.get()

    # lazily initialised, shared across Thread 2 calls
    _response_store = None
    _websocket_handler = None

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    @classmethod
    def run(cls) -> None:
        """
        Start the output-queue poller (Thread 2) as a daemon, then start
        the REST API (Thread 1) in the main thread.  Blocks until the
        REST API exits.
        """
        output_queue_url = cls._config.execution.queues.output.url
        max_receive_count = cls._config.execution.queues.output.max_receive_count

        if not output_queue_url:
            raise ValueError(
                "AK_EXECUTION__QUEUES__OUTPUT__URL is required for ECSRESTService"
            )

        mode = cls._config.execution.mode
        cls._log.info(
            f"ECSRESTService starting — mode={mode} output_queue={output_queue_url}"
        )

        poller = SQSPoller(
            queue_url=output_queue_url,
            process_fn=cls.process_output_message,
            max_receive_count=max_receive_count,
            on_permanent_failure_fn=cls.on_permanent_failure,
        )
        t2 = threading.Thread(
            target=poller.run, name="output-queue-poller", daemon=True
        )
        t2.start()
        cls._log.info("ECSRESTService: Thread 2 (output-queue poller) started")

        # Use queue-aware request handler that bypasses ChatService
        # This directly enqueues to SQS without agent validation
        from .ecs_queue_handler import ECSQueueRequestHandler
        
        cls._log.info("ECSRESTService: starting REST API with queue-aware handler (Thread 1)")
        RESTAPI.run(handlers=[ECSQueueRequestHandler()])

    # ------------------------------------------------------------------
    # Lazy initialisers
    # ------------------------------------------------------------------

    @classmethod
    def _get_response_store(cls):
        if cls._response_store is None:
            cls._response_store = ResponseDBHandler().get_store()
        return cls._response_store

    @classmethod
    def _get_websocket_handler(cls) -> WebSocketHandler:
        if cls._websocket_handler is None:
            ws_config = cls._config.websocket_api
            if not ws_config.connection_table or not ws_config.connection_table.table_name:
                raise ValueError(
                    "websocket_api.connection_table.table_name is required "
                    "for ECSRESTService in WebSocket mode"
                )
            cls._websocket_handler = WebSocketHandler(
                conn_table_name=ws_config.connection_table.table_name,
                ttl=ws_config.connection_table.ttl,
            )
        return cls._websocket_handler

    # ------------------------------------------------------------------
    # Output-queue message handlers (Thread 2)
    # These are public so callers can also invoke them directly if needed.
    # ------------------------------------------------------------------

    @classmethod
    def process_output_message(cls, record: Dict[str, Any]) -> None:
        """
        Process one message from the Output Queue.

        Dispatches based on ``execution.mode``:

        - ``async``                  → push via WebSocket (PostToConnection)
        - ``rest_sync`` / ``rest_async`` → write to DynamoDB Response Store

        :param record: boto3 SQS ``receive_message`` record
        """
        cls._log.info(f"Processing output message {record.get('MessageId')}")

        if cls._config.execution.mode == ExecutionMode.ASYNC:
            cls._broadcast_via_websocket(record)
        else:
            message = cls._construct_message_for_store(record)
            cls._get_response_store().add_message(message)
            cls._log.info(
                f"Stored response — session_id={message['session_id']} "
                f"request_id={message['request_id']}"
            )

    @classmethod
    def on_permanent_failure(cls, record: Dict[str, Any]) -> None:
        """
        Handle an output message that exceeded ``max_receive_count``.

        - ``async`` mode → broadcast error via WebSocket
        - Other modes    → write error entry to Response Store so the
                           waiting HTTP caller gets a response instead of
                           hanging indefinitely

        :param record: boto3 SQS ``receive_message`` record
        """
        max_retries = cls._config.execution.queues.output.max_receive_count
        cls._log.error(
            f"Permanent failure for output message {record.get('MessageId')} "
            f"after {max_retries} retries"
        )

        try:
            message_attributes = SQSHandler.get_message_custom_attributes(record)
            request_id = message_attributes.get("request_id")
            error_payload = {
                "error": f"Failed to process message after {max_retries} retries",
                "request_id": request_id,
            }

            if cls._config.execution.mode == ExecutionMode.ASYNC:
                endpoint_url = message_attributes.get("endpoint_url")
                user_id = message_attributes.get("user_id")
                if endpoint_url and user_id:
                    cls._get_websocket_handler().broadcast(
                        endpoint_url=endpoint_url,
                        message=error_payload,
                        user_id=user_id,
                    )
                else:
                    cls._log.warning(
                        "Cannot broadcast permanent-failure error: "
                        "endpoint_url or user_id missing"
                    )
            else:
                error_body = json.dumps(error_payload)
                message = cls._construct_message_for_store(record, body=error_body)
                cls._get_response_store().add_message(message)
                cls._log.info(
                    f"Stored permanent-failure error — "
                    f"session_id={message['session_id']} "
                    f"request_id={message['request_id']}"
                )
        except Exception:
            cls._log.exception(
                "Failed to handle permanent-failure output message"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _construct_message_for_store(
        cls, record: Dict[str, Any], body: Any = None
    ) -> Dict[str, Any]:
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
    def _broadcast_via_websocket(cls, record: Dict[str, Any]) -> None:
        """
        Push an output message to the client over WebSocket.

        :param record: boto3 SQS record
        :raises ValueError: If endpoint_url or user_id is missing.
        """
        message_attributes = SQSHandler.get_message_custom_attributes(record)
        endpoint_url = message_attributes.get("endpoint_url")
        user_id = message_attributes.get("user_id")

        if not endpoint_url:
            raise ValueError(
                "endpoint_url is required in SQS message attributes for ASYNC mode"
            )
        if not user_id:
            raise ValueError(
                "user_id is required in SQS message attributes for ASYNC mode"
            )

        message_body = record.get("Body", "{}")
        if isinstance(message_body, str):
            message_body = json.loads(message_body)

        cls._log.info(
            f"Broadcasting via WebSocket — user_id={user_id} endpoint={endpoint_url}"
        )
        cls._get_websocket_handler().broadcast(
            endpoint_url=endpoint_url, message=message_body, user_id=user_id
        )
