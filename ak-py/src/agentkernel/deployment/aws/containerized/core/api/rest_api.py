from ......api.handler import RESTRequestHandler
from ......api.http import RESTAPI
from .....common.rest_handler import RestHandler
from ....core.response_store import ResponseDBHandler


class ECSQueueRequestHandler(RestHandler):
    """ECS + SQS + DynamoDB/Redis RestHandler; bypasses ChatService (validation/execution happen in the Agent Runner).

    Enqueues through the inherited ``get_transport()``: the configured input queue URL resolves
    to the SQS transport, so the wire format matches the pre-#495 SQSHandler path exactly."""

    def __init__(self):
        super().__init__(logger_name="ak.ecs.queue_handler")
        self._response_store = None

    def get_response_store(self):
        """Lazily create the response store."""
        if self._response_store is None:
            self._response_store = ResponseDBHandler().get_store()
        return self._response_store


class AWSRestAPI(RESTAPI):
    """REST API for ECS containerized deployments; defaults to ECSQueueRequestHandler so requests are enqueued to SQS rather than run inline."""

    @classmethod
    def get_default_handlers(cls) -> list[RESTRequestHandler]:
        return [ECSQueueRequestHandler()]
