"""ServerlessAgentRunner records the reply of a request LambdaThreadHost recorded at the edge (#879)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessAgentRunner
from agentkernel.integration.thread import ConversationThreadManager
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore
from agentkernel.pipeline.envelope import ATTR_THREAD

RUNNER_MODULE = "agentkernel.deployment.aws.serverless.akagentrunner"
MEDIA_TYPE = "application/a2ui+json"


@pytest.fixture(autouse=True)
def manager(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    AKConfig.get().thread = _ThreadStoreConfig(type="in_memory")
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    manager = ConversationThreadManager.get()
    manager.get_or_create_thread(session_id="s1", user_id="u1", group_id=None, name="t", first_prompt="hello")
    manager.append_message("s1", "user", "hello")
    yield manager
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    AKConfig._reset()


def _record(marked: bool = True) -> dict:
    attributes = {"request_id": {"stringValue": "req-1", "DataType": "String"}, "user_id": {"stringValue": "u1", "DataType": "String"}}
    if marked:
        attributes[ATTR_THREAD] = {"stringValue": "1", "DataType": "String"}
    return {
        "body": json.dumps({"prompt": "hello", "session_id": "s1", "user_id": "u1"}),
        "attributes": {"MessageGroupId": "s1", "MessageDeduplicationId": "req-1"},
        "messageAttributes": attributes,
    }


def _process(record: dict, status_code: int = 200, response: dict | None = None, send=None) -> MagicMock:
    chat_service = MagicMock()
    chat_service.process_chat_request.return_value = (status_code, response if response is not None else {"result": "ok", "session_id": "s1"})
    with (
        patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=chat_service),
        patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue", send or MagicMock()) as sent,
    ):
        ServerlessAgentRunner.process_message(record)
    return sent


def _roles(manager) -> list[str]:
    return [m.role for m in manager.get_messages("s1").messages]


def test_a_marked_record_appends_the_reply_with_its_media_type(manager):
    _process(_record(), response={"result": {"k": "v"}, "media_type": MEDIA_TYPE, "session_id": "s1"})

    reply = manager.get_messages("s1").messages[-1]
    assert _roles(manager) == ["user", "assistant"]
    assert reply.media_type == MEDIA_TYPE


@pytest.mark.parametrize(
    "record,status_code,response",
    [
        (_record(marked=False), 200, None),
        (_record(), 400, {"error": "bad", "session_id": "s1"}),
        (_record(), 200, {"result": "", "session_id": "s1"}),
    ],
    ids=["unmarked", "failed-run", "empty-reply"],
)
def test_nothing_is_recorded(manager, record, status_code, response):
    _process(record, status_code=status_code, response=response)

    assert _roles(manager) == ["user"]


def test_a_runner_without_a_thread_block_warns(manager, caplog):
    ConversationThreadManager.reset()
    AKConfig.get().thread = None

    with caplog.at_level("WARNING"):
        _process(_record())

    assert "no 'thread' config block" in caplog.text


def test_a_store_failure_is_logged_and_the_message_succeeds(manager, monkeypatch, caplog):
    monkeypatch.setattr(manager, "append_message", MagicMock(side_effect=RuntimeError("store down")))

    with caplog.at_level("ERROR"):
        sent = _process(_record())

    sent.assert_called_once()
    assert "Failed to record the assistant message" in caplog.text


def test_recording_happens_after_the_output_send(manager, monkeypatch):
    order = []
    monkeypatch.setattr(manager, "append_message", MagicMock(side_effect=lambda *a, **k: order.append("record")))

    _process(_record(), send=MagicMock(side_effect=lambda *a, **k: order.append("send")))

    assert order == ["send", "record"]
