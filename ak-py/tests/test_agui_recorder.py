"""AGUIThreadRecorder: AG-UI runs adapted to ThreadRecorder (#836)."""

import logging
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import AgentRequestText, Principal, StreamChunk
from agentkernel.integration.agui.recorder import AGUIThreadRecorder
from agentkernel.integration.agui.run_input import AGUIRunInput
from agentkernel.integration.thread import ConversationThreadManager, ThreadNamingStrategy
from agentkernel.integration.thread.model import HITL_MEDIA_TYPE
from agentkernel.integration.thread.recorder import StreamedReply, ThreadRecorder
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore

PNG_B64 = "iVBORw0KGgo="
U1 = Principal(subject="u1", provider="static", namespace="static")


def body(content="hello", **overrides):
    payload = {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": content}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }
    payload.update(overrides)
    return payload


def chat_request(raw: dict):
    run_input = AGUIRunInput.parse(raw)
    requests = AGUIRunInput.to_requests(run_input)
    return AGUIThreadRecorder.chat_request(run_input, U1, "planner", requests), requests


def image_part():
    return {"type": "image", "source": {"type": "data", "value": PNG_B64, "mimeType": "image/png"}}


def text_reply(text: str) -> StreamedReply:
    reply = StreamedReply("thread-1")
    reply.add(StreamChunk(delta=text))
    reply.add(StreamChunk(done=True))
    return reply


class _FixedNaming(ThreadNamingStrategy):
    def generate_name(self, prompt: str) -> str:
        return "thread"


@pytest.fixture
def thread_store():
    AKConfig.get().thread = _ThreadStoreConfig(type="in_memory")
    ConversationThreadManager.reset()
    ConversationThreadManager.set_naming_strategy(_FixedNaming())
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    yield ConversationThreadManager.get()
    AKConfig.get().thread = None
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()


class TestCreate:
    def test_no_thread_block_means_no_recorder(self):
        AKConfig.get().thread = None
        ConversationThreadManager.reset()
        assert AGUIThreadRecorder.create() is None

    def test_a_thread_block_enables_it(self, thread_store):
        assert isinstance(AGUIThreadRecorder.create(), AGUIThreadRecorder)


class TestChatRequest:
    def test_a_text_turn(self):
        req, _ = chat_request(body("plan my week"))
        assert (req.session_id, req.principal, req.agent, req.prompt, req.resume) == ("thread-1", U1, "planner", "plan my week", None)

    def test_text_parts_are_joined(self):
        req, _ = chat_request(body([{"type": "text", "text": "look"}, image_part(), {"type": "text", "text": "at this"}]))
        assert req.prompt == "look\nat this"

    def test_an_image_only_turn_has_an_empty_prompt(self):
        req, _ = chat_request(body([image_part()]))
        assert req.prompt == ""

    def test_a_resume_carries_the_decisions(self):
        req, requests = chat_request(body(resume=[{"interruptId": "i1", "status": "resolved", "payload": True}]))
        assert req.prompt == ""
        assert req.resume.run_id is None
        assert [(d.id, d.status) for d in req.resume.decisions] == [("i1", "approved")]
        assert req.resume.decisions == requests[-1].decisions


class TestPreRun:
    def test_records_the_user_turn(self, thread_store):
        req, requests = chat_request(body("plan my week"))
        AGUIThreadRecorder.create().pre_run(req, requests)

        thread = thread_store.get_thread("thread-1")
        messages = thread_store.get_messages("thread-1").messages
        assert thread.user_id == "u1"
        assert [(m.role, m.content) for m in messages] == [("user", "plan my week")]

    def test_a_resume_records_the_decision(self, thread_store):
        req, requests = chat_request(body(resume=[{"interruptId": "i1", "status": "resolved", "payload": True}]))
        AGUIThreadRecorder.create().pre_run(req, requests)

        message = thread_store.get_messages("thread-1").messages[0]
        assert message.media_type == HITL_MEDIA_TYPE
        assert message.content["resume"]["decisions"][0]["id"] == "i1"

    def test_a_refused_attachment_is_a_400_and_writes_nothing(self, thread_store, monkeypatch):
        monkeypatch.setattr(AKConfig.get().multimodal, "enabled", False)
        req, requests = chat_request(body([image_part()]))
        with pytest.raises(HTTPException) as excinfo:
            AGUIThreadRecorder.create().pre_run(req, requests)

        assert excinfo.value.status_code == 400
        assert thread_store.get_thread("thread-1") is None

    def test_another_users_thread_is_a_403_and_writes_nothing(self, thread_store):
        thread_store.get_or_create_thread(session_id="thread-1", user_id="owner", first_prompt="mine")
        req, requests = chat_request(body("hijack"))
        with pytest.raises(HTTPException) as excinfo:
            AGUIThreadRecorder.create().pre_run(req, requests)

        assert excinfo.value.status_code == 403
        assert thread_store.get_messages("thread-1").messages == []

    def test_a_thread_created_concurrently_by_another_user_is_a_403(self, thread_store, monkeypatch):
        thread_store.get_or_create_thread(session_id="thread-1", user_id="owner", first_prompt="mine")
        threads = AGUIThreadRecorder.create()
        monkeypatch.setattr(thread_store, "get_thread", lambda session_id, user_id=None: None)
        monkeypatch.setattr(thread_store._store, "load_metadata", lambda session_id: None)
        req, requests = chat_request(body("hijack"))
        with pytest.raises(HTTPException) as excinfo:
            threads.pre_run(req, requests)

        assert excinfo.value.status_code == 403
        assert InMemoryThreadStore._messages["thread-1"] == []

    def test_returns_the_rebuilt_requests(self):
        rebuilt = [AgentRequestText(prompt="rebuilt")]
        recorder = MagicMock(spec=ThreadRecorder)
        recorder.pre_run.return_value = (rebuilt, [])
        req, requests = chat_request(body())

        assert AGUIThreadRecorder(recorder).pre_run(req, requests) is rebuilt


class TestPostRun:
    def test_records_the_reply(self, thread_store):
        req, requests = chat_request(body("plan my week"))
        threads = AGUIThreadRecorder.create()
        threads.pre_run(req, requests)
        threads.post_run(req, text_reply("Here is your plan"))

        messages = thread_store.get_messages("thread-1").messages
        assert [(m.role, m.content) for m in messages] == [("user", "plan my week"), ("assistant", "Here is your plan")]

    def test_nothing_to_record_is_a_no_op(self):
        recorder = MagicMock(spec=ThreadRecorder)
        req, _ = chat_request(body())

        AGUIThreadRecorder(recorder).post_run(req, StreamedReply("thread-1"))

        recorder.post_run.assert_not_called()

    def test_a_store_failure_is_logged_not_raised(self, caplog):
        recorder = MagicMock(spec=ThreadRecorder)
        recorder.post_run.side_effect = RuntimeError("store down")
        req, _ = chat_request(body())

        with caplog.at_level(logging.ERROR, logger="ak.integration.agui.recorder"):
            AGUIThreadRecorder(recorder).post_run(req, text_reply("hi"))

        assert "thread-1" in caplog.text
