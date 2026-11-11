from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request

from ......core.config import AKConfig
from ......core.model import BaseRequest
from ......core.multimodal.storage import AttachmentStorageManager
from ......core.util.factory import AKConfigError
from ......integration.thread.thread_chat import ThreadRequestHandler
from ...aklambda import Lambda
from ..router.rest_lambda import LambdaChatRejection
from .base import LambdaHost, LambdaHostGuard
from .event_translator import LambdaEventTranslator


class LambdaThreadHost(LambdaHost):
    """Serves Conversation Thread Support on the request-handler Lambda (#879).

    Build it at module scope and register the read routes with ``Lambda.register``::

        threads = LambdaThreadHost(ThreadRequestHandler())

        @Lambda.register("/threads", method="GET")
        def list_threads(event, context):
            return threads.list_threads(event, context)

        @Lambda.register("/threads/{session_id}", method="GET")
        def get_thread(event, context):
            return threads.get_thread(event, context)

    The chat route stays the router's: the host hooks its enqueue step, where
    ``ThreadRequestHandler.prepare_for_queue`` records the user message and marks the message,
    and ``ServerlessAgentRunner`` records the reply. Creating the host is what enables threads.

    This module imports FastAPI and Starlette at module scope, so ``agentkernel.aws`` exports it
    lazily: ``from agentkernel.aws import Lambda`` stays fastapi-free.
    """

    def __init__(self, handler: ThreadRequestHandler, translator: LambdaEventTranslator | None = None):
        """Check the deployment, then take over the chat route's enqueue step.

        :param handler: The pipeline thread handler whose edge work and read routes to host.
        :param translator: The event <-> Starlette translator; a default one when omitted.
        :raises TypeError: The handler is not a ThreadRequestHandler.
        :raises AKConfigError: See LambdaThreadGuard; also non-queue or WebSocket mode, from
            ``Lambda.set_chat_enqueue_hook``.
        :raises ValueError: A chat enqueue hook is already set.
        """
        self._handler = LambdaThreadGuard().check(handler)
        super().__init__(translator)
        Lambda.set_chat_enqueue_hook(self._before_enqueue)

    def list_threads(self, event: dict[str, Any], context: Any) -> dict[str, Any]:
        """GET /threads (the router's ``(event, context)`` contract).

        :param event: The API Gateway REST (v1) proxy event.
        :param context: The Lambda context; unused.
        :return: The proxy response, FastAPI-shaped.
        """
        principal = self._principal(event)

        async def endpoint(request: Request) -> dict:
            q = request.query_params
            return self._handler.read_handler.list_threads(
                lambda: principal, user_id=q.get("user_id"), group_id=q.get("group_id"), limit=self._limit(q.get("limit")), cursor=q.get("cursor")
            )

        return self._run(self._respond(endpoint, event))

    def get_thread(self, event: dict[str, Any], context: Any) -> dict[str, Any]:
        """GET /threads/{session_id} (the router's ``(event, context)`` contract).

        :param event: The API Gateway REST (v1) proxy event; ``pathParameters.session_id`` names the thread.
        :param context: The Lambda context; unused.
        :return: The proxy response, FastAPI-shaped.
        """
        principal = self._principal(event)
        session_id = (event.get("pathParameters") or {}).get("session_id")

        async def endpoint(request: Request) -> dict:
            q = request.query_params
            return self._handler.read_handler.get_thread(lambda: principal, session_id, limit=self._limit(q.get("limit")), cursor=q.get("cursor"))

        return self._run(self._respond(endpoint, event))

    def _before_enqueue(self, payload: BaseRequest) -> dict[str, str]:
        """The chat route's enqueue hook: record the user message and return the thread marker.

        :param payload: The parsed chat envelope; its body is rewritten in place for the queue.
        :return: The extra SQS message attributes.
        :raises LambdaChatRejection: A 400 the pipeline route would answer, before any thread write.
        """
        try:
            return self._run(self._handler.prepare_for_queue(payload.body))
        except HTTPException as e:
            raise LambdaChatRejection(e.status_code, e.detail)

    @staticmethod
    def _principal(event: Mapping[str, Any]) -> str | None:
        """The user the API Gateway authorizer approved, or None when no authorizer ran."""
        authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
        return authorizer.get("principalId") or None

    @staticmethod
    def _limit(value: str | None) -> int | None:
        """Parse the ``limit`` query parameter; 400 where FastAPI would answer 422."""
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"limit must be an integer; got {value!r}")


class LambdaThreadGuard(LambdaHostGuard):
    """The cold-start checks LambdaThreadHost runs (#879): fail at import, not on the first chat."""

    HOST_NAME = "LambdaThreadHost"
    SUBJECT = "threads"
    COMPLETE_ONLY_REASON = "The serverless agent runner records the reply of a whole message only"

    def check(self, handler: Any) -> ThreadRequestHandler:
        """Run every check, in this order; return the handler, typed.

        :param handler: What the application passed to ``LambdaThreadHost``.
        :return: The same handler.
        :raises TypeError: The handler is not a ThreadRequestHandler.
        :raises AKConfigError: Mode, transport, base-path environment, an Authoriser, an
            unshared attachment store, or an unshared thread store.
        """
        if not isinstance(handler, ThreadRequestHandler):
            raise TypeError(f"LambdaThreadHost serves ThreadRequestHandler only; got {type(handler).__name__}")
        self._check_deployment(handler)
        if handler.read_handler.authoriser is not None:
            raise AKConfigError("Lambda authorizes at the API Gateway authorizer; build ThreadRequestHandler() without an Authoriser")
        if AKConfig.get().multimodal.enabled and not AttachmentStorageManager.store_is_shared():
            raise AKConfigError(
                f"multimodal.storage_type '{AKConfig.get().multimodal.storage_type}' keeps attachments in the process "
                "that wrote them, but the agent runs in the agent-runner Lambda: an attachment offloaded at the edge "
                "would be unresolvable there. Use redis or dynamodb"
            )
        if AKConfig.get().thread.type.lower() == "in_memory":
            raise AKConfigError(
                "thread.type 'in_memory' keeps threads in the process that wrote them, but the request-handler Lambda "
                "records the user message and serves the read routes while the agent-runner Lambda records the reply: "
                "each would see its own copy. Use redis, valkey, dynamodb, cosmosdb or firestore"
            )
        return handler
