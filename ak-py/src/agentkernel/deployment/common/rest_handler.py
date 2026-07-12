"""
AWS (queue-aware) REST Request Handler

Extends AgentRESTRequestHandler so it inherits the direct-ChatService routes and,
when queue mode is enabled, swaps the chat route for a queue-based enqueue/poll flow.

Direct mode (no input queue configured) — inherited from AgentRESTRequestHandler:
    - GET  /api/v1/agents           List available agents
    - POST /api/v1/chat             Run an agent via ChatService
    - POST /api/v1/chat-multipart   Run an agent with multipart file/image uploads

Queue mode (execution.queues.input.url is set):
    - GET  /api/v1/agents   List available agents (always present)
    - POST /api/v1/chat     Enqueue the request and wait (REST_SYNC) or return request_id (REST_ASYNC)
    - GET  /api/v1/chat     Poll for a response (REST_ASYNC)

In queue mode this class bypasses ChatService entirely, so NO agent validation happens
here — validation and execution occur in the Agent Runner service. Concrete deployments
(ECS+SQS, GCP+Pub/Sub, Docker+Kafka, etc.) only need to supply their queue handler and
response store implementations by overriding get_queue_handler() and get_response_store().
"""

import asyncio
import logging
import uuid
from abc import abstractmethod

from fastapi import APIRouter, HTTPException

from ...api.handler import AgentRESTRequestHandler
from ...core.config import AKConfig
from ...core.model import BaseRunRequest, ExecutionMode
from .queue_handler import QueueHandler
from .response_store import ResponseStore


class AWSRestHandler(AgentRESTRequestHandler):
    """
    Queue-aware REST request handler shared by all queue-based deployments.

    Inherits the direct-ChatService routes from AgentRESTRequestHandler and, when queue
    mode is enabled, replaces the chat route with queue-based enqueue/poll handlers:

    - POST /api/v1/chat: Enqueue request and wait for response (sync mode) / return request_id (async mode)
    - GET  /api/v1/chat: Poll for response (async mode)
    """

    # Poll route reuses the chat path (GET vs the enqueue POST).
    CHAT_POLL_PATH = AgentRESTRequestHandler.CHAT_PATH

    def __init__(self, logger_name: str = "ak.deployment.queue_handler"):
        super().__init__()
        # Override the base logger with the deployment-specific one.
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

    def _is_queue_mode(self) -> bool:
        """True when an input queue is configured (enqueue mode); False for direct mode."""
        return self._config.execution.queues.input.url is not None

    async def enqueue_and_wait(self, body: BaseRunRequest):
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
                message_group_id=body.session_id,
                message_deduplication_id=request_id,
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

    async def poll_response(self, request_id: str = None, session_id: str = None):
        """
        Poll for response (REST_ASYNC mode only).

        :param request_id: Specific request to poll for (query parameter)
        :param session_id: Optional session identifier (query parameter, used for logging/errors)
        """
        try:
            if self._config.execution.mode != ExecutionMode.REST_ASYNC:
                raise HTTPException(status_code=404, detail="GET endpoint only available in REST_ASYNC mode")

            if not request_id:
                raise HTTPException(status_code=400, detail={"error": "request_id is required", "session_id": session_id})

            self._log.info(f"Polling for response: request_id={request_id}, session_id={session_id}")

            response = await self.get_response_store().get_message_with_retry(request_id=request_id, get_and_delete=True, async_mode=True)

            if not response:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": "NOT_FOUND",
                        "message": f"No response message found for request_id '{request_id}'. The message may be unavailable. Please try again.",
                        "request_id": request_id,
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

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter.

        Direct mode (no input queue): the inherited AgentRESTRequestHandler routes
        (agents, chat, chat-multipart).

        Queue mode (input queue configured): the agents route plus queue-based chat
        endpoints that share the same paths as the base handler:
        - POST /api/v1/chat: Enqueue request and wait (sync) / return request_id (async)
        - GET  /api/v1/chat: Poll for response (async)
        """
        if not self._is_queue_mode():
            return super().get_router()

        router = APIRouter()
        router.add_api_route(self.AGENTS_PATH, self.list_agents, methods=["GET"])
        router.add_api_route(self.CHAT_PATH, self.enqueue_and_wait, methods=["POST"])
        router.add_api_route(self.CHAT_POLL_PATH, self.poll_response, methods=["GET"])
        return router
