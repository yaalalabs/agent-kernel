"""StreamedReply: what a streamed run leaves in a conversation thread (#836)."""

from unittest.mock import MagicMock

import pytest

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.event import DataMessage, PausedInterruption, RunPaused
from agentkernel.core.model import AgentPausedReplyAny, AgentReplyAny, AgentReplyText, BaseRunRequest, Principal, StreamChunk
from agentkernel.core.runtime import Runtime
from agentkernel.identity import IdentityProviderFactory
from agentkernel.integration.thread import AgentThreadRequestHandler, ConversationThreadManager, ThreadNamingStrategy
from agentkernel.integration.thread.model import HITL_MEDIA_TYPE
from agentkernel.integration.thread.recorder import StreamedReply, ThreadRecorder
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore

A2UI = "application/a2ui+json"


def paused_event(agent: str = "agent-1") -> RunPaused:
    return RunPaused(
        run_id="run-1",
        agent=agent,
        interruptions=[PausedInterruption(id="i1", kind="tool_call", tool_name="refund", arguments='{"order": 7}')],
    )


def reply_from(*chunks: StreamChunk, session_id: str = "s1") -> StreamedReply:
    reply = StreamedReply(session_id)
    for chunk in chunks:
        reply.add(chunk)
    return reply


class TestStreamedReply:
    def test_text_deltas_are_joined(self):
        reply = reply_from(StreamChunk(delta="Hel"), StreamChunk(delta="lo"), StreamChunk(done=True))
        assert reply.result() == "Hello"
        assert reply.paused is False

    def test_an_empty_run_records_nothing(self):
        assert reply_from(StreamChunk(done=True)).result() is None

    def test_an_error_records_nothing(self):
        reply = reply_from(StreamChunk(delta="partial"), StreamChunk(error="model unavailable", done=True))
        assert reply.result() is None

    def test_a_pause_records_the_paused_reply(self):
        reply = reply_from(StreamChunk(event=paused_event()), StreamChunk(done=True), session_id="thread-9")

        result = reply.result()
        assert isinstance(result, AgentPausedReplyAny)
        assert (result.run_id, result.session_id, result.agent) == ("run-1", "thread-9", "agent-1")
        assert [i.id for i in result.interruptions] == ["i1"]
        assert reply.paused is True

    def test_a_pause_replaces_the_text_streamed_before_it(self):
        reply = reply_from(StreamChunk(delta="Let me check"), StreamChunk(event=paused_event()), StreamChunk(done=True))
        assert isinstance(reply.result(), AgentPausedReplyAny)

    def test_an_error_after_a_pause_records_nothing(self):
        """The failure after a pause is the one that never persisted it."""
        reply = reply_from(StreamChunk(event=paused_event()), StreamChunk(error="session store unavailable", done=True))
        assert reply.result() is None
        assert reply.paused is False

    def test_a_data_message_records_the_labelled_payload(self):
        payload = {"surfaceUpdate": {"components": []}}
        reply = reply_from(
            StreamChunk(delta="ignored text"),
            StreamChunk(event=DataMessage(message_id="m1", content=payload, media_type=A2UI)),
            StreamChunk(done=True),
        )

        result = reply.result()
        assert isinstance(result, AgentReplyAny)
        assert ThreadRecorder._as_thread_message(result) == (payload, A2UI)

    def test_an_unlabelled_data_message_records_json_text(self):
        """No label, no object: the #763 switch, so an unlabelled payload is stored as text."""
        reply = reply_from(StreamChunk(event=DataMessage(message_id="m1", content={"a": 1})), StreamChunk(done=True))
        assert ThreadRecorder._as_thread_message(reply.result()) == ('{"a": 1}', None)

    def test_a_pause_beats_a_data_message(self):
        reply = reply_from(
            StreamChunk(event=DataMessage(message_id="m1", content={"a": 1}, media_type=A2UI)),
            StreamChunk(event=paused_event()),
            StreamChunk(done=True),
        )
        assert isinstance(reply.result(), AgentPausedReplyAny)


class _FixedNaming(ThreadNamingStrategy):
    def generate_name(self, prompt: str) -> str:
        return "thread"


class _Runner(Runner):
    async def run(self, agent, session, requests):
        return AgentReplyText(response="unused")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Agent(Agent):
    def __init__(self):
        super().__init__("streamed-reply-agent", _Runner("StreamedReplyRunner"))

    def get_description(self) -> str:
        return "Test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class _FakeChatService:
    def __init__(self, chunks):
        self.chunks = chunks

    async def execute_stream(self, req, requests=None):
        async def _gen():
            for chunk in self.chunks:
                yield chunk

        return _gen()


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


@pytest.fixture
def agent():
    registered = _Agent()
    Runtime.current().register(registered)
    yield registered
    Runtime.current().deregister(registered)


@pytest.mark.asyncio
async def test_a_pause_is_stored_as_the_same_bytes_as_the_rest_stream(thread_store, agent, monkeypatch):
    """Parity with the threaded REST SSE path, which builds its own paused reply inline."""
    chunks = [StreamChunk(delta="Let me check"), StreamChunk(event=paused_event(agent.name)), StreamChunk(done=True)]
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: MagicMock()))
    handler = AgentThreadRequestHandler()
    handler.chat_service = _FakeChatService(chunks)

    gen = await handler._stream_with_recording(
        BaseRunRequest(
            prompt="refund it", session_id="s1", principal=Principal(subject="u1", provider="static", namespace="static"), agent=agent.name
        )
    )
    _ = [frame async for frame in gen]
    stored = thread_store.get_messages("s1").messages[1]

    content, media_type = ThreadRecorder._as_thread_message(reply_from(*chunks).result())
    assert stored.media_type == media_type == HITL_MEDIA_TYPE
    assert stored.content == content
