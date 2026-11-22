"""#911: the ECS handlers trace every request-path stage once, in order, with one request_id."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.core.config import _ExecutionConfig
from agentkernel.core.logger import TRACE, TraceStage
from agentkernel.core.model import BaseRequest, ExecutionMode, Principal
from agentkernel.deployment.aws.containerized.akagentrunner import ECSAgentRunner, ECSStreamAgentRunner
from agentkernel.deployment.aws.containerized.akoutputconsumer import ECSOutputConsumer
from agentkernel.deployment.aws.containerized.core.api.websocket_api import ECSWebSocketRequestHandler

WS_MODULE = "agentkernel.deployment.aws.containerized.core.api.websocket_api"
RUNNER_MODULE = "agentkernel.deployment.aws.containerized.akagentrunner"
ENDPOINT_URL = "https://example.execute-api.us-east-1.amazonaws.com/prod"


def _record(body: dict) -> dict:
    return {
        "MessageId": "m1",
        "Body": json.dumps(body),
        "Attributes": {"MessageGroupId": "s1", "MessageDeduplicationId": "req-1"},
        "MessageAttributes": {
            "request_id": {"StringValue": "req-1", "DataType": "String"},
            "user_id": {"StringValue": "u1", "DataType": "String"},
            "endpoint_url": {"StringValue": ENDPOINT_URL, "DataType": "String"},
        },
    }


def _traces(caplog, logger: str) -> list[tuple[TraceStage, str]]:
    return [(record.args[0], record.args[1]) for record in caplog.records if record.levelno == TRACE and record.name == logger]


async def _enqueue_ws_chat(monkeypatch, message_type: str | None) -> None:
    config = SimpleNamespace(
        websocket_api=SimpleNamespace(endpoint_url=ENDPOINT_URL, connection_table=SimpleNamespace(table_name="t", ttl=3600)),
        execution=_ExecutionConfig(mode=ExecutionMode.ASYNC, message_type=message_type),
        identity=None,
        registry=None,
    )
    config.execution.queues.input.url = "https://sqs.test/input"
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: config))
    handler = ECSWebSocketRequestHandler()
    handler.build_route_context = AsyncMock(
        return_value=handler.WSRouteContext(
            message=BaseRequest.from_payload({"request_id": "req-1", "body": {"session_id": "s1", "prompt": "hi"}}),
            principal=Principal(subject="u1", provider="static", namespace="static"),
            connection_id="c1",
            endpoint_url=ENDPOINT_URL,
        )
    )
    with patch(f"{WS_MODULE}.SQSHandler"):
        assert (await handler._handle_chat(request=MagicMock())).status_code == 200


@pytest.fixture(autouse=True)
def _reset_websocket_handler():
    ECSOutputConsumer._websocket_handler = None
    yield
    ECSOutputConsumer._websocket_handler = None


@pytest.mark.asyncio
async def test_complete_websocket(caplog, monkeypatch):
    chat_service = MagicMock()
    chat_service.process_chat_request.return_value = (200, {"result": "ok", "session_id": "s1"})
    monkeypatch.setattr(ECSOutputConsumer._config.execution, "mode", ExecutionMode.ASYNC)
    monkeypatch.setattr(ECSOutputConsumer._config.execution, "message_type", None)

    with (
        caplog.at_level(TRACE, logger="ak"),
        patch.object(ECSAgentRunner, "_get_chat_service", return_value=chat_service),
        patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue"),
        patch(f"{RUNNER_MODULE}.SQSHandler.get_output_queue_url", return_value="q"),
        patch.object(ECSOutputConsumer, "_get_websocket_handler", return_value=MagicMock()),
    ):
        await _enqueue_ws_chat(monkeypatch, message_type=None)
        ECSAgentRunner.process_message(_record({"prompt": "hi", "session_id": "s1"}))
        ECSOutputConsumer.process_message(_record({"result": "ok", "session_id": "s1"}))

    assert _traces(caplog, "ak.ecs.ws_handler") == [(TraceStage.REQUEST_RECEIVED, "req-1"), (TraceStage.INPUT_ENQUEUED, "req-1")]
    assert _traces(caplog, "ak.ecs.agentrunner") == [
        (TraceStage.AGENT_RECEIVED, "req-1"),
        (TraceStage.AGENT_START, "req-1"),
        (TraceStage.AGENT_DONE, "req-1"),
        (TraceStage.OUTPUT_ENQUEUED, "req-1"),
    ]
    assert _traces(caplog, "ak.ecs.outputconsumer") == [(TraceStage.OUTPUT_RECEIVED, "req-1"), (TraceStage.RESPONSE_DELIVERED, "req-1")]


def test_complete_response_store(caplog, monkeypatch):
    monkeypatch.setattr(ECSOutputConsumer._config.execution, "mode", ExecutionMode.REST_SYNC)
    with caplog.at_level(TRACE, logger="ak"), patch.object(ECSOutputConsumer, "_get_response_store", return_value=MagicMock()):
        ECSOutputConsumer.process_message(_record({"result": "ok", "session_id": "s1"}))

    assert _traces(caplog, "ak.ecs.outputconsumer") == [(TraceStage.OUTPUT_RECEIVED, "req-1"), (TraceStage.RESPONSE_DELIVERED, "req-1")]


@pytest.mark.asyncio
async def test_delta_websocket(caplog, monkeypatch):
    def _stream(req):
        yield json.dumps({"delta": "Hello", "done": False, "session_id": "s1"})
        yield json.dumps({"done": True, "session_id": "s1"})

    chat_service = MagicMock()
    chat_service.process_stream_chat_sync = _stream
    monkeypatch.setattr(ECSOutputConsumer._config.execution, "mode", ExecutionMode.ASYNC)
    monkeypatch.setattr(ECSOutputConsumer._config.execution, "message_type", "delta")

    with (
        caplog.at_level(TRACE, logger="ak"),
        patch.object(ECSStreamAgentRunner, "_get_chat_service", return_value=chat_service),
        patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue"),
        patch(f"{RUNNER_MODULE}.SQSHandler.get_output_queue_url", return_value="q"),
        patch.object(ECSOutputConsumer, "_get_websocket_handler", return_value=MagicMock()),
    ):
        await _enqueue_ws_chat(monkeypatch, message_type="delta")
        ECSStreamAgentRunner.process_message(_record({"prompt": "hi", "session_id": "s1"}))
        ECSOutputConsumer.process_message(_record({"delta": "Hello", "done": False, "session_id": "s1"}))
        ECSOutputConsumer.process_message(_record({"done": True, "session_id": "s1"}))

    assert _traces(caplog, "ak.ecs.ws_handler") == [(TraceStage.REQUEST_RECEIVED, "req-1"), (TraceStage.INPUT_ENQUEUED, "req-1")]
    assert _traces(caplog, "ak.ecs.streamagentrunner") == [
        (TraceStage.AGENT_RECEIVED, "req-1"),
        (TraceStage.AGENT_START, "req-1"),
        (TraceStage.AGENT_FIRST_CHUNK, "req-1"),
        (TraceStage.AGENT_DONE, "req-1"),
        (TraceStage.OUTPUT_ENQUEUED, "req-1"),
    ]
    # One output message per chunk, each traced (#911 Q1).
    assert _traces(caplog, "ak.ecs.outputconsumer") == [(TraceStage.OUTPUT_RECEIVED, "req-1"), (TraceStage.RESPONSE_DELIVERED, "req-1")] * 2
