"""Regression tests for the multipart chat endpoint's form fields.

FastAPI silently discards multipart fields that are absent from the endpoint signature, so a
field dropped from ``run_multipart`` fails invisibly: the request still succeeds, the value just
never reaches the agent. ``user_id`` in particular is mandatory once Conversation Thread Support
is configured, and ``group_id``/``thread_name`` feed thread auto-creation.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.api.handler import AgentRESTRequestHandler
from agentkernel.core.model import ExecutionMode

# Every form field the endpoint must accept and forward, beyond the file/image uploads.
EXPECTED_FORM_FIELDS = ("prompt", "agent", "session_id", "user_id", "group_id", "thread_name")


@pytest.fixture
def captured_requests():
    """Mount the handler's router on a TestClient, capturing each request model ChatService receives."""
    captured = []

    config = Mock()
    config.api.max_file_size = 10_000_000
    config.execution.mode = ExecutionMode.REST_SYNC

    chat_service = Mock()
    chat_service.process_async_chat_request = AsyncMock(side_effect=lambda req: captured.append(req) or {"reply": "ok"})

    with patch("agentkernel.api.handler.Config.get", return_value=config), patch("agentkernel.api.handler.ChatService", return_value=chat_service):
        app = FastAPI()
        app.include_router(AgentRESTRequestHandler().get_router())
        yield TestClient(app), captured


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
