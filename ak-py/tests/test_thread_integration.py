from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import AgentReplyText, AgentRequestText, BaseRunRequest, StreamChunk
from agentkernel.core.runtime import Runtime
from agentkernel.core.thread import ConversationThreadManager, ThreadNamingStrategy
from agentkernel.core.thread.store.in_memory import InMemoryThreadStore
from agentkernel.integration.thread import AgentThreadRequestHandler, ThreadRecorder


class EchoNaming(ThreadNamingStrategy):
    """Offline test strategy: the first prompt becomes the name, no LLM call."""

    def generate_name(self, prompt: str) -> str:
        return (prompt or "").strip()


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(response=f"ok:{prompt}")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class DummyAgent(Agent):
    def __init__(self, name="thread-test-agent"):
        super().__init__(name, DummyRunner("DummyRunner"))

    def get_description(self) -> str:
        return "Test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class FakeChatService:
    """Stands in for the ChatService core on the handler's chat routes."""

    def __init__(self, reply=None, chunks=None):
        self.reply = reply if reply is not None else AgentReplyText(response="agent says hi")
        self.chunks = chunks or []
        self.calls = []

    async def execute(self, req, requests=None):
        self.calls.append((req, requests))
        return self.reply, req.session_id

    async def execute_stream(self, req, requests=None):
        self.calls.append((req, requests))

        async def _gen():
            for chunk in self.chunks:
                yield chunk

        return _gen()


@pytest.fixture
def thread_enabled():
    """Enable thread support with the in-memory store for the duration of a test."""
    AKConfig.get().thread = _ThreadStoreConfig(type="memory")
    ConversationThreadManager.reset()
    ConversationThreadManager.set_naming_strategy(EchoNaming())
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    yield ConversationThreadManager.get()
    AKConfig.get().thread = None
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()


@pytest.fixture
def registered_agent():
    agent = DummyAgent()
    Runtime.current().register(agent)
    yield agent
    Runtime.current().deregister(agent)


class TestThreadRecorder:
    def test_missing_user_id_rejected_with_exact_message(self):
        recorder = ThreadRecorder(MagicMock())
        req = BaseRunRequest(prompt="hi", session_id="s1")
        with pytest.raises(ValueError, match="user_id is required when thread support is enabled"):
            recorder.pre_run(req, [AgentRequestText(prompt="hi")])

    def test_store_attachments_rejection_fires_before_thread_creation(self):
        manager = MagicMock()
        manager.store_attachments.side_effect = ValueError("attachments need multimodal")
        recorder = ThreadRecorder(manager)
        req = BaseRunRequest(prompt="hi", session_id="s1", user_id="u1")

        with pytest.raises(ValueError, match="multimodal"):
            recorder.pre_run(req, [AgentRequestText(prompt="hi")])

        manager.get_or_create_thread.assert_not_called()
        manager.append_message.assert_not_called()

    def test_pre_run_appends_user_message_and_returns_rebuilt_requests(self):
        manager = MagicMock()
        rebuilt, attachments = [AgentRequestText(prompt="hi")], ["att-ref"]
        manager.store_attachments.return_value = (rebuilt, attachments)
        recorder = ThreadRecorder(manager)
        req = BaseRunRequest(prompt="hi", session_id="s1", user_id="u1", group_id="g1", thread_name="Chat")

        out_requests, out_attachments = recorder.pre_run(req, [AgentRequestText(prompt="hi")])

        assert out_requests is rebuilt
        assert out_attachments is attachments
        manager.get_or_create_thread.assert_called_once_with(session_id="s1", user_id="u1", group_id="g1", name="Chat", first_prompt="hi")
        manager.append_message.assert_called_once_with("s1", "user", "hi", attachments=attachments)

    def test_post_run_appends_assistant_message(self):
        manager = MagicMock()
        recorder = ThreadRecorder(manager)
        req = BaseRunRequest(prompt="hi", session_id="s1", user_id="u1")

        recorder.post_run(req, AgentReplyText(response="agent says hi"))

        manager.append_message.assert_called_once_with("s1", "assistant", "agent says hi")


class TestAgentThreadRequestHandler:
    def test_construction_fails_fast_without_thread_config(self):
        AKConfig.get().thread = None
        ConversationThreadManager.reset()
        with pytest.raises(ValueError, match="thread"):
            AgentThreadRequestHandler()

    def test_router_serves_chat_and_read_routes(self, thread_enabled):
        handler = AgentThreadRequestHandler()
        app = FastAPI()
        app.include_router(handler.get_router())
        paths = set(TestClient(app).get("/openapi.json").json()["paths"].keys())
        assert {"/api/v1/agents", "/api/v1/chat", "/api/v1/chat-multipart", "/api/v1/threads", "/api/v1/threads/{session_id}"} <= paths

    @pytest.mark.asyncio
    async def test_chat_records_user_and_assistant_messages(self, thread_enabled, registered_agent):
        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService()

        body = await handler._run_with_recording(BaseRunRequest(prompt="hi there", session_id="s1", user_id="u1", agent=registered_agent.name))

        assert body == {"result": "agent says hi", "session_id": "s1"}
        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role, m.content) for m in messages] == [("user", "hi there"), ("assistant", "agent says hi")]

    @pytest.mark.asyncio
    async def test_missing_user_id_maps_to_400(self, thread_enabled, registered_agent):
        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService()

        with pytest.raises(HTTPException) as exc:
            await handler._run_with_recording(BaseRunRequest(prompt="hi", session_id="s1", agent=registered_agent.name))

        assert exc.value.status_code == 400
        assert "user_id" in exc.value.detail["error"]
        assert thread_enabled.get_thread("s1") is None

    @pytest.mark.asyncio
    async def test_no_agent_precheck_leaves_no_phantom_thread(self, thread_enabled):
        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService()

        with pytest.raises(HTTPException) as exc:
            await handler._run_with_recording(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1", agent="no-such-agent"))

        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "No agent available"
        assert thread_enabled.get_thread("s1") is None

    @pytest.mark.asyncio
    async def test_stream_accumulates_deltas_into_assistant_message(self, thread_enabled, registered_agent):
        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService(chunks=[StreamChunk(delta="Hel"), StreamChunk(delta="lo!"), StreamChunk(done=True)])

        gen = await handler._stream_with_recording(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1", agent=registered_agent.name))
        frames = [frame async for frame in gen]

        assert all(frame.startswith("data: ") for frame in frames)
        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role, m.content) for m in messages] == [("user", "hi"), ("assistant", "Hello!")]

    @pytest.mark.asyncio
    async def test_stream_error_chunk_records_no_assistant_message(self, thread_enabled, registered_agent):
        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService(chunks=[StreamChunk(error="blocked by guardrail", done=True)])

        gen = await handler._stream_with_recording(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1", agent=registered_agent.name))
        _ = [frame async for frame in gen]

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role,) for m in messages] == [("user",)]

    @pytest.mark.asyncio
    async def test_empty_stream_records_no_assistant_message(self, thread_enabled, registered_agent):
        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService(chunks=[StreamChunk(done=True)])

        gen = await handler._stream_with_recording(BaseRunRequest(prompt="hi", session_id="s1", user_id="u1", agent=registered_agent.name))
        _ = [frame async for frame in gen]

        messages = thread_enabled.get_messages("s1").messages
        assert [(m.role,) for m in messages] == [("user",)]


class TestEndToEnd:
    def test_chat_records_and_reads_back_through_the_api(self, thread_enabled, registered_agent):
        handler = AgentThreadRequestHandler()
        app = FastAPI()
        app.include_router(handler.get_router())
        client = TestClient(app)

        resp = client.post(
            "/api/v1/chat",
            json={"prompt": "hello", "session_id": "s-e2e", "user_id": "alice", "agent": registered_agent.name},
        )
        assert resp.status_code == 200
        assert resp.json() == {"result": "ok:hello", "session_id": "s-e2e"}

        read = client.get("/api/v1/threads/s-e2e")
        assert read.status_code == 200
        body = read.json()
        assert body["user_id"] == "alice"
        assert [(m["role"], m["content"]) for m in body["messages"]] == [("user", "hello"), ("assistant", "ok:hello")]

        listing = client.get("/api/v1/threads", params={"user_id": "alice"})
        assert listing.status_code == 200
        assert [t["session_id"] for t in listing.json()["threads"]] == ["s-e2e"]
