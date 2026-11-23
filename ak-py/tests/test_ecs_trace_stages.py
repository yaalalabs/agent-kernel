"""#911: the ECS WebSocket handler traces its enqueue stages. The runner and consumer are the shared pipeline classes,
traced in test_pipeline_request_handler.py."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.core.config import _ExecutionConfig
from agentkernel.core.logger import TRACE, TraceStage
from agentkernel.core.model import BaseRequest, ExecutionMode, Principal
from agentkernel.deployment.aws.containerized.core.api.websocket_api import ECSWebSocketRequestHandler

WS_MODULE = "agentkernel.deployment.aws.containerized.core.api.websocket_api"
ENDPOINT_URL = "https://example.execute-api.us-east-1.amazonaws.com/prod"


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


@pytest.mark.asyncio
@pytest.mark.parametrize("message_type", [None, "delta"])
async def test_ws_enqueue(caplog, monkeypatch, message_type):
    with caplog.at_level(TRACE, logger="ak"):
        await _enqueue_ws_chat(monkeypatch, message_type=message_type)

    assert _traces(caplog, "ak.ecs.ws_handler") == [(TraceStage.REQUEST_RECEIVED, "req-1"), (TraceStage.INPUT_ENQUEUED, "req-1")]
