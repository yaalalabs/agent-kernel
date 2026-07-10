"""
ECS Queue-aware REST Request Handler

This handler bypasses ChatService and directly enqueues requests to SQS,
similar to how the Lambda serverless DefaultEndpointsHandler works.

Used by ECSIOHandler (Thread 1 — REST API) when queue mode is enabled.
"""

from ...common.queue_handler import QueueHandler
from ...common.queue_request_handler import QueueRequestHandler
from ..core.response_store import ResponseDBHandler
from ..core.sqs_handler import SQSHandler


class ECSQueueRequestHandler(QueueRequestHandler):
    """
    ECS + SQS + DynamoDB/Redis implementation of QueueRequestHandler.

    This bypasses ChatService entirely - NO agent validation happens here.
    Agent validation and execution occurs in the Agent Runner service.
    """

    def __init__(self):
        super().__init__(logger_name="ak.ecs.queue_handler")
        self._response_store = None
        self._queue_handler = None

    def get_response_store(self):
        """Lazy initialization of response store."""
        if self._response_store is None:
            self._response_store = ResponseDBHandler().get_store()
        return self._response_store

    def get_queue_handler(self) -> QueueHandler:
        """Lazy initialization of queue handler."""
        if self._queue_handler is None:
            self._queue_handler = SQSHandler
        return self._queue_handler
