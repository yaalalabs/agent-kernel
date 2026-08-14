from ......api.handler import RESTRequestHandler
from ......api.http import RESTAPI
from .....common.queue_handler import ChatQueueHandler
from .....common.rest_handler import RestHandler
from ....core.response_store import ResponseDBHandler
from ....core.sqs_handler import SQSHandler


class ECSQueueRequestHandler(RestHandler):
    """ECS + SQS + DynamoDB/Redis RestHandler; bypasses ChatService (validation/execution happen in the Agent Runner)."""

    def __init__(self):
        super().__init__(logger_name="ak.ecs.queue_handler")
        self._response_store = None
        self._queue_handler = None

    def get_response_store(self):
        """Lazily create the response store."""
        if self._response_store is None:
            self._response_store = ResponseDBHandler().get_store()
        return self._response_store

    def get_queue_handler(self) -> ChatQueueHandler:
        """Lazily resolve the queue handler."""
        if self._queue_handler is None:
            self._queue_handler = SQSHandler
        return self._queue_handler


class AWSRestAPI(RESTAPI):
    """REST API for ECS containerized deployments; defaults to ECSQueueRequestHandler so requests are enqueued to SQS rather than run inline."""

    @classmethod
    def get_default_handlers(cls) -> list[RESTRequestHandler]:
        return [ECSQueueRequestHandler()]
