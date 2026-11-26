"""#911: the Lambda handlers trace every request-path stage once, in order, with one request_id."""

import json
from unittest.mock import MagicMock, patch

from agentkernel.core.config import _ExecutionConfig, _ResponseStoreConfig
from agentkernel.core.logger import TRACE, TraceStage
from agentkernel.core.model import ExecutionMode, Principal
from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessAgentRunner, ServerlessStreamAgentRunner
from agentkernel.deployment.aws.serverless.akresponsehandler import ResponseHandler
from agentkernel.deployment.aws.serverless.core.router.rest_lambda import DefaultEndpointsHandler
from agentkernel.deployment.aws.serverless.core.router.ws_lambda import SystemRoutesHandler

RUNNER_MODULE = "agentkernel.deployment.aws.serverless.akagentrunner"
RESPONSE_MODULE = "agentkernel.deployment.aws.serverless.akresponsehandler"
REST_MODULE = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"
WS_MODULE = "agentkernel.deployment.aws.serverless.core.router.ws_lambda"
ENDPOINT_URL = "https://example.execute-api.us-east-1.amazonaws.com/prod"


def _attribute(value: str) -> dict:
    return {"stringValue": value, "DataType": "String"}


def _input_record() -> dict:
    return {
        "body": json.dumps({"prompt": "hi", "session_id": "s1"}),
        "attributes": {"MessageGroupId": "s1", "MessageDeduplicationId": "req-1"},
        "messageAttributes": {"request_id": _attribute("req-1"), "user_id": _attribute("u1"), "endpoint_url": _attribute(ENDPOINT_URL)},
    }


def _output_record(body: dict) -> dict:
    return {
        "body": json.dumps(body),
        "attributes": {"MessageGroupId": "s1"},
        "messageAttributes": {"request_id": _attribute("req-1"), "user_id": _attribute("u1"), "endpoint_url": _attribute(ENDPOINT_URL)},
    }


def _traces(caplog, logger: str) -> list[tuple[TraceStage, str]]:
    return [(record.args[0], record.args[1]) for record in caplog.records if record.levelno == TRACE and record.name == logger]


def _response_handler_config(mode: ExecutionMode, message_type: str | None = None) -> MagicMock:
    config = MagicMock()
    config.execution = _ExecutionConfig(mode=mode, message_type=message_type)
    return config


def test_complete_rest_sync(caplog):
    config = MagicMock()
    config.execution = _ExecutionConfig(mode=ExecutionMode.REST_SYNC, response_store=_ResponseStoreConfig(type="dynamodb"))
    store = MagicMock()
    store.get_record_with_retry.return_value = {"session_id": "s1", "request_id": "req-1", "status_code": 200, "body": {"result": "ok"}}
    chat_service = MagicMock()
    chat_service.process_chat_request.return_value = (200, {"result": "ok", "session_id": "s1"})
    sent_after = []  # the runner's stages already traced when it sends the reply

    with (
        caplog.at_level(TRACE, logger="ak"),
        patch(f"{REST_MODULE}.AKConfig.get", return_value=config),
        patch(f"{REST_MODULE}.ResponseStoreFactory.create", return_value=store),
        patch(f"{REST_MODULE}.ChatService"),
        patch(f"{REST_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}),
        patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=chat_service),
        patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send_output,
        patch.object(ResponseHandler, "_get_response_store", return_value=MagicMock()),
    ):
        send_output.side_effect = lambda **kwargs: sent_after.extend(stage for stage, _ in _traces(caplog, "ak.aws.agentrunner"))
        # The edge polls the store the runner and Response Handler fill; called in order here.
        ServerlessAgentRunner.process_message(_input_record())
        ResponseHandler.process_message(_output_record({"result": "ok", "session_id": "s1"}))
        assert (
            DefaultEndpointsHandler()._handle_rest_sync({"body": json.dumps({"request_id": "req-1", "prompt": "hi", "session_id": "s1"})}, None)[0]
            == 200
        )

    assert _traces(caplog, "ak.aws.lambda.default_endpoints") == [
        (TraceStage.REQUEST_HANDLER_START, "req-1"),
        (TraceStage.INPUT_ENQUEUED, "req-1"),
        (TraceStage.RESPONSE_POLL_START, "req-1"),
        (TraceStage.RESPONSE_FOUND, "req-1"),
    ]
    assert _traces(caplog, "ak.aws.agentrunner") == [
        (TraceStage.AGENT_RECEIVED, "req-1"),
        (TraceStage.AGENT_START, "req-1"),
        (TraceStage.AGENT_DONE, "req-1"),
        (TraceStage.OUTPUT_ENQUEUED, "req-1"),
    ]
    assert sent_after[-1] == TraceStage.OUTPUT_ENQUEUED  # traced before the send, not after
    assert _traces(caplog, "ak.aws.responsehandler") == [(TraceStage.OUTPUT_RECEIVED, "req-1"), (TraceStage.RESPONSE_DELIVERED, "req-1")]


def test_delta_websocket(caplog):
    with (
        patch(f"{WS_MODULE}.AKConfig") as ws_config_cls,
        patch(f"{WS_MODULE}.WebSocketConnectionStore"),
        patch(f"{WS_MODULE}.ChatService"),
    ):
        ws_config = MagicMock()
        ws_config.execution = _ExecutionConfig(mode=ExecutionMode.ASYNC, message_type="delta")
        ws_config_cls.get.return_value = ws_config
        ws_handler = SystemRoutesHandler()
    ws_handler.get_principal = MagicMock(return_value=Principal(subject="u1", provider="static", namespace="static"))
    ws_event = {
        "requestContext": {"connectionId": "conn-1", "domainName": "example.execute-api.us-east-1.amazonaws.com", "stage": "prod"},
        "body": json.dumps({"request_id": "req-1", "body": {"prompt": "hi", "session_id": "s1"}}),
    }

    def _stream(req, requests=None):
        yield json.dumps({"delta": "Hello", "done": False, "session_id": "s1"})
        yield json.dumps({"done": True, "session_id": "s1"})

    chat_service = MagicMock()
    chat_service.process_stream_chat_sync = _stream

    with (
        caplog.at_level(TRACE, logger="ak"),
        patch(f"{WS_MODULE}.SQSHandler.send_message_to_input_queue", return_value={"MessageId": "m1"}),
        patch.object(ServerlessStreamAgentRunner, "_get_chat_service", return_value=chat_service),
        patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue"),
        patch(f"{RESPONSE_MODULE}.AKConfig.get", return_value=_response_handler_config(ExecutionMode.ASYNC, "delta")),
        patch.object(ResponseHandler, "_get_base_ws_handler", return_value=MagicMock()),
    ):
        assert ws_handler._handle_queue_mode(ws_event)[0] == 200
        ServerlessStreamAgentRunner.process_message(_input_record())
        ResponseHandler.process_message(_output_record({"delta": "Hello", "done": False, "session_id": "s1"}))
        ResponseHandler.process_message(_output_record({"done": True, "session_id": "s1"}))

    assert _traces(caplog, "ak.pipeline.ws.handler") == [(TraceStage.REQUEST_HANDLER_START, "req-1"), (TraceStage.INPUT_ENQUEUED, "req-1")]
    assert _traces(caplog, "ak.aws.streamagentrunner") == [
        (TraceStage.AGENT_RECEIVED, "req-1"),
        (TraceStage.AGENT_START, "req-1"),
        (TraceStage.AGENT_FIRST_CHUNK, "req-1"),
        (TraceStage.AGENT_DONE, "req-1"),
        (TraceStage.OUTPUT_ENQUEUED, "req-1"),
    ]
    # One output message per chunk, each traced (#911 Q1).
    assert _traces(caplog, "ak.aws.responsehandler") == [(TraceStage.OUTPUT_RECEIVED, "req-1"), (TraceStage.RESPONSE_DELIVERED, "req-1")] * 2
