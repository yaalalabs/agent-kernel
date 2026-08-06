"""Tests for RestHandler.poll_response: request_id and session_id travel as query
parameters. request_id is the sole lookup key; session_id is optional and used only
for logging/error messages, never validated against the stored response.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.core.model import ExecutionMode
from agentkernel.deployment.common.rest_handler import RestHandler


class _FakeRestHandler(RestHandler):
    def __init__(self, response_store):
        super().__init__()
        self._store = response_store

    def get_response_store(self):
        return self._store

    def get_queue_handler(self):
        raise NotImplementedError


@pytest.fixture
def client_and_store():
    config = Mock()
    config.execution.mode = ExecutionMode.REST_ASYNC
    config.execution.queues.input.url = "https://sqs.example/input"
    config.api.max_file_size = 10_000_000

    store = Mock()
    store.get_message_with_retry = AsyncMock(return_value=None)

    with (
        patch("agentkernel.deployment.common.rest_handler.AKConfig.get", return_value=config),
        patch("agentkernel.api.handler.Config.get", return_value=config),
    ):
        app = FastAPI()
        app.include_router(_FakeRestHandler(store).get_router())
        yield TestClient(app), store, config


def test_poll_succeeds_with_request_id_in_query_string(client_and_store):
    client, store, _ = client_and_store
    store.get_message_with_retry.return_value = {"body": {"reply": "hi"}}

    response = client.request("GET", RestHandler.CHAT_POLL_PATH, params={"request_id": "req-1"})

    assert response.status_code == 200
    assert response.json() == {"reply": "hi"}
    store.get_message_with_retry.assert_awaited_once_with(request_id="req-1", get_and_delete=True, async_mode=True)


def test_poll_accepts_optional_session_id_for_logging_only(client_and_store):
    """session_id, if sent, is not used as part of the lookup — request_id alone decides the result."""
    client, store, _ = client_and_store
    store.get_message_with_retry.return_value = {"body": {"reply": "hi"}}

    response = client.request("GET", RestHandler.CHAT_POLL_PATH, params={"request_id": "req-1", "session_id": "s-1"})

    assert response.status_code == 200
    store.get_message_with_retry.assert_awaited_once_with(request_id="req-1", get_and_delete=True, async_mode=True)


def test_poll_missing_request_id_returns_400(client_and_store):
    client, store, _ = client_and_store

    response = client.request("GET", RestHandler.CHAT_POLL_PATH)

    assert response.status_code == 400
    store.get_message_with_retry.assert_not_called()


def test_poll_not_found_returns_404_with_session_id_in_detail(client_and_store):
    client, store, _ = client_and_store
    store.get_message_with_retry.return_value = None

    response = client.request("GET", RestHandler.CHAT_POLL_PATH, params={"request_id": "missing", "session_id": "s-1"})

    assert response.status_code == 404
    assert response.json()["detail"]["session_id"] == "s-1"


def test_poll_rejected_outside_rest_async_mode(client_and_store):
    """The handler reads self._config bound at construction, so mutate the same mock in place."""
    client, store, config = client_and_store
    config.execution.mode = ExecutionMode.REST_SYNC

    response = client.request("GET", RestHandler.CHAT_POLL_PATH, params={"request_id": "req-1"})

    assert response.status_code == 404
    store.get_message_with_retry.assert_not_called()
