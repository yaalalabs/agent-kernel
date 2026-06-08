"""
ECS Queue-aware REST Request Handler

This handler bypasses ChatService and directly enqueues requests to SQS,
similar to how the Lambda serverless DefaultEndpointsHandler works.

Used by ECSRESTService when queue mode is enabled.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ....api.handler import RESTRequestHandler
from ....core.config import AKConfig
from ....core.model import BaseRunRequest, ExecutionMode
from ..core.response_store import ResponseDBHandler
from ..core.sqs_handler import SQSHandler


class ECSQueueRequestHandler(RESTRequestHandler):
    """
    Queue-aware REST request handler for ECS deployments.

    Handles POST /api/v1/chat by:
    1. Enqueuing the request to Input SQS Queue
    2. Waiting for response in DynamoDB Response Store (sync mode)
    3. Returning the response to the client

    This bypasses ChatService entirely - NO agent validation happens here.
    Agent validation and execution occurs in the Agent Runner service.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.ecs.queue_handler")
        self._config = AKConfig.get()
        self._response_store = None

    def _get_response_store(self):
        """Lazy initialization of response store."""
        if self._response_store is None:
            self._response_store = ResponseDBHandler().get_store()
        return self._response_store

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter for queue-based endpoints.

        - POST /api/v1/chat: Enqueue request and wait for response (sync mode)
        - GET /api/v1/chat/{session_id}: Poll for response (async mode)
        """
        router = APIRouter()

        @router.post("/api/v1/chat")
        async def enqueue_and_wait(body: BaseRunRequest):
            """
            Enqueue request to Input Queue.

            In REST_SYNC mode: Wait for response in DynamoDB Response Store.
            In REST_ASYNC mode: Return request_id immediately.
            """
            try:
                # Validate required fields
                if not body.session_id:
                    raise HTTPException(status_code=400, detail="session_id is required")
                if not body.prompt:
                    raise HTTPException(status_code=400, detail="prompt is required")

                # Generate unique request_id (different from session_id)
                import uuid

                request_id = str(uuid.uuid4())

                self._log.info(
                    f"[REQUEST START] session_id={body.session_id}, request_id={request_id}, agent={body.agent}, prompt={body.prompt[:50]}"
                )

                # Send to Input Queue
                queue_result = SQSHandler.send_message_to_input_queue(
                    message_body=body.model_dump(),
                    message_group_id=body.session_id,
                    message_deduplication_id=request_id,
                    request_id=request_id,  # This becomes a custom message attribute
                )

                self._log.info(f"[ENQUEUED] MessageId={queue_result.get('MessageId')}, request_id={request_id}")

                # Handle based on execution mode
                if self._config.execution.mode == ExecutionMode.REST_SYNC:
                    # Wait for response in DynamoDB
                    self._log.info(f"[WAITING] Polling DynamoDB for request_id={request_id}")

                    response = self._wait_for_response(request_id=request_id, session_id=body.session_id)

                    if not response:
                        raise HTTPException(
                            status_code=504,
                            detail={
                                "error": f"No response received for request_id: {request_id}",
                                "session_id": body.session_id,
                                "request_id": request_id,
                            },
                        )

                    self._log.info(f"[RESPONSE FOUND] request_id={request_id}, response_keys={list(response.keys())}")

                    # Return the response body
                    return response.get("body", response)

                elif self._config.execution.mode == ExecutionMode.REST_ASYNC:
                    # Return request_id for polling
                    return {"status": "ACCEPTED", "request_id": request_id, "session_id": body.session_id}

                else:
                    raise HTTPException(status_code=500, detail=f"Unsupported execution mode: {self._config.execution.mode}")

            except HTTPException:
                raise
            except Exception as e:
                self._log.error(f"Error processing request: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail={"error": str(e), "session_id": body.session_id if body else None})

        @router.get("/api/v1/chat/{session_id}")
        async def poll_response(session_id: str, request_id: str = None):
            """
            Poll for response (REST_ASYNC mode only).

            :param session_id: Session identifier (must match the session in DynamoDB)
            :param request_id: Optional specific request to poll for
            """
            try:
                if self._config.execution.mode != ExecutionMode.REST_ASYNC:
                    raise HTTPException(status_code=404, detail="GET endpoint only available in REST_ASYNC mode")

                effective_request_id = request_id or session_id
                if not effective_request_id:
                    raise HTTPException(status_code=400, detail={"error": "request_id is required", "session_id": session_id})

                self._log.info(f"Polling for response: request_id={effective_request_id}, session_id={session_id}")

                response = self._get_response_store().get_message(effective_request_id)

                if not response:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "error": "NOT_FOUND",
                            "message": f"No response message found for request_id '{effective_request_id}'. The message may be unavailable. Please try again.",
                            "request_id": effective_request_id,
                            "session_id": session_id,
                        },
                    )

                # SECURITY: Validate that the session_id in the response matches the URL path
                response_session_id = response.get("session_id")
                if response_session_id != session_id:
                    self._log.warning(
                        f"Session ID mismatch: URL session_id={session_id}, "
                        f"response session_id={response_session_id}, request_id={effective_request_id}"
                    )
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "error": "NOT_FOUND",
                            "message": f"No response message found for request_id '{effective_request_id}'. The message may be unavailable. Please try again.",
                            "request_id": effective_request_id,
                            "session_id": session_id,
                        },
                    )

                # Return the response body
                return response.get("body", response)

            except HTTPException:
                raise
            except Exception as e:
                self._log.error(f"Error polling response: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail={"error": str(e), "session_id": session_id})

        return router

    def _wait_for_response(self, request_id: str, session_id: str, max_retries: int = None, delay: int = None) -> Dict[str, Any]:
        """
        Wait for response to appear in DynamoDB Response Store.

        :param request_id: Request identifier to wait for
        :param session_id: Session identifier
        :param max_retries: Maximum number of retry attempts (from config if None)
        :param delay: Delay between retries in seconds (from config if None)
        :return: Response dict from DynamoDB, or None if not found
        """
        if max_retries is None:
            max_retries = self._config.execution.response_store.retry_count
        if delay is None:
            delay = self._config.execution.response_store.delay

        import time

        self._log.info(f"[WAIT START] request_id={request_id}, max_retries={max_retries}, delay={delay}s")

        for attempt in range(max_retries):
            response = self._get_response_store().get_message(request_id)
            if response:
                self._log.info(f"[WAIT SUCCESS] Found response on attempt {attempt + 1}/{max_retries} for request_id={request_id}")
                return response

            if attempt < max_retries - 1:
                self._log.debug(
                    f"[WAIT RETRY] Response not ready, waiting {delay}s (attempt {attempt + 1}/{max_retries}) for request_id={request_id}"
                )
                time.sleep(delay)

        self._log.warning(f"[WAIT TIMEOUT] Response not found after {max_retries} attempts for request_id={request_id}")
        return None
