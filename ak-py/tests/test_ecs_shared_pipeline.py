"""ECS on the shared queue pipeline (#870): rolling-deploy wire compatibility and handler mounting.

The SQS wire written by the old ECS classes is reproduced through ``SQSHandler``, which those classes
used and which stays: what it sends is exactly what a container from the previous release puts on
the queue.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import Request

from agentkernel.core.config import AKConfig, _ExecutionConfig
from agentkernel.core.model import BaseRunRequest
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler
from agentkernel.deployment.aws.core.websocket_service import AWSWebSocketHandler
from agentkernel.identity import IdentityProvider, IdentityProviderFactory
from agentkernel.integration.adapter.base import InboundAdapter, InboundParseResult, Source
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.integration.agui.queue_handler import AGUIPipelineRequestHandler
from agentkernel.integration.thread import ConversationThreadManager, ThreadRequestHandler
from agentkernel.pipeline.agent_runner import StreamAgentRunner
from agentkernel.pipeline.io_handler import IOHandler
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.sqs import SQSTransport, SQSTransportConsumer
from agentkernel.pipeline.ws.base import WebSocketHandlerABC

INPUT_URL = "https://sqs.test/input.fifo"
OUTPUT_URL = "https://sqs.test/output.fifo"
ENDPOINT_URL = "https://abc123.execute-api.us-east-1.amazonaws.com/prod"


def _cfg(mode, message_type):
    class _Cfg:
        execution = _ExecutionConfig(mode=mode, message_type=message_type)

    return _Cfg


def _sent_by_sqs_handler(monkeypatch, send) -> dict:
    """The boto3 ``send_message`` kwargs ``SQSHandler`` produces for one send."""
    client = MagicMock()
    monkeypatch.setattr(SQSHandler, "_sqs_client", client)
    monkeypatch.setattr(SQSHandler, "_input_queue_url", INPUT_URL)
    monkeypatch.setattr(SQSHandler, "_output_queue_url", OUTPUT_URL)
    send()
    return client.send_message.call_args.kwargs


def _as_received(sent: dict) -> dict:
    """What ``receive_message`` returns for a message sent with these kwargs."""
    return {
        "MessageId": "m1",
        "ReceiptHandle": "rh-1",
        "Body": sent["MessageBody"],
        "Attributes": {
            "MessageGroupId": sent["MessageGroupId"],
            "MessageDeduplicationId": sent["MessageDeduplicationId"],
            "ApproximateReceiveCount": "1",
        },
        "MessageAttributes": sent["MessageAttributes"],
    }


def _fetch(monkeypatch, client, record, queue_url):
    client.receive_message.return_value = {"Messages": [record]}
    monkeypatch.setattr("agentkernel.pipeline.transport.sqs.boto3.client", lambda service: client)
    [message] = SQSTransportConsumer(queue_url).fetch(1, 0.0)
    return message


class TestRollingDeploy:
    """Old and new containers share the queues during a rolling deploy, in both directions."""

    def test_old_io_to_new_runner(self, monkeypatch):
        """A WebSocket chat frame enqueued as ECSWebSocketRequestHandler does is streamed back
        chunk by chunk, each chunk carrying the return address and a FIFO dedup ID."""
        sent = _sent_by_sqs_handler(
            monkeypatch,
            lambda: SQSHandler.send_message_to_input_queue(
                message_body=BaseRunRequest(prompt="hi", session_id="s1").model_dump(),
                attributes={"message_group_id": "s1", "message_deduplication_id": "r1"},
                request_id="r1",
                user_id="u1",
                custom_message_attributes=[
                    SQSHandler.CustomAttribute(name="endpoint_url", value=ENDPOINT_URL, datatype=SQSHandler.AttributeDataType.STRING)
                ],
            ),
        )
        client = MagicMock()
        message = _fetch(monkeypatch, client, _as_received(sent), INPUT_URL)
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: _cfg("async", "delta")))
        chat_service = MagicMock()
        chat_service.process_stream_chat_sync.return_value = iter(
            [json.dumps({"delta": "he", "session_id": "s1"}), json.dumps({"done": True, "session_id": "s1"})]
        )

        StreamAgentRunner(transport=SQSTransport(input_url=INPUT_URL, output_url=OUTPUT_URL), chat_service=chat_service).process(message)

        chunks = [call.kwargs for call in client.send_message.call_args_list]
        assert [chunk["MessageDeduplicationId"] for chunk in chunks] == ["r1-1-0", "r1-1-1"]
        assert {chunk["QueueUrl"] for chunk in chunks} == {OUTPUT_URL}
        for chunk in chunks:
            assert chunk["MessageAttributes"]["endpoint_url"]["StringValue"] == ENDPOINT_URL
            assert chunk["MessageAttributes"]["user_id"]["StringValue"] == "u1"

    @staticmethod
    def _old_runner_reply(monkeypatch, status_code: int) -> dict:
        """An output record as the deleted ECSAgentRunner._send_to_output_queue wrote it."""
        return _as_received(
            _sent_by_sqs_handler(
                monkeypatch,
                lambda: SQSHandler.send_message_to_output_queue(
                    message_body={"delta": "he", "session_id": "s1"},
                    attributes={"message_group_id": "s1", "message_deduplication_id": "r1-1-0"},
                    request_id="r1",
                    user_id="u1",
                    custom_message_attributes=[
                        SQSHandler.CustomAttribute(name="status_code", value=str(status_code), datatype=SQSHandler.AttributeDataType.STRING),
                        SQSHandler.CustomAttribute(name="endpoint_url", value=ENDPOINT_URL, datatype=SQSHandler.AttributeDataType.STRING),
                    ],
                ),
            )
        )

    def test_old_runner_to_new_io_over_websocket(self, monkeypatch):
        """The reply reaches the user's connection through the API Gateway endpoint it names."""
        message = _fetch(monkeypatch, MagicMock(), self._old_runner_reply(monkeypatch, 200), OUTPUT_URL)
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: _cfg("async", "delta")))
        gateway = MagicMock()
        built_for = []
        monkeypatch.setattr(
            "agentkernel.deployment.aws.core.websocket_service.boto3.client",
            lambda service, endpoint_url: built_for.append(endpoint_url) or gateway,
        )
        store = MagicMock()
        store.get_connections.return_value = ["conn-1"]

        ResponseHandler(transport=MagicMock(), ws_handler=AWSWebSocketHandler(connection_store=store)).process(message)

        assert built_for == [ENDPOINT_URL]
        store.get_connections.assert_called_once_with("u1")
        [call] = gateway.post_to_connection.call_args_list
        assert call.kwargs["ConnectionId"] == "conn-1"
        assert json.loads(call.kwargs["Data"]) == {"delta": "he", "session_id": "s1", "type": WebSocketHandlerABC.MessageType.STREAM_CHUNK.value}

    def test_old_runner_to_new_io_over_rest(self, monkeypatch):
        """In REST mode the same record is stored with the status code it carried."""
        message = _fetch(monkeypatch, MagicMock(), self._old_runner_reply(monkeypatch, 202), OUTPUT_URL)
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: _cfg("rest_sync", "complete")))
        store = MagicMock()

        ResponseHandler(transport=MagicMock(), response_store=store).process(message)

        store.add_message.assert_called_once_with(
            {"session_id": "s1", "request_id": "r1", "status_code": 202, "body": {"delta": "he", "session_id": "s1"}}
        )


class _Provider(IdentityProvider):
    name = "test"

    async def authenticate(self, credential, context=None):  # pragma: no cover - no request is made
        raise AssertionError("not called")


class _WebhookAdapter(InboundAdapter):
    name = "byo_pkg.FakeAdapter"
    source = Source.WEBHOOK
    webhook_path = "/fake/webhook"

    async def verify(self, raw: Request) -> None:  # pragma: no cover - no request is made
        pass

    async def parse(self, raw: Request) -> InboundParseResult:  # pragma: no cover - no request is made
        return InboundParseResult(requests=[])


class TestMount:
    """Surfaces the old ECS IO container could not host now mount on it through IOHandler."""

    @pytest.fixture
    def ecs_config(self, monkeypatch):
        """The ECS SQS topology. AG-UI streams its events through the response store, so it needs a
        chunk-capable one: Redis, which the ECS Terraform module can provision."""
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("AK_SESSION__TYPE", "dynamodb")
        monkeypatch.setenv("AK_EXECUTION__MODE", "rest_sync")
        monkeypatch.setenv("AK_EXECUTION__QUEUES__TYPE", "sqs")
        monkeypatch.setenv("AK_EXECUTION__QUEUES__INPUT__URL", INPUT_URL)
        monkeypatch.setenv("AK_EXECUTION__QUEUES__OUTPUT__URL", OUTPUT_URL)
        monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__TYPE", "redis")
        monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__REDIS__URL", "redis://localhost:6379")
        AKConfig._reset()
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: _Provider()))
        monkeypatch.setattr(ConversationThreadManager, "get", classmethod(lambda cls: MagicMock()))
        yield
        AKConfig._reset()

    def test_webhook_agui_and_thread_handlers_mount(self, monkeypatch, ecs_config):
        server_config = MagicMock()
        monkeypatch.setattr("agentkernel.pipeline.io_handler.uvicorn.Config", server_config)
        monkeypatch.setattr("agentkernel.pipeline.io_handler.uvicorn.Server", MagicMock())
        monkeypatch.setattr(IOHandler, "_install_signal_handlers", classmethod(lambda cls, server: None))
        monkeypatch.setattr(ThreadRunner, "run", staticmethod(lambda tasks, max_workers=None, exit_on_shutdown=True: None))

        IOHandler.run(
            handlers=[WebhookRESTRequestHandler(_WebhookAdapter(), producer=MagicMock()), AGUIPipelineRequestHandler()],
            request_handler=ThreadRequestHandler(),
        )

        paths = set(server_config.call_args.kwargs["app"].openapi()["paths"])
        assert {"/fake/webhook", "/api/v1/chat", "/api/v1/threads", "/agui/{agent_name}"} <= paths
