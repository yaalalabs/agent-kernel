"""The legacy queue-mode contracts renamed in #495: ChatQueueHandler (send side, chat-shaped
bodies) and RawQueueConsumer (receive side, provider-native records), with the pre-rename names
kept as aliases so existing imports and subclasses keep working."""

from agentkernel.deployment.aws.containerized.core.sqs_consumer import ECSSQSConsumer
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler
from agentkernel.deployment.aws.serverless.core.sqs_consumer import LambdaSQSConsumer
from agentkernel.deployment.common import ChatQueueHandler, QueueConsumer, QueueHandler, RawQueueConsumer


class TestRenamedContracts:
    def test_old_names_alias_the_new_classes(self):
        assert QueueHandler is ChatQueueHandler
        assert QueueConsumer is RawQueueConsumer

    def test_old_module_paths_still_resolve_the_same_objects(self):
        from agentkernel.deployment.common.queue_consumer import QueueConsumer as by_module_consumer
        from agentkernel.deployment.common.queue_handler import QueueHandler as by_module_handler

        assert by_module_handler is ChatQueueHandler
        assert by_module_consumer is RawQueueConsumer

    def test_implementations_subclass_the_renamed_contracts(self):
        assert issubclass(SQSHandler, ChatQueueHandler)
        assert issubclass(ECSSQSConsumer, RawQueueConsumer)
        assert issubclass(LambdaSQSConsumer, RawQueueConsumer)
