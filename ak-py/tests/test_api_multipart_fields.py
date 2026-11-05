"""Regression tests for the multipart chat endpoint's form fields.

FastAPI silently discards multipart fields that are absent from the endpoint signature, so a
field dropped from ``run_multipart`` fails invisibly: the request still succeeds, the value just
never reaches the agent. ``user_id`` in particular is mandatory once Conversation Thread Support
is configured, and ``group_id``/``thread_name`` feed thread auto-creation.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.api.handler import AgentRESTRequestHandler
from agentkernel.core.config import _ExecutionConfig
from agentkernel.core.model import ExecutionMode

# Every form field the endpoint must accept and forward, beyond the file/image uploads.
EXPECTED_FORM_FIELDS = ("prompt", "agent", "session_id", "user_id", "group_id", "thread_name")


@contextmanager
def _mounted(mode=ExecutionMode.REST_SYNC, message_type=None):
    """Mount the handler's router on a TestClient, capturing each request model ChatService receives."""
    captured = []

    config = Mock()
    config.api.max_file_size = 10_000_000
    config.execution = _ExecutionConfig(mode=mode, message_type=message_type)

    async def _sse(req, sse_format):
        captured.append(req)

        async def _frames():
            yield 'data: {"delta": "hi", "done": false}\n\n'
            yield 'data: {"done": true}\n\n'

        return _frames()

    chat_service = Mock()
    chat_service.process_async_chat_request = AsyncMock(side_effect=lambda req: captured.append(req) or {"reply": "ok"})
    chat_service.process_stream_chat_async = AsyncMock(side_effect=_sse)

    with patch("agentkernel.api.handler.Config.get", return_value=config), patch("agentkernel.api.handler.ChatService", return_value=chat_service):
        app = FastAPI()
        app.include_router(AgentRESTRequestHandler().get_router())
        yield TestClient(app), captured


@pytest.fixture
def captured_requests():
    with _mounted() as mounted:
        yield mounted


def test_multipart_forwards_every_form_field(captured_requests):
    """All six form fields must land on the request model — not just prompt/agent/session_id."""
    client, captured = captured_requests

    response = client.post(
        AgentRESTRequestHandler.CHAT_MULTIPART_PATH,
        data={
            "prompt": "hello",
            "agent": "triage",
            "session_id": "s-1",
            "user_id": "u-1",
            "group_id": "g-1",
            "thread_name": "my thread",
        },
    )

    assert response.status_code == 200
    assert len(captured) == 1
    req = captured[0]
    assert (req.prompt, req.agent, req.session_id) == ("hello", "triage", "s-1")
    assert (req.user_id, req.group_id, req.thread_name) == ("u-1", "g-1", "my thread")


@pytest.mark.parametrize("field", EXPECTED_FORM_FIELDS)
def test_multipart_declares_field_in_openapi_schema(captured_requests, field):
    """Each field must be declared in the signature, or FastAPI drops it without an error."""
    client, _ = captured_requests

    schema = client.app.openapi()
    body = schema["paths"][AgentRESTRequestHandler.CHAT_MULTIPART_PATH]["post"]["requestBody"]
    multipart = body["content"]["multipart/form-data"]["schema"]
    properties = client.app.openapi()["components"]["schemas"][multipart["$ref"].rsplit("/", 1)[-1]]["properties"]

    assert field in properties


def test_multipart_optional_fields_default_to_none(captured_requests):
    """Omitting the optional fields must not fail the request; they arrive as None."""
    client, captured = captured_requests

    response = client.post(AgentRESTRequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "hello"})

    assert response.status_code == 200
    req = captured[0]
    assert (req.user_id, req.group_id, req.thread_name) == (None, None, None)


class TestReplyMessageType:
    """The direct REST handler streams SSE only for rest_sync + delta (#641)."""

    def test_rest_sync_delta_streams_sse_on_chat(self):
        with _mounted(ExecutionMode.REST_SYNC, "delta") as (client, captured):
            response = client.post(AgentRESTRequestHandler.CHAT_PATH, json={"prompt": "hello", "session_id": "s-1"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"delta": "hi"' in response.text
        assert captured[0].prompt == "hello"

    def test_rest_sync_delta_streams_sse_on_multipart(self):
        with _mounted(ExecutionMode.REST_SYNC, "delta") as (client, _):
            response = client.post(AgentRESTRequestHandler.CHAT_MULTIPART_PATH, data={"prompt": "hello"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

    @pytest.mark.parametrize("path", [AgentRESTRequestHandler.CHAT_PATH, AgentRESTRequestHandler.CHAT_MULTIPART_PATH])
    def test_async_delta_returns_json(self, path):
        """Under async the direct handler keeps returning JSON, whichever message type is set."""
        with _mounted(ExecutionMode.ASYNC, "delta") as (client, _):
            if path == AgentRESTRequestHandler.CHAT_PATH:
                response = client.post(path, json={"prompt": "hello", "session_id": "s-1"})
            else:
                response = client.post(path, data={"prompt": "hello"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"reply": "ok"}
