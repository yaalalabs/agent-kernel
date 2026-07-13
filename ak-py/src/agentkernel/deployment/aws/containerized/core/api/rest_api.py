"""
ECS Queue-aware REST Request Handler and REST API.

Used by ECSIOHandler (Thread 1 — REST API) when queue mode is enabled.
"""

from ......api.handler import RESTRequestHandler
from ......api.http import RESTAPI
from .....common.queue_handler import QueueHandler
from .....common.rest_handler import RestHandler
from ....core.response_store import ResponseDBHandler
from ....core.sqs_handler import SQSHandler


class ECSQueueRequestHandler(RestHandler):
    """
    ECS + SQS + DynamoDB/Redis implementation of RestHandler.

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


class AWSRestAPI(RESTAPI):
    """
    REST API for ECS containerized deployments.

    Defaults to the queue-aware ECSQueueRequestHandler instead of RESTAPI's plain
    AgentRESTRequestHandler, so requests are enqueued to SQS rather than run inline.

    Usage::

        from agentkernel.aws import AWSRestAPI

        AWSRestAPI.run()
    """

    @classmethod
    def get_default_handlers(cls) -> list[RESTRequestHandler]:
        return [ECSQueueRequestHandler()]
