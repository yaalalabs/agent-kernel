"""
Abstract Queue Request Handler

Provides the common REST request/response flow for queue-based deployments:
enqueue the request to an input queue, then either wait for a synchronous
response in a response store or return immediately for async polling.

Concrete deployments (ECS+SQS, GCP+Pub/Sub, Docker+Kafka, etc.) only need to
supply their queue handler and response store implementations by overriding
get_queue_handler() and get_response_store() — this class bypasses
ChatService entirely, so NO agent validation happens here. Agent validation
and execution occurs in the Agent Runner service.
"""

import asyncio
import logging
import uuid
from abc import abstractmethod

from fastapi import APIRouter, HTTPException

from ...api.handler import RESTRequestHandler
from ...core.config import AKConfig
from ...core.model import BaseRunRequest, ExecutionMode
from .queue_handler import QueueHandler
from .response_store import ResponseStore


class QueueRequestHandler(RESTRequestHandler):
    """
    Queue-aware REST request handler shared by all queue-based deployments.

    - POST /api/v1/chat: Enqueue request and wait for response (sync mode)
    - GET /api/v1/chat/{session_id}: Poll for response (async mode)
    """

    def __init__(self, logger_name: str = "ak.deployment.queue_handler"):
        self._log = logging.getLogger(logger_name)
        self._config = AKConfig.get()

    @abstractmethod
    def get_response_store(self) -> ResponseStore:
        """Return the ResponseStore implementation used to poll for responses."""
        pass

    @abstractmethod
    def get_queue_handler(self) -> QueueHandler:
        """Return the QueueHandler implementation used to enqueue requests."""
        pass

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

            In REST_SYNC mode: Wait for response in the Response Store.
            In REST_ASYNC mode: Return request_id immediately.
            """
            try:
                # Validate required fields
                if not body.session_id:
                    raise HTTPException(status_code=400, detail="session_id is required")
                if not body.prompt:
                    raise HTTPException(status_code=400, detail="prompt is required")

                # Generate unique request_id (different from session_id)
                request_id = str(uuid.uuid4())

                self._log.info(
                    f"[REQUEST START] session_id={body.session_id}, request_id={request_id}, agent={body.agent}, prompt={body.prompt[:50]}"
                )

                # Send to Input Queue (sync call — offload so it doesn't block the event loop)
                queue_result = await asyncio.to_thread(
                    self.get_queue_handler().send_message_to_input_queue,
                    message_body=body.model_dump(),
                    attributes={"message_group_id": body.session_id, "message_deduplication_id": request_id},
                    request_id=request_id,  # This becomes a custom message attribute
                )

                self._log.info(f"[ENQUEUED] MessageId={queue_result.get('MessageId')}, request_id={request_id}")

                # Handle based on execution mode
                if self._config.execution.mode == ExecutionMode.REST_SYNC:
                    # Wait for response in the Response Store
                    self._log.info(f"[WAITING] Polling response store for request_id={request_id}")

                    response = await self.get_response_store().get_message_with_retry(request_id, True, async_mode=True)

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

            :param session_id: Session identifier (must match the session in the response store)
            :param request_id: Optional specific request to poll for
            """
            try:
                if self._config.execution.mode != ExecutionMode.REST_ASYNC:
                    raise HTTPException(status_code=404, detail="GET endpoint only available in REST_ASYNC mode")

                if not request_id:
                    raise HTTPException(status_code=400, detail={"error": "request_id is required", "session_id": session_id})

                effective_request_id = request_id

                self._log.info(f"Polling for response: request_id={effective_request_id}, session_id={session_id}")

                response = await asyncio.to_thread(self.get_response_store().get_message, effective_request_id)

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
