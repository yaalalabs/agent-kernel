import datetime
import decimal
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText, BaseRunRequest, ScheduleSpec, StreamChunk
from agentkernel.core.runtime import Runtime
from agentkernel.integration.thread import (
    AgentThreadRequestHandler,
    ConversationThreadManager,
    ThreadAttachment,
    ThreadMessage,
    ThreadNamingStrategy,
    ThreadRecorder,
)
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore

MEDIA_TYPE = "application/a2ui+json"


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
    AKConfig.get().thread = _ThreadStoreConfig(type="in_memory")
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

        manager.append_message.assert_called_once_with("s1", "assistant", "agent says hi", media_type=None)


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
    async def test_scheduled_request_is_acknowledged_without_recording(self, thread_enabled, registered_agent):
        # A deferred request is not a conversation turn: the thread and its messages belong to the
        # occurrence that eventually runs, so nothing is recorded at creation time.
        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService(reply=AgentReplyAny(content={"status": "SCHEDULED", "scheduled_task_id": "t1", "session_id": "s1"}))
        req = BaseRunRequest(
            prompt="send the weekly report",
            session_id="s1",
            user_id="u1",
            agent=registered_agent.name,
            schedule=ScheduleSpec(at="2030-06-01T09:00:00"),
        )

        response = await handler._run_with_recording(req)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 202
        assert thread_enabled.get_thread("s1") is None
        # Called without prebuilt requests: the recorder's pre_run never ran.
        assert handler.chat_service.calls[0][1] is None

    @pytest.mark.asyncio
    async def test_scheduled_stream_frames_the_acknowledgement_without_recording(self, thread_enabled, registered_agent):
        handler = AgentThreadRequestHandler()
        ack = AgentReplyAny(content={"status": "SCHEDULED", "scheduled_task_id": "t1", "session_id": "s1"})
        handler.chat_service = FakeChatService(chunks=[StreamChunk(delta=str(ack), done=True)])
        req = BaseRunRequest(
            prompt="send the weekly report",
            session_id="s1",
            user_id="u1",
            agent=registered_agent.name,
            schedule=ScheduleSpec(at="2030-06-01T09:00:00"),
        )

        frames = [frame async for frame in await handler._stream_with_recording(req)]

        assert len(frames) == 1
        assert "SCHEDULED" in frames[0]
        assert thread_enabled.get_thread("s1") is None

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

    def test_a_labelled_reply_replays_as_an_object_with_its_label(self, thread_enabled, registered_agent):
        """The whole point of #763: what rendered live must render again on reload.

        Both messages go into one thread deliberately — the unlabelled one is the guarantee that an
        application which never opted into A2UI reads exactly what it read before.
        """
        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService(reply=AgentReplyAny(content={"version": "v1.0"}, media_type=MEDIA_TYPE))
        app = FastAPI()
        app.include_router(handler.get_router())
        client = TestClient(app)
        chat = {"session_id": "s-label", "user_id": "alice", "agent": registered_agent.name}

        assert client.post("/api/v1/chat", json={**chat, "prompt": "show me the form"}).status_code == 200
        handler.chat_service = FakeChatService(reply=AgentReplyText(response="plain words"))
        assert client.post("/api/v1/chat", json={**chat, "prompt": "and in words"}).status_code == 200

        messages = client.get("/api/v1/threads/s-label").json()["messages"]
        labelled, unlabelled = messages[1], messages[3]

        assert labelled["content"] == {"version": "v1.0"}
        assert labelled["media_type"] == MEDIA_TYPE
        assert unlabelled["content"] == "plain words"
        assert "media_type" not in unlabelled


class TestThreadMessageShape:
    """What ``ThreadMessage`` accepts, refuses, and puts on the wire (#763).

    The union is the part worth pinning rather than trusting: ``Union[str, JSONPayload]`` leans on
    pydantic's smart union to keep a string a string, and a reply whose text happens to look like
    JSON is exactly the value that would be wrong to promote to an object.
    """

    def test_text_content_stays_text(self):
        assert ThreadMessage(role="assistant", content="hello").content == "hello"

    def test_a_json_looking_string_is_not_promoted_to_an_object(self):
        message = ThreadMessage(role="assistant", content='{"a": 1}')

        assert message.content == '{"a": 1}'
        assert message.media_type is None

    def test_object_content_is_normalised_like_a_reply(self):
        """The same normalisation ``AgentReplyAny.content`` runs, so neither store holds a datetime."""
        raw = {"submittedAt": datetime.datetime(2026, 9, 22, 14, 30), "amount": decimal.Decimal("250.00")}

        message = ThreadMessage(role="assistant", content=raw, media_type=MEDIA_TYPE)

        assert message.content == AgentReplyAny(content=raw).content
        assert message.content == {"submittedAt": "2026-09-22T14:30:00", "amount": "250.00"}

    def test_a_scalar_is_refused(self):
        with pytest.raises(ValidationError):
            ThreadMessage(role="assistant", content=42)

    def test_an_object_without_a_label_is_refused(self):
        with pytest.raises(ValidationError, match="media_type is unset"):
            ThreadMessage(role="assistant", content={"a": 1})

    def test_a_label_over_text_is_refused(self):
        with pytest.raises(ValidationError, match="content is text"):
            ThreadMessage(role="assistant", content="hello", media_type=MEDIA_TYPE)

    def test_a_blank_label_over_text_is_no_label(self):
        """Every other layer reads a blank label as unlabelled; the wire form must not disagree."""
        message = ThreadMessage(role="assistant", content="plain text", media_type="")

        assert message.media_type is None
        assert "media_type" not in message.to_wire()

    def test_a_whitespace_only_label_is_no_label(self):
        assert ThreadMessage(role="assistant", content="plain text", media_type="   ").media_type is None

    def test_an_object_with_a_blank_label_is_refused(self):
        with pytest.raises(ValidationError, match="media_type is unset"):
            ThreadMessage(role="assistant", content={"a": 1}, media_type="")

    def test_a_row_written_before_the_field_existed_still_reads(self):
        message = ThreadMessage.model_validate_json('{"message_id": "m1", "role": "assistant", "content": "hi"}')

        assert (message.content, message.media_type) == ("hi", None)

    def test_the_wire_form_omits_an_unset_label(self):
        wire = ThreadMessage(role="assistant", content="hello").to_wire()

        assert "media_type" not in wire
        assert wire["content"] == "hello"

    def test_the_wire_form_carries_a_set_label(self):
        wire = ThreadMessage(role="assistant", content={"a": 1}, media_type=MEDIA_TYPE).to_wire()

        assert wire["media_type"] == MEDIA_TYPE
        assert wire["content"] == {"a": 1}

    def test_the_wire_form_keeps_an_attachments_unset_fields(self):
        """The regression guard for excluding a named field rather than ``exclude_none``, which recurses."""
        attachment = ThreadAttachment(attachment_id="a1")

        wire = ThreadMessage(role="assistant", content="hello", attachments=[attachment]).to_wire()

        assert wire["attachments"] == [{"attachment_id": "a1", "name": None, "mime_type": None}]


class TestThreadContentEncoding:
    """Both recording paths must store the same content and label for the same reply.

    ``ThreadRecorder.post_run`` is called with three different types — an ``AgentReply`` from the
    direct handler, the accumulated text from the streaming one, and the response body's ``result``
    value from the queue runner, which for a labelled reply is a dict.
    """

    def test_a_labelled_reply_records_the_object_and_its_label(self):
        """The direct handler's shape: the reply carries its own label."""
        reply = AgentReplyAny(content={"a": 1}, media_type=MEDIA_TYPE)

        assert ThreadRecorder._as_thread_message(reply) == ({"a": 1}, MEDIA_TYPE)

    def test_a_labelled_queue_body_records_the_object_and_its_label(self):
        """The queue runner's shape: the label arrives beside the result, not on it."""
        assert ThreadRecorder._as_thread_message({"a": 1}, MEDIA_TYPE) == ({"a": 1}, MEDIA_TYPE)

    def test_an_unlabelled_agent_reply_records_json(self):
        """The label is the switch: without one, a structured reply is still text."""
        assert ThreadRecorder._as_thread_message(AgentReplyAny(content={"a": 1})) == ('{"a": 1}', None)

    def test_text_reply_records_its_text(self):
        assert ThreadRecorder._as_thread_message(AgentReplyText(response="hello")) == ("hello", None)

    def test_accumulated_stream_text_passes_through(self):
        assert ThreadRecorder._as_thread_message("hel" + "lo") == ("hello", None)

    def test_an_unlabelled_dict_records_json_not_a_python_repr(self):
        content, label = ThreadRecorder._as_thread_message({"root": None, "ok": True})

        assert (content, label) == ('{"root": null, "ok": true}', None)
        assert "'" not in content
        assert "None" not in content

    def test_both_paths_record_the_same_pair(self):
        """The queue path and the direct path hold different types for the same reply."""
        content = {"version": "v1.0", "createSurface": {"surfaceId": "s1"}}
        reply = AgentReplyAny(content=content, media_type=MEDIA_TYPE)

        assert ThreadRecorder._as_thread_message(reply) == ThreadRecorder._as_thread_message(content, MEDIA_TYPE) == (content, MEDIA_TYPE)


class TestThreadPauseAndResume:
    """
    The thread routes carry a pause like every other surface (issue #606).

    Both defects here came from the same widening: `prompt` became optional so a decision can stand
    alone, and this file held a second promptless guard and a hard-coded 200 that no one revisited.
    """

    @pytest.mark.asyncio
    async def test_a_paused_reply_is_acknowledged_with_202(self, thread_enabled, registered_agent):
        from agentkernel.core.event import PausedInterruption
        from agentkernel.core.model import AgentPausedReplyAny

        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService(
            reply=AgentPausedReplyAny(
                run_id="run-1",
                session_id="s1",
                agent=registered_agent.name,
                interruptions=[PausedInterruption(id="i1", kind="tool_call", tool_name="refund")],
            )
        )
        req = BaseRunRequest(prompt="refund it", session_id="s1", user_id="u1", agent=registered_agent.name)

        response = await handler._run_with_recording(req)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_a_resume_only_request_is_not_rejected_for_having_no_prompt(self, thread_enabled, registered_agent):
        from agentkernel.core.model import ResumeDecision, ResumeSpec

        handler = AgentThreadRequestHandler()
        handler.chat_service = FakeChatService()
        req = BaseRunRequest(
            session_id="s1",
            user_id="u1",
            agent=registered_agent.name,
            resume=ResumeSpec(decisions=[ResumeDecision(id="i1", status="approved")]),
        )

        body = await handler._run_with_recording(req)

        assert body["result"] == "agent says hi"

    @pytest.mark.asyncio
    async def test_the_queue_route_accepts_a_resume_without_a_prompt(self, thread_enabled, registered_agent):
        """The second guard, in the queue-mode handler — the one the first fix missed."""
        from unittest.mock import AsyncMock, patch

        from agentkernel.core.model import ResumeDecision, ResumeSpec
        from agentkernel.integration.thread.thread_chat import ThreadRequestHandler
        from agentkernel.pipeline.request_handler import RequestHandler

        handler = ThreadRequestHandler()
        req = BaseRunRequest(
            session_id="s1",
            user_id="u1",
            agent=registered_agent.name,
            resume=ResumeSpec(decisions=[ResumeDecision(id="i1", status="approved")]),
        )

        with (
            patch.object(ThreadRequestHandler, "_reject_unroutable"),
            patch.object(ThreadRequestHandler, "_record_user_message", AsyncMock()),
            patch.object(RequestHandler, "run_chat", AsyncMock(return_value={"accepted": True})),
        ):
            assert await handler.run_chat(req) == {"accepted": True}

    @pytest.mark.asyncio
    async def test_the_queue_route_still_rejects_a_request_carrying_neither(self, thread_enabled, registered_agent):
        from agentkernel.integration.thread.thread_chat import ThreadRequestHandler

        handler = ThreadRequestHandler()

        with pytest.raises(HTTPException) as exc:
            await handler.run_chat(BaseRunRequest(session_id="s1", user_id="u1", agent=registered_agent.name, prompt=""))

        assert exc.value.status_code == 400
        assert "No prompt provided" in exc.value.detail["error"]
