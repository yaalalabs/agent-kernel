"""Conversation Thread Support on the queue pipeline.

The direct handler brackets one in-process call (pre_run -> execute -> post_run). Here the agent
runs on the far side of the input queue, so the bracket is split: ThreadRequestHandler records the
user message and marks the message before enqueueing, and AgentRunner appends the reply. These
tests pin both halves and the marker that joins them.
"""

import json
import threading
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
from agentkernel.core.model import AgentReplyText, AgentRequestText, ScheduleSpec
from agentkernel.core.runtime import Runtime
from agentkernel.integration.thread import ConversationThreadManager, ThreadNamingStrategy, ThreadRequestHandler
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore
from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.consumer import ConsumerLoop
from agentkernel.pipeline.envelope import ATTR_THREAD, QueueMessage, QueueName
from agentkernel.pipeline.io_handler import IOHandler
from agentkernel.pipeline.request_handler import RequestHandler
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

AGENT_NAME = "thread-pipeline-agent"
CHAT = RequestHandler.CHAT_PATH


class EchoNaming(ThreadNamingStrategy):
    """Offline naming: the first prompt becomes the thread name, no LLM call."""

    def generate_name(self, prompt: str) -> str:
        return (prompt or "").strip()


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(response=f"ok:{prompt}")

    async def stream(self, agent, session, requests):
        yield MessageStart(message_id="m-1")
        for token in ("he", "llo"):
            yield TextDelta(message_id="m-1", content=token)
        yield MessageEnd(message_id="m-1")


class DummyAgent(Agent):
    def __init__(self):
        super().__init__(AGENT_NAME, DummyRunner("DummyRunner"))

    def get_description(self) -> str:
        return "Thread pipeline test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    ThreadRunner.shutdown_event.clear()
    ConversationThreadManager.reset()
    AKConfig._reset()


@pytest.fixture
def dummy_agent():
    agent = DummyAgent()
    Runtime.current().register(agent)
    yield agent
    Runtime.current().deregister(agent)


def _configure(monkeypatch, mode=None):
    """Real defaults (in_memory transport) with a fast response-wait budget, then threads on."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    if mode:
        monkeypatch.setenv("AK_EXECUTION__MODE", mode)
    else:
        monkeypatch.delenv("AK_EXECUTION__MODE", raising=False)
    monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT", "100")
    monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__DELAY", "0.05")
    AKConfig._reset()
    return _enable_threads()


def _enable_threads():
    AKConfig.get().thread = _ThreadStoreConfig(type="in_memory")
    ConversationThreadManager.reset()
    ConversationThreadManager.set_naming_strategy(EchoNaming())
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    return ConversationThreadManager.get()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ThreadRequestHandler().get_router())
    return TestClient(app)


def _enqueued(transport=None) -> QueueMessage:
    """The single message the handler put on the input queue."""
    [message] = (transport or InMemoryTransport()).create_consumer(QueueName.INPUT).fetch(10, 0.5)
    return message


def _chat(session_id="s1", prompt="hello", user_id="u1", **extra) -> dict:
    return {"prompt": prompt, "session_id": session_id, "user_id": user_id, "agent": AGENT_NAME, **extra}


class TestEdgeRecording:
    def test_user_message_is_recorded_and_the_message_is_marked(self, monkeypatch, dummy_agent):
        manager = _configure(monkeypatch, mode="rest_async")

        response = _client().post(CHAT, json=_chat())

        assert response.status_code == 200
        message = _enqueued()
        # The marker is what tells the runner on the other side that a user message is already
        # recorded and a reply is owed to this thread.
        assert message.attributes[ATTR_THREAD] == "1"
        [recorded] = manager.get_messages("s1").messages
        assert (recorded.role, recorded.content) == ("user", "hello")
        assert manager.get_thread("s1").name == "hello"

    def test_the_plain_request_handler_marks_nothing(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_async")
        app = FastAPI()
        app.include_router(RequestHandler().get_router())

        TestClient(app).post(CHAT, json=_chat())

        # A thread block is configured, but this producer did not record: the runner must not
        # grow a thread nobody opened.
        assert ATTR_THREAD not in _enqueued().attributes
        assert ConversationThreadManager.get().get_thread("s1") is None

    def test_attachments_are_offloaded_before_the_queue(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_async")
        AKConfig.get().multimodal.enabled = True
        AKConfig.get().multimodal.storage_type = "in_memory"

        payload = _chat(images=[{"image_data": "aGVsbG8=", "name": "a.png", "mime_type": "image/png"}])
        assert _client().post(CHAT, json=payload).status_code == 200

        message = _enqueued()
        # The bytes were stored at the edge and replaced by a reference: an attachment must never
        # ride the queue, where a real broker's message-size limit is waiting.
        assert "aGVsbG8=" not in message.body
        body = json.loads(message.body)
        assert body.get("images") is None
        assert [req["type"] for req in body["requests"]] == ["text", "attachment_ref"]

    def test_missing_user_id_is_rejected_before_any_thread_write(self, monkeypatch, dummy_agent):
        manager = _configure(monkeypatch, mode="rest_async")

        response = _client().post(CHAT, json={"prompt": "hello", "session_id": "s1", "agent": AGENT_NAME})

        assert response.status_code == 400
        assert "user_id" in response.json()["detail"]["error"]
        assert manager.get_thread("s1") is None
        assert not InMemoryTransport().create_consumer(QueueName.INPUT).fetch(10, 0.1)

    def test_an_unavailable_agent_leaves_no_phantom_thread(self, monkeypatch, dummy_agent):
        manager = _configure(monkeypatch, mode="rest_async")

        response = _client().post(CHAT, json=_chat(agent="nope"))

        assert response.status_code == 400
        assert manager.get_thread("s1") is None

    def test_a_deferred_request_records_nothing_and_is_unmarked(self, monkeypatch, dummy_agent):
        manager = _configure(monkeypatch, mode="rest_async")

        payload = _chat(schedule=ScheduleSpec(at="2999-01-01T00:00:00Z").model_dump(exclude_none=True))
        _client().post(CHAT, json=payload)

        # The 202 acknowledgement is not something the agent said, so it is never appended.
        assert ATTR_THREAD not in _enqueued().attributes
        assert manager.get_thread("s1") is None

    def test_missing_prompt_keeps_the_pipeline_error_shape(self, monkeypatch, dummy_agent):
        _configure(monkeypatch, mode="rest_async")

        response = _client().post(CHAT, json={"prompt": "", "session_id": "s1", "user_id": "u1"})

        assert response.status_code == 400
        assert response.json()["detail"] == {"error": "No prompt provided in the request", "session_id": "s1"}


def _marked_message(session_id="s1", user_id="u1", marked=True) -> QueueMessage:
    return QueueMessage(
        body=json.dumps({"prompt": "hello", "session_id": session_id, "user_id": user_id, "agent": AGENT_NAME}),
        attributes={"request_id": "r1", **({ATTR_THREAD: "1"} if marked else {})},
        group_id=session_id,
        dedup_id="d1",
        message_id="m1",
    )


def _open_thread(manager, session_id="s1"):
    manager.get_or_create_thread(session_id=session_id, user_id="u1", group_id=None, name=None, first_prompt="hello")
    manager.append_message(session_id, "user", "hello")


class TestRunnerRecording:
    def _runner(self, status_code=200, result="ok:hello"):
        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (status_code, {"result": result, "session_id": "s1"})
        return AgentRunner(transport=InMemoryTransport(), chat_service=chat_service)

    def test_reply_is_appended_for_a_marked_message(self, monkeypatch):
        manager = _configure(monkeypatch)
        _open_thread(manager)

        self._runner().process(_marked_message())

        assert [(m.role, m.content) for m in manager.get_messages("s1").messages] == [("user", "hello"), ("assistant", "ok:hello")]

    def test_an_unmarked_message_records_nothing(self, monkeypatch):
        manager = _configure(monkeypatch)
        _open_thread(manager)

        self._runner().process(_marked_message(marked=False))

        assert [m.role for m in manager.get_messages("s1").messages] == ["user"]

    def test_a_failed_run_records_nothing(self, monkeypatch):
        manager = _configure(monkeypatch)
        _open_thread(manager)

        self._runner(status_code=500, result=None).process(_marked_message())

        assert [m.role for m in manager.get_messages("s1").messages] == ["user"]

    def test_a_thread_store_failure_never_retries_the_run(self, monkeypatch, caplog):
        manager = _configure(monkeypatch)
        _open_thread(manager)
        monkeypatch.setattr(manager, "append_message", MagicMock(side_effect=RuntimeError("store down")))

        with caplog.at_level("ERROR"):
            # Must not raise: the reply is already on the output queue, so a redelivery would run
            # the agent a second time to fix a bookkeeping problem.
            self._runner().process(_marked_message())

        assert "Failed to record the assistant message" in caplog.text

    def test_recording_happens_after_the_reply_is_on_the_output_queue(self, monkeypatch):
        manager = _configure(monkeypatch)
        _open_thread(manager)
        transport = InMemoryTransport()
        order = []
        monkeypatch.setattr(transport, "send", MagicMock(side_effect=lambda *a, **k: order.append("send")))
        monkeypatch.setattr(manager, "append_message", MagicMock(side_effect=lambda *a, **k: order.append("record")))
        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (200, {"result": "ok:hello", "session_id": "s1"})

        AgentRunner(transport=transport, chat_service=chat_service).process(_marked_message())

        assert order == ["send", "record"]

    def test_a_runner_without_thread_config_warns_instead_of_failing(self, monkeypatch, caplog):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        AKConfig._reset()
        ConversationThreadManager.reset()

        with caplog.at_level("WARNING"):
            self._runner().process(_marked_message())

        assert "no 'thread' config block" in caplog.text


class TestStreamRunnerRecording:
    def _stream_runner(self, chunks):
        chat_service = MagicMock()
        chat_service.process_stream_chat_sync.return_value = [json.dumps(chunk) for chunk in chunks]
        return StreamAgentRunner(transport=InMemoryTransport(), chat_service=chat_service)

    def test_deltas_are_accumulated_into_one_assistant_message(self, monkeypatch):
        manager = _configure(monkeypatch, mode="stream")
        _open_thread(manager)

        self._stream_runner([{"delta": "he"}, {"delta": "llo"}, {"done": True}]).process(_marked_message())

        # The chunks fan out as separate output messages, so this is the only place the reply
        # exists as one thing.
        assert [(m.role, m.content) for m in manager.get_messages("s1").messages][-1] == ("assistant", "hello")

    def test_a_halted_stream_records_nothing(self, monkeypatch):
        manager = _configure(monkeypatch, mode="stream")
        _open_thread(manager)

        self._stream_runner([{"delta": "he"}, {"error": "boom", "done": True}]).process(_marked_message())

        assert [m.role for m in manager.get_messages("s1").messages] == ["user"]

    def test_an_empty_stream_records_no_blank_message(self, monkeypatch):
        manager = _configure(monkeypatch, mode="stream")
        _open_thread(manager)

        self._stream_runner([{"done": True}]).process(_marked_message())

        assert [m.role for m in manager.get_messages("s1").messages] == ["user"]


class TestMounting:
    def test_the_thread_handler_replaces_the_pipeline_chat_route(self, monkeypatch):
        """One chat route, not two: a second registration of POST /api/v1/chat would be shadowed."""
        captured = {}
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        AKConfig._reset()
        _enable_threads()
        monkeypatch.setattr(
            "agentkernel.api.http.RESTAPI.build_app",
            classmethod(lambda cls, handlers=None: captured.update(handlers=handlers) or MagicMock()),
        )
        monkeypatch.setattr("agentkernel.pipeline.io_handler.uvicorn.Server", MagicMock())
        monkeypatch.setattr(IOHandler, "_install_signal_handlers", classmethod(lambda cls, server: None))
        monkeypatch.setattr(ThreadRunner, "run", staticmethod(lambda tasks, max_workers=None, exit_on_shutdown=True: None))

        IOHandler.run(request_handler=ThreadRequestHandler())

        [handler] = captured["handlers"]
        assert isinstance(handler, ThreadRequestHandler)

    def test_it_is_pipeline_only(self):
        # A bare RESTAPI app would enqueue into a queue no runner drains.
        assert ThreadRequestHandler.requires_pipeline is True


class TestEndToEnd:
    @pytest.fixture
    def workers(self):
        threads = []
        transport = InMemoryTransport()
        for component, queue in ((AgentRunner(transport=transport), QueueName.INPUT), (ResponseHandler(transport=transport), QueueName.OUTPUT)):
            loop = ConsumerLoop(
                process=component.process,
                on_permanent_failure=component.on_permanent_failure,
                max_receive_count=3,
                num_consumers=1,
                batch_size=10,
                consumer_factory=lambda q=queue: transport.create_consumer(q),
                thread_name_prefix="thread-e2e",
                wait_seconds=0.05,
            )
            thread = threading.Thread(target=loop._consumer_loop, daemon=True)
            thread.start()
            threads.append(thread)
        yield
        ThreadRunner.shutdown_event.set()
        for thread in threads:
            thread.join(timeout=2)

    def test_both_sides_of_the_exchange_are_readable_from_the_thread_routes(self, monkeypatch, dummy_agent, workers):
        _configure(monkeypatch, mode="rest_sync")
        client = _client()

        response = client.post(CHAT, json=_chat())

        assert response.json() == {"result": "ok:hello", "session_id": "s1"}
        thread = client.get("/api/v1/threads/s1").json()
        assert [(m["role"], m["content"]) for m in thread["messages"]] == [("user", "hello"), ("assistant", "ok:hello")]
