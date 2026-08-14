"""#495 public-interface cleanup: the pipeline transport (QueueTransport/QueueMessage) is the
only public queue API. The deployment-side helpers are internal: RawQueueConsumer (raw provider
records) lives under deployment/aws/core, and the chat-shaped send models are SQSHandler's own.
The pre-cleanup public names (QueueHandler, QueueConsumer, deployment.common.queue_* modules)
are intentionally removed."""

import pytest

from agentkernel.deployment.aws.containerized.core.sqs_consumer import ECSSQSConsumer
from agentkernel.deployment.aws.core.raw_queue_consumer import RawQueueConsumer
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler
from agentkernel.deployment.aws.serverless.core.sqs_consumer import LambdaSQSConsumer


class TestInternalizedContracts:
    def test_aws_consumers_share_the_raw_record_base(self):
        assert issubclass(ECSSQSConsumer, RawQueueConsumer)
        assert issubclass(LambdaSQSConsumer, RawQueueConsumer)

    def test_chat_send_models_are_owned_by_sqs_handler(self):
        body = SQSHandler.QueueMessageBody(prompt="hi", session_id="s1")
        assert body.agent is None
        attributes = SQSHandler.SendMessageAttributes(message_group_id="g1")
        assert attributes.message_deduplication_id is None

    def test_removed_public_names_are_gone(self):
        with pytest.raises(ImportError):
            from agentkernel.deployment.common import QueueConsumer  # noqa: F401
        with pytest.raises(ImportError):
            import agentkernel.deployment.common.queue_handler  # noqa: F401
        with pytest.raises(ImportError):
            import agentkernel.deployment.common.queue_consumer  # noqa: F401
