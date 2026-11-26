"""#911: the ECS WebSocket handler traces its enqueue stages. The runner and consumer are the shared pipeline classes,
traced in test_pipeline_request_handler.py."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.core.config import _ExecutionConfig
from agentkernel.core.logger import TRACE, TraceStage
from agentkernel.core.model import ExecutionMode, Principal
from agentkernel.deployment.aws.containerized.core.api.websocket_api import ECSWebSocketRequestHandler

WS_MODULE = "agentkernel.deployment.aws.containerized.core.api.websocket_api"
ENDPOINT_URL = "https://example.execute-api.us-east-1.amazonaws.com/prod"


def _traces(caplog, logger: str) -> list[tuple[TraceStage, str]]:
    return [(record.args[0], record.args[1]) for record in caplog.records if record.levelno == TRACE and record.name == logger]


async def _enqueue_ws_chat(monkeypatch, caplog, message_type: str | None) -> dict:
    config = SimpleNamespace(
        websocket_api=SimpleNamespace(endpoint_url=ENDPOINT_URL, connection_table=SimpleNamespace(table_name="t", ttl=3600)),
        execution=_ExecutionConfig(mode=ExecutionMode.ASYNC, message_type=message_type),
        identity=None,
        registry=None,
    )
    config.execution.queues.input.url = "https://sqs.test/input"
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: config))
    handler = ECSWebSocketRequestHandler()
    request = MagicMock(headers={handler.CONNECTION_ID_HEADER: "c1"})
    request.body = AsyncMock(return_value=json.dumps({"request_id": "req-1", "body": {"session_id": "s1", "prompt": "hi"}}).encode())
    principal = Principal(subject="u1", provider="static", namespace="static")
    seen = {}  # the stages already traced when each traced action starts

    def _get_principal(connection_id):
        seen["principal lookup"] = [stage for stage, _ in _traces(caplog, "ak.ecs.ws_handler")]
        return principal

    def _send(**kwargs):
        seen["send"] = [stage for stage, _ in _traces(caplog, "ak.ecs.ws_handler")]

    handler.get_websocket_handler = MagicMock(return_value=MagicMock(get_principal=_get_principal))
    with patch(f"{WS_MODULE}.SQSHandler.send_message_to_input_queue", side_effect=_send):
        assert (await handler._handle_chat(request=request)).status_code == 200
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("message_type", [None, "delta"])
async def test_ws_enqueue(caplog, monkeypatch, message_type):
    with caplog.at_level(TRACE, logger="ak"):
        seen = await _enqueue_ws_chat(monkeypatch, caplog, message_type=message_type)

    assert _traces(caplog, "ak.ecs.ws_handler") == [(TraceStage.REQUEST_HANDLER_START, "req-1"), (TraceStage.INPUT_ENQUEUED, "req-1")]
    # Each stage is traced before the work it names starts.
    assert seen == {"principal lookup": [TraceStage.REQUEST_HANDLER_START], "send": [TraceStage.REQUEST_HANDLER_START, TraceStage.INPUT_ENQUEUED]}
