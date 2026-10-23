"""The A2A executor answers through the queue (#780 §3): one row per outcome the caller can see."""

import json
import subprocess
import sys
import uuid
from unittest.mock import Mock

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, MessageSendParams, Part, Role, TextPart
from a2a.utils import get_message_text
from a2a.utils.errors import ServerError

from agentkernel.api.a2a.a2a import A2A
from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.model import AgentReplyAny, AgentReplyImage, AgentReplyText
from agentkernel.pipeline.request_client import QueuedReply, ReplyTimeoutError

AGENT = "triage"


@pytest.fixture(autouse=True)
def reset_a2a_state():
    """A2A keeps its cards, executors and client in class state; restore them so tests don't leak."""
    saved = (dict(A2A._cards), dict(A2A._executors), A2A._built, A2A._client)
    yield
    A2A._cards, A2A._executors, A2A._built, A2A._client = dict(saved[0]), dict(saved[1]), saved[2], saved[3]


class FakeClient:
    """Stands in for QueueRequestClient: records each request and answers with ``reply`` or raises ``raises``."""

    def __init__(self, reply=None, raises=None):
        self.reply = reply
        self.raises = raises
        self.calls = []

    async def request(self, body, protocol):
        self.calls.append((body, protocol))
        if self.raises is not None:
            raise self.raises
        return self.reply


def _queued(result, status_code=200) -> QueuedReply:
    """The reply a runner really stores: the body ResponseBuilder builds from an agent reply."""
    _status, body = ResponseBuilder.build_response(status_code, "ctx-1", rest_api_mode=False, result=result)
    return QueuedReply(request_id="r1", status_code=status_code, body=body)


def _context(text="hello", task_id="task-1", context_id="ctx-1") -> RequestContext:
    message = Message(message_id=str(uuid.uuid4()), role=Role.user, parts=[Part(root=TextPart(text=text))])
    return RequestContext(request=MessageSendParams(message=message), task_id=task_id, context_id=context_id)


async def _execute(client, context=None):
    """Run the executor and return (events, raised ServerError or None)."""
    A2A._client = client
    queue = EventQueue()
    raised = None
    try:
        await A2A.Executor(AGENT).execute(context or _context(), queue)
    except ServerError as e:
        raised = e
    events = []
    while not queue.queue.empty():
        events.append(await queue.dequeue_event(no_wait=True))
    return events, raised


class TestRequest:
    @pytest.mark.asyncio
    async def test_the_request_is_the_message_text_agent_and_context(self):
        client = FakeClient(_queued(AgentReplyText(response="hi")))

        await _execute(client, _context(text="what is 2+2", context_id="ctx-9"))

        [(body, protocol)] = client.calls
        assert (body.prompt, body.agent, body.session_id) == ("what is 2+2", AGENT, "ctx-9")
        assert protocol == "a2a" == A2A.PROTOCOL

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fields, message",
        [
            ({"task_id": None}, "task_id and context_id"),
            ({"context_id": None}, "task_id and context_id"),
            ({"message": None}, "must have a message"),
        ],
    )
    async def test_the_context_checks_still_fire_before_anything_is_sent(self, fields, message):
        # A real RequestContext generates missing ids, so the SDK never hands over one without them;
        # a spec'd mock is the only way to reach the executor's own checks.
        context = Mock(spec=RequestContext, **{"task_id": "task-1", "context_id": "ctx-1", "message": object(), **fields})
        client = FakeClient(_queued(AgentReplyText(response="hi")))
        A2A._client = client

        with pytest.raises(ValueError, match=message):
            await A2A.Executor(AGENT).execute(context, EventQueue())

        assert client.calls == []


class TestReplies:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "agent_reply, expected_text",
        [
            (AgentReplyText(response="4"), "4"),
            (AgentReplyImage(response="here it is", name="chart.png", image_data="aGk="), "here it is. Image chart.png is attached."),
            (AgentReplyAny(content={"a": 1}), '{"a": 1}'),
            (AgentReplyAny(content={"a": 1}, media_type="application/a2ui+json"), '{"a": 1}'),
            (AgentReplyAny(content=[{"b": 2}], media_type="application/a2ui+json"), '[{"b": 2}]'),
        ],
    )
    async def test_a_successful_reply_is_one_text_message(self, agent_reply, expected_text):
        events, raised = await _execute(FakeClient(_queued(agent_reply)))

        assert raised is None
        [event] = events
        assert get_message_text(event) == expected_text
        assert (event.context_id, event.task_id) == ("ctx-1", "task-1")

    @pytest.mark.asyncio
    async def test_a_structured_reply_reads_as_the_json_the_old_path_gave(self):
        reply = AgentReplyAny(content={"x": [1, 2]}, media_type="application/a2ui+json")

        events, _ = await _execute(FakeClient(_queued(reply)))

        assert json.loads(get_message_text(events[0])) == reply.content
        assert get_message_text(events[0]) == str(reply)


class TestFailures:
    async def _assert_generic_failure(self, client, caplog, expected_message="Internal error"):
        events, raised = await _execute(client)

        [event] = events
        assert get_message_text(event) == A2A.Executor.ERROR_MESSAGE
        assert raised is not None
        assert raised.error.message == expected_message
        return caplog.text

    @pytest.mark.asyncio
    async def test_an_error_status_sends_the_generic_message_and_logs_the_detail(self, caplog):
        reply = QueuedReply(request_id="r1", status_code=500, body={"error": "database password is hunter2"})

        logs = await self._assert_generic_failure(FakeClient(reply), caplog)

        assert "hunter2" in logs

    @pytest.mark.asyncio
    async def test_a_missing_result_is_a_failure(self, caplog):
        await self._assert_generic_failure(FakeClient(QueuedReply(request_id="r1", body={"session_id": "ctx-1"})), caplog)

    @pytest.mark.asyncio
    async def test_a_timeout_carries_the_fixed_timeout_message(self, caplog):
        logs = await self._assert_generic_failure(
            FakeClient(raises=ReplyTimeoutError("r9", 60, 1.0)), caplog, expected_message=A2A.Executor.TIMEOUT_MESSAGE
        )

        assert "request_id=r9" in logs

    @pytest.mark.asyncio
    async def test_any_other_exception_is_a_generic_failure(self, caplog):
        logs = await self._assert_generic_failure(FakeClient(raises=ConnectionError("broker at 10.0.0.5 refused")), caplog)

        assert "10.0.0.5" in logs

    @pytest.mark.asyncio
    async def test_an_empty_prompt_is_refused_by_the_client_as_a_generic_failure(self, caplog):
        """The real client validates before sending; the executor reports it like any other failure."""
        from agentkernel.pipeline.request_client import QueueRequestClient

        events, raised = await _execute(QueueRequestClient(transport=object(), response_store=object(), budget=(1, 0)), _context(text=""))

        assert get_message_text(events[0]) == A2A.Executor.ERROR_MESSAGE
        assert raised.error.message == "Internal error"

    @pytest.mark.asyncio
    async def test_cancel_is_still_unsupported(self):
        with pytest.raises(ServerError):
            await A2A.Executor(AGENT).cancel(_context(), EventQueue())


class TestClient:
    def test_the_client_is_built_once_and_reused(self, monkeypatch):
        from agentkernel.pipeline import request_client

        built = []

        class _Client:
            def __init__(self):
                built.append(self)

        monkeypatch.setattr(request_client, "QueueRequestClient", _Client)
        A2A._client = None

        assert A2A.get_client() is A2A.get_client()
        assert len(built) == 1

    def test_the_module_no_longer_runs_agents_itself(self):
        import agentkernel.api.a2a.a2a as module

        assert not hasattr(module, "AgentService")
        assert not hasattr(A2A.Executor, "_execute_agent")

    def test_importing_the_module_does_not_load_the_pipeline_client(self):
        code = "import sys, agentkernel.api.a2a.a2a; sys.exit('agentkernel.pipeline.request_client' in sys.modules)"
        assert subprocess.run([sys.executable, "-c", code]).returncode == 0
