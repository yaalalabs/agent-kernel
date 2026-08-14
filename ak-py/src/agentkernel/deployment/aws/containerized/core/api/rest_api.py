from ......api.handler import RESTRequestHandler
from ......api.http import RESTAPI
from .....common.rest_handler import RestHandler


class ECSQueueRequestHandler(RestHandler):
    """ECS + SQS + DynamoDB/Redis RestHandler; bypasses ChatService (validation/execution happen in the Agent Runner).

    Pure instantiation of the pipeline's RestHandler: the inherited ``get_transport()`` resolves
    the configured input queue URL to the SQS transport (wire format matches the pre-#495
    SQSHandler path exactly), and the inherited ``get_response_store()`` resolves the configured
    shared store. Only the ECS logger name is ECS-specific."""

    def __init__(self):
        super().__init__(logger_name="ak.ecs.queue_handler")


class AWSRestAPI(RESTAPI):
    """REST API for ECS containerized deployments; defaults to ECSQueueRequestHandler so requests are enqueued to SQS rather than run inline."""

    @classmethod
    def get_default_handlers(cls) -> list[RESTRequestHandler]:
        return [ECSQueueRequestHandler()]
