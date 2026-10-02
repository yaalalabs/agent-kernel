"""Messaging-integration traffic through the serverless (Lambda) queue consumers (#760, part 1).

An integration message carries its own return address, the ``integration`` attribute plus the
``reply_*`` context, through both queues. These tests pin that the serverless agent runners keep
it, and that the serverless response handler delivers to the platform with it, in every mode.
"""

import json
import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.model import AgentReplyText, ExecutionMode
from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessAgentRunner, ServerlessStreamAgentRunner
from agentkernel.deployment.aws.serverless.akresponsehandler import ResponseHandler
from agentkernel.deployment.aws.serverless.core.router.ws_lambda import LambdaWSHandler
from agentkernel.integration.adapter.base import OutboundAdapter
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory

RUNNER_MODULE = "agentkernel.deployment.aws.serverless.akagentrunner"
HANDLER_MODULE = "agentkernel.deployment.aws.serverless.akresponsehandler"
ADAPTER_NAME = "byo_pkg.RecordingOutboundAdapter"

SLACK_REPLY_CONTEXT = {"channel": "C9", "thread_ts": "111.222", "user": "U1", "ack_ts": "333.444", "ack_channel": "C9"}
ROUTING = {"integration": "slack", **{f"reply_{key}": value for key, value in SLACK_REPLY_CONTEXT.items()}}
PREBUILT_REQUESTS = [{"type": "text", "prompt": "hi"}, {"type": "attachment_ref", "attachment_id": "att-1"}]


def _string(value: str) -> dict:
    return {"stringValue": value, "DataType": "String"}


def _input_record(routing: dict | None = None, endpoint_url: str | None = None, body: dict | None = None) -> dict:
    """A Lambda-shaped input-queue record."""
    attributes = {"request_id": "req-1", "user_id": "u1", **(routing or {})}
    if endpoint_url:
        attributes["endpoint_url"] = endpoint_url
    return {
        "body": json.dumps(body or {"prompt": "hi", "session_id": "s1", "user_id": "u1", "requests": PREBUILT_REQUESTS}),
        "attributes": {"MessageGroupId": "s1", "MessageDeduplicationId": "req-1", "ApproximateReceiveCount": "1"},
        "messageAttributes": {name: _string(value) for name, value in attributes.items()},
    }


def _config(mode):
    config = MagicMock()
    config.execution.mode = mode
    config.execution.queues.input.max_receive_count = 3
    config.execution.queues.output.max_receive_count = 3
    return config


def _sent_custom_attributes(send_mock) -> dict:
    return {attribute.name: attribute.value for attribute in send_mock.call_args.kwargs["custom_message_attributes"]}


def _chat_service(status_code=200, response=None):
    chat_service = MagicMock()
    chat_service.process_chat_request.return_value = (status_code, response or {"result": "hello from the agent", "session_id": "s1"})
    return chat_service


class TestRunner:
    def test_the_prebuilt_requests_reach_the_chat_service(self):
        chat_service = _chat_service()
        with (
            patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=chat_service),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue"),
        ):
            ServerlessAgentRunner.process_message(_input_record(ROUTING))

        requests = chat_service.process_chat_request.call_args.kwargs["requests"]
        assert [request.model_dump(exclude_none=True) for request in requests] == PREBUILT_REQUESTS

    def test_a_body_without_requests_passes_none(self):
        chat_service = _chat_service()
        with (
            patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=chat_service),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue"),
        ):
            ServerlessAgentRunner.process_message(_input_record(body={"prompt": "hi", "session_id": "s1"}))

        assert chat_service.process_chat_request.call_args.kwargs["requests"] is None

    def test_the_return_address_is_copied_onto_the_output(self):
        with (
            patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=_chat_service()),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send,
        ):
            ServerlessAgentRunner.process_message(_input_record(ROUTING))

        assert _sent_custom_attributes(send) == {"status_code": "200", **ROUTING}

    def test_a_non_integration_record_keeps_todays_output_attributes(self):
        with (
            patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=_chat_service()),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send,
        ):
            ServerlessAgentRunner.process_message(_input_record())

        assert _sent_custom_attributes(send) == {"status_code": "200"}

    def test_a_non_integration_websocket_record_keeps_its_endpoint_url(self):
        with (
            patch(f"{RUNNER_MODULE}.AKConfig.get", return_value=_config(ExecutionMode.ASYNC)),
            patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=_chat_service()),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send,
        ):
            ServerlessAgentRunner.process_message(_input_record(endpoint_url="https://ws.example/prod"))

        assert _sent_custom_attributes(send) == {"endpoint_url": "https://ws.example/prod", "status_code": "200"}

    def test_a_caller_built_record_without_routing_attributes_still_sends(self):
        record_attributes = {"message_group_id": "s1", "message_deduplication_id": "req-1", "request_id": "req-1", "user_id": "u1"}
        with patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send:
            ServerlessAgentRunner._send_to_output_queue({"result": "ok"}, record_attributes, status_code=200)

        assert _sent_custom_attributes(send) == {"status_code": "200"}

    def test_the_permanent_failure_reply_carries_the_return_address(self):
        with patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send:
            ServerlessAgentRunner.on_permanent_failure(_input_record(ROUTING))

        assert _sent_custom_attributes(send) == {"status_code": "500", **ROUTING}


class TestStreamRunner:
    def test_websocket_traffic_passes_the_prebuilt_requests(self):
        seen = {}

        def _stream(req, sse_format=False, requests=None):
            seen["requests"] = requests
            yield json.dumps({"done": True, "session_id": "s1"})

        chat_service = MagicMock()
        chat_service.process_stream_chat_sync = _stream
        with (
            patch.object(ServerlessStreamAgentRunner, "_get_chat_service", return_value=chat_service),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue"),
        ):
            ServerlessStreamAgentRunner.process_message(_input_record(endpoint_url="https://ws.example/prod"))

        assert [request.model_dump(exclude_none=True) for request in seen["requests"]] == PREBUILT_REQUESTS

    def test_an_integration_record_takes_the_non_streaming_path(self):
        stream_chat_service = MagicMock()
        runner_chat_service = _chat_service()
        with (
            patch.object(ServerlessStreamAgentRunner, "_get_chat_service", return_value=stream_chat_service),
            patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=runner_chat_service),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send,
        ):
            ServerlessStreamAgentRunner.process_message(_input_record(ROUTING))

        stream_chat_service.process_stream_chat_sync.assert_not_called()
        runner_chat_service.process_chat_request.assert_called_once()
        send.assert_called_once()
        assert _sent_custom_attributes(send) == {"status_code": "200", **ROUTING}

    def test_an_integration_permanent_failure_takes_the_non_streaming_path(self):
        with patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send:
            ServerlessStreamAgentRunner.on_permanent_failure(_input_record(ROUTING))

        send.assert_called_once()
        assert _sent_custom_attributes(send) == {"status_code": "500", **ROUTING}


class _RecordingOutboundAdapter(OutboundAdapter):
    """Records what the response handler asked it to send."""

    name = ADAPTER_NAME

    def __init__(self):
        self.delivered = []
        self.errors = []
        self.fail_with = None

    async def deliver(self, reply, reply_context):
        if self.fail_with:
            raise self.fail_with
        self.delivered.append((reply, dict(reply_context)))

    async def deliver_error(self, message, reply_context):
        if self.fail_with:
            raise self.fail_with
        self.errors.append((message, dict(reply_context)))


@pytest.fixture
def adapter():
    fake = _RecordingOutboundAdapter()
    IntegrationAdapterFactory.reset()
    IntegrationAdapterFactory._cache[ADAPTER_NAME] = fake
    yield fake
    IntegrationAdapterFactory.reset()


RECORDING_ROUTING = {**ROUTING, "integration": ADAPTER_NAME}


def _output_record(routing: dict | None = None, body=None, status_code: str | None = "200", endpoint_url: str | None = None) -> dict:
    """A Lambda-shaped output-queue record. The group id is only where SQS puts it: the system attributes."""
    attributes = {"request_id": "req-1", "user_id": "u1", **(routing or {})}
    if status_code is not None:
        attributes["status_code"] = status_code
    if endpoint_url:
        attributes["endpoint_url"] = endpoint_url
    return {
        "messageId": "m1",
        "body": json.dumps(body if body is not None else {"result": "hello from the agent", "session_id": "s1"}),
        "attributes": {"MessageGroupId": "s1", "ApproximateReceiveCount": "1"},
        "messageAttributes": {name: _string(value) for name, value in attributes.items()},
    }


@pytest.fixture
def handler_sinks():
    """Patch the mode, the response store and the WebSocket handler of the serverless response handler."""
    store = MagicMock()
    ws = MagicMock()

    def _set_mode(mode):
        ak_config = MagicMock()
        ak_config.get.return_value = _config(mode)
        return patch(f"{HANDLER_MODULE}.AKConfig", ak_config)

    with (
        patch.object(ResponseHandler, "_get_response_store", return_value=store),
        patch.object(ResponseHandler, "_get_base_ws_handler", return_value=ws),
    ):
        yield _set_mode, store, ws


ALL_MODES = [ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC, ExecutionMode.ASYNC, ExecutionMode.STREAM]


class TestResponseHandler:
    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_an_integration_reply_is_delivered_to_the_platform_in_every_mode(self, adapter, handler_sinks, mode):
        set_mode, store, ws = handler_sinks
        with set_mode(mode):
            ResponseHandler.process_message(_output_record(RECORDING_ROUTING))

        assert adapter.delivered == [(AgentReplyText(response="hello from the agent"), SLACK_REPLY_CONTEXT)]
        store.add_message.assert_not_called()
        ws.broadcast.assert_not_called()

    @pytest.mark.parametrize("status_code", ["400", "500"])
    def test_an_error_status_sends_the_generic_message(self, adapter, handler_sinks, status_code):
        set_mode, store, _ = handler_sinks
        with set_mode(ExecutionMode.REST_ASYNC):
            ResponseHandler.process_message(_output_record(RECORDING_ROUTING, body={"error": "boom"}, status_code=status_code))

        assert adapter.errors == [(_RecordingOutboundAdapter.ERROR_MESSAGE, SLACK_REPLY_CONTEXT)]
        assert adapter.delivered == []
        store.add_message.assert_not_called()

    def test_an_unparseable_status_takes_the_success_path(self, adapter, handler_sinks):
        set_mode, _, _ = handler_sinks
        with set_mode(ExecutionMode.REST_ASYNC):
            ResponseHandler.process_message(_output_record(RECORDING_ROUTING, status_code="not-a-number"))

        assert [reply.response for reply, _ in adapter.delivered] == ["hello from the agent"]
        assert adapter.errors == []

    def test_a_failed_delivery_is_retried(self, adapter, handler_sinks):
        set_mode, store, _ = handler_sinks
        adapter.fail_with = ConnectionError("slack is down")
        with set_mode(ExecutionMode.REST_ASYNC):
            result = ResponseHandler.handle({"Records": [_output_record(RECORDING_ROUTING)]}, None)

        assert result["batchItemFailures"] == [{"itemIdentifier": "m1"}]
        store.add_message.assert_not_called()


class TestPermanentFailure:
    def test_an_integration_user_gets_the_error_message(self, adapter, handler_sinks):
        set_mode, store, ws = handler_sinks
        with set_mode(ExecutionMode.REST_ASYNC):
            ResponseHandler.on_permanent_failure(_output_record(RECORDING_ROUTING))

        assert adapter.errors == [(_RecordingOutboundAdapter.ERROR_MESSAGE, SLACK_REPLY_CONTEXT)]
        store.add_message.assert_not_called()
        ws.broadcast.assert_not_called()

    def test_an_adapter_failure_is_swallowed(self, adapter, handler_sinks, caplog):
        set_mode, store, _ = handler_sinks
        adapter.fail_with = ConnectionError("slack is down")
        with set_mode(ExecutionMode.REST_ASYNC), caplog.at_level(logging.ERROR, logger="ak.aws.responsehandler"):
            ResponseHandler.on_permanent_failure(_output_record(RECORDING_ROUTING))

        # The delivery was attempted and its failure logged, not raised.
        assert "slack is down" in caplog.text
        store.add_message.assert_not_called()

    @pytest.mark.parametrize("mode", [ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC])
    def test_rest_modes_store_a_500_record_with_the_system_group_id(self, handler_sinks, mode):
        set_mode, store, _ = handler_sinks
        with set_mode(mode):
            ResponseHandler.on_permanent_failure(_output_record())

        [(stored,), _] = store.add_message.call_args
        assert stored["session_id"] == "s1"
        assert stored["request_id"] == "req-1"
        assert stored["status_code"] == 500
        assert stored["body"]["session_id"] == "s1"
        assert "Failed to process message" in stored["body"]["error"]

    def test_async_broadcasts_a_system_response(self, handler_sinks):
        set_mode, _, ws = handler_sinks
        with set_mode(ExecutionMode.ASYNC):
            ResponseHandler.on_permanent_failure(_output_record(endpoint_url="https://ws.example/prod"))

        kwargs = ws.broadcast.call_args.kwargs
        assert kwargs["message_type"] == LambdaWSHandler.MessageType.SYSTEM_RESPONSE
        assert kwargs["message"]["session_id"] == "s1"
        assert kwargs["user_id"] == "u1"

    def test_stream_broadcasts_an_error_chunk(self, handler_sinks):
        set_mode, _, ws = handler_sinks
        with set_mode(ExecutionMode.STREAM):
            ResponseHandler.on_permanent_failure(_output_record(endpoint_url="https://ws.example/prod"))

        kwargs = ws.broadcast.call_args.kwargs
        assert kwargs["message_type"] == LambdaWSHandler.MessageType.STREAM_CHUNK
        assert kwargs["message"]["session_id"] == "s1"
        assert kwargs["message"]["done"] is True
        assert "Failed to process message" in kwargs["message"]["error"]


class TestMissingExtra:
    def test_a_missing_platform_extra_is_retried_and_names_the_extra(self, handler_sinks, monkeypatch, caplog):
        set_mode, store, _ = handler_sinks
        IntegrationAdapterFactory.reset()
        monkeypatch.setitem(sys.modules, "agentkernel.integration.slack.adapter", None)

        with set_mode(ExecutionMode.REST_ASYNC), caplog.at_level(logging.INFO, logger="ak.aws.responsehandler"):
            result = ResponseHandler.handle({"Records": [_output_record(ROUTING)]}, None)

        IntegrationAdapterFactory.reset()
        assert result["batchItemFailures"] == [{"itemIdentifier": "m1"}]
        assert "agentkernel[slack]" in caplog.text
        store.add_message.assert_not_called()


IN_URL = "https://sqs.ap-southeast-2.amazonaws.com/123456789012/in.fifo"
OUT_URL = "https://sqs.ap-southeast-2.amazonaws.com/123456789012/out.fifo"


def _lambda_record(send_kwargs: dict, message_id: str = "m-rt") -> dict:
    """What a Lambda event source mapping hands a consumer, for a message boto3 was asked to send."""
    return {
        "messageId": message_id,
        "body": send_kwargs["MessageBody"],
        "attributes": {
            "MessageGroupId": send_kwargs.get("MessageGroupId"),
            "MessageDeduplicationId": send_kwargs.get("MessageDeduplicationId"),
            "ApproximateReceiveCount": "1",
        },
        "messageAttributes": {
            name: {"stringValue": value["StringValue"], "dataType": value["DataType"]}
            for name, value in (send_kwargs.get("MessageAttributes") or {}).items()
        },
    }


def _through_the_runner_and_the_response_handler(input_record: dict, agent_text: str) -> dict:
    """Run an input record through ServerlessAgentRunner and ResponseHandler; return the runner's send kwargs.

    Only the boto3 client and the queue URL are patched, so the real send_message_to_output_queue
    builds the attributes (request_id/user_id stamping and the duplicate check included).
    """
    runner_client = MagicMock()
    chat_service = _chat_service(response={"result": agent_text, "session_id": "C9:111.222"})
    with (
        patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=chat_service),
        patch(f"{RUNNER_MODULE}.SQSHandler.get_sqs_client", return_value=runner_client),
        patch(f"{RUNNER_MODULE}.SQSHandler.get_output_queue_url", return_value=OUT_URL),
    ):
        ServerlessAgentRunner.process_message(input_record)
    sent = runner_client.send_message.call_args.kwargs
    ResponseHandler.process_message(_lambda_record(sent, message_id="m-out"))
    return sent


class TestRoundTrip:
    def test_a_slack_message_keeps_its_return_address_through_both_queues(self, adapter):
        from agentkernel.core.model import AgentRequestText
        from agentkernel.integration.adapter.base import InboundRequest
        from agentkernel.integration.adapter.producer import IntegrationProducer
        from agentkernel.pipeline.transport.sqs import SQSTransport

        inbound = InboundRequest(
            session_id="C9:111.222",
            request_id="Ev1",
            requests=[AgentRequestText(prompt="hi")],
            prompt="hi",
            user_id="U1",
            reply_context=SLACK_REPLY_CONTEXT,
        )
        edge_client = MagicMock()
        with patch("boto3.client", return_value=edge_client):
            IntegrationProducer(SQSTransport(input_url=IN_URL, output_url=OUT_URL)).enqueue(ADAPTER_NAME, inbound)
        input_record = _lambda_record(edge_client.send_message.call_args.kwargs)

        sent = _through_the_runner_and_the_response_handler(input_record, "hello from the agent")

        assert len(sent["MessageAttributes"]) <= 10, "SQS allows at most 10 message attributes"
        assert adapter.delivered == [(AgentReplyText(response="hello from the agent"), SLACK_REPLY_CONTEXT)]


class _AcknowledgingOutboundAdapter(_RecordingOutboundAdapter):
    """Stands in for Slack's outbound half: the edge's "thinking..." and the final reply."""

    name = "slack"

    async def acknowledge(self, reply_context):
        return {"ack_ts": "333.444", "ack_channel": reply_context["channel"]}


class TestEndToEnd:
    SIGNING_SECRET = "test-signing-secret"

    def _signed_event(self, body: dict) -> dict:
        import hashlib
        import hmac
        import time

        payload = json.dumps(body)
        timestamp = str(int(time.time()))
        signature = "v0=" + hmac.new(self.SIGNING_SECRET.encode(), f"v0:{timestamp}:{payload}".encode(), hashlib.sha256).hexdigest()
        return {
            "httpMethod": "POST",
            "path": "/api/v1/slack/events",
            "headers": {"Content-Type": "application/json", "X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
            "body": payload,
            "isBase64Encoded": False,
        }

    def test_a_signed_slack_event_reaches_the_platform_through_lambda(self, monkeypatch):
        from slack_sdk.web.async_client import AsyncWebClient

        from agentkernel.core.config import AKConfig
        from agentkernel.deployment.aws.serverless.aklambda import Lambda
        from agentkernel.deployment.aws.serverless.core.webhook_host import LambdaWebhookHost
        from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
        from agentkernel.integration.slack.adapter import SlackInboundAdapter

        # The environment the ak-serverless module gives the request handler (queue_mode, rest_async).
        for key, value in {
            "SLACK_BOT_TOKEN": "xoxb-test-token",
            "SLACK_SIGNING_SECRET": self.SIGNING_SECRET,
            "AK_EXECUTION__MODE": "rest_async",
            "AK_EXECUTION__QUEUES__TYPE": "sqs",
            "AK_EXECUTION__QUEUES__INPUT__URL": IN_URL,
            "AK_EXECUTION__QUEUES__OUTPUT__URL": OUT_URL,
            "API_BASE_PATH": "api",
            "API_VERSION": "v1",
            "AGENT_ENDPOINT": "chat",
        }.items():
            monkeypatch.setenv(key, value)
        AKConfig._reset()

        class _AuthTestResponse(dict):
            headers = {"x-oauth-scopes": "chat:write"}

        async def _auth_test(self, **kwargs):
            return _AuthTestResponse(ok=True, bot_id="B_BOT", user_id="B_BOT", team_id="T1", url="https://test.slack.com/")

        monkeypatch.setattr(AsyncWebClient, "auth_test", _auth_test)
        slack = _AcknowledgingOutboundAdapter()
        IntegrationAdapterFactory.reset()
        IntegrationAdapterFactory._cache["slack"] = slack

        endpoints = MagicMock()
        endpoints.get_default_endpoint_info.return_value = ("default_chat_path", "POST", "GET")
        endpoints.get_routes.return_value = {"default_chat_path": {"POST": MagicMock(return_value=(200, {}))}}
        edge_client = MagicMock()
        Lambda._router, Lambda._config, LambdaWebhookHost._loop = None, None, None
        try:
            with (
                patch("agentkernel.deployment.aws.serverless.core.router.rest_lambda.DefaultEndpointsHandler", return_value=endpoints),
                patch("boto3.client", return_value=edge_client),
            ):
                # The handler builds its own producer: the SQS transport from execution.queues.
                host = LambdaWebhookHost(WebhookRESTRequestHandler(SlackInboundAdapter()))
                Lambda.register("/slack/events", method="POST")(host.handle)
                event = {"type": "message", "channel_type": "channel", "user": "U123", "text": "hello <@B_BOT>", "channel": "C9", "ts": "111.222"}
                response = Lambda.handler(self._signed_event({"type": "event_callback", "team_id": "T1", "event": event}), None)

            assert response["statusCode"] == 200
            input_record = _lambda_record(edge_client.send_message.call_args.kwargs)
            _through_the_runner_and_the_response_handler(input_record, "hello from the agent")
        finally:
            if LambdaWebhookHost._loop is not None:
                LambdaWebhookHost._loop.close()
            Lambda._router, Lambda._config, LambdaWebhookHost._loop = None, None, None
            IntegrationAdapterFactory.reset()

        [(reply, context)] = slack.delivered
        assert reply == AgentReplyText(response="hello from the agent")
        assert context["channel"] == "C9"
        assert context["ack_ts"] == "333.444"


class TestImportHygiene:
    def test_the_serverless_consumers_do_not_import_integration(self):
        saved_modules = {name: module for name, module in sys.modules.items() if name == "agentkernel" or name.startswith("agentkernel.")}
        for name in saved_modules:
            del sys.modules[name]

        try:
            import agentkernel.deployment.aws.serverless.akagentrunner  # noqa: F401
            import agentkernel.deployment.aws.serverless.akresponsehandler  # noqa: F401

            assert not [name for name in sys.modules if name.startswith("agentkernel.integration")]
        finally:
            for name in list(sys.modules):
                if name == "agentkernel" or name.startswith("agentkernel."):
                    del sys.modules[name]
            sys.modules.update(saved_modules)


@pytest.fixture(autouse=True)
def _fresh_config(monkeypatch):
    from agentkernel.core.config import AKConfig

    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    yield
    AKConfig._reset()
