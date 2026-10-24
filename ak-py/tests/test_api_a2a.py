"""The A2A executor answers through the queue (#780 §3): one row per outcome the caller can see.

On a2a-sdk 1.x (#762) a failure is the raised error alone: an event enqueued before the raise is
never delivered, so the error's own message is what the caller reads.
"""

import json
import subprocess
import sys
import uuid
from unittest.mock import Mock

import pytest
from a2a.helpers import get_data_parts, get_message_text
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, SendMessageRequest, UnsupportedOperationError
from a2a.utils.errors import A2AError

from agentkernel.api.a2a.a2a import A2A
from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.model import AgentReplyAny, AgentReplyImage, AgentReplyText
from agentkernel.pipeline.request_client import QueuedReply, ReplyTimeoutError

AGENT = "triage"
A2UI = "application/a2ui+json"


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


class RecordingEventQueue(EventQueue):
    """The 1.x EventQueue is abstract; this one keeps what the executor enqueues, in order."""

    def __init__(self):
        self.events = []

    async def enqueue_event(self, event) -> None:
        self.events.append(event)


def _context(text="hello", task_id="task-1", context_id="ctx-1") -> RequestContext:
    message = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text=text)])
    return RequestContext(ServerCallContext(), request=SendMessageRequest(message=message), task_id=task_id, context_id=context_id)


async def _execute(client, context=None):
    """Run the executor and return (events, raised A2AError or None)."""
    A2A._client = client
    queue = RecordingEventQueue()
    raised = None
    try:
        await A2A.Executor(AGENT).execute(context or _context(), queue)
    except A2AError as e:
        raised = e
    return queue.events, raised


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
            await A2A.Executor(AGENT).execute(context, RecordingEventQueue())

        assert client.calls == []


class TestReplies:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "agent_reply, expected_text",
        [
            (AgentReplyText(response="4"), "4"),
            (AgentReplyImage(response="here it is", name="chart.png", image_data="aGk="), "here it is. Image chart.png is attached."),
            (AgentReplyAny(content={"a": 1}), '{"a": 1}'),
        ],
    )
    async def test_an_unlabelled_reply_is_one_text_message(self, agent_reply, expected_text):
        events, raised = await _execute(FakeClient(_queued(agent_reply)))

        assert raised is None
        [event] = events
        assert get_message_text(event) == expected_text
        assert (event.context_id, event.task_id) == ("ctx-1", "task-1")

    @pytest.mark.asyncio
    async def test_the_ids_are_not_mistaken_for_a_media_type(self):
        """1.x's text helper takes media_type second; a positional port would put the context id there."""
        events, _ = await _execute(FakeClient(_queued(AgentReplyText(response="4"))))

        [part] = events[0].parts
        assert part.media_type == ""
        assert (events[0].context_id, events[0].task_id) == ("ctx-1", "task-1")

    @pytest.mark.asyncio
    async def test_an_unlabelled_structured_reply_reads_as_the_json_the_old_path_gave(self):
        """D3: without a media type a structured reply stays JSON text, so a text-only client reads it."""
        reply = AgentReplyAny(content={"x": [1, 2]})

        events, _ = await _execute(FakeClient(_queued(reply)))

        assert json.loads(get_message_text(events[0])) == reply.content
        assert get_message_text(events[0]) == str(reply)


class TestDataParts:
    """A labelled structured reply is one data part, labelled where both A2A and A2UI clients look (#762)."""

    async def _part(self, agent_reply):
        events, raised = await _execute(FakeClient(_queued(agent_reply)))

        assert raised is None
        [event] = events
        assert (event.context_id, event.task_id) == ("ctx-1", "task-1")
        [part] = event.parts
        return part

    @pytest.mark.asyncio
    async def test_a_labelled_reply_is_a_data_part_labelled_twice(self):
        part = await self._part(AgentReplyAny(content=[{"b": "2"}], media_type=A2UI))

        assert part.HasField("data")
        assert part.media_type == A2UI
        assert dict(part.metadata) == {"mimeType": A2UI}
        assert get_data_parts([part]) == [[{"b": "2"}]]

    @pytest.mark.asyncio
    async def test_an_a2ui_object_goes_out_as_a_one_item_list(self):
        """The A2UI binding requires a list of messages in the data part."""
        part = await self._part(AgentReplyAny(content={"createSurface": {"surfaceId": "s1"}}, media_type=A2UI))

        assert get_data_parts([part]) == [[{"createSurface": {"surfaceId": "s1"}}]]

    @pytest.mark.asyncio
    async def test_another_media_type_keeps_its_object(self):
        """The executor maps any label; only A2UI's own rule wraps an object."""
        part = await self._part(AgentReplyAny(content={"k": "v"}, media_type="application/vnd.acme+json"))

        assert part.media_type == "application/vnd.acme+json"
        assert dict(part.metadata) == {"mimeType": "application/vnd.acme+json"}
        assert get_data_parts([part]) == [{"k": "v"}]

    @pytest.mark.asyncio
    async def test_numbers_arrive_as_doubles(self):
        """A data part carries a protobuf Struct, whose numbers are doubles: 1 arrives as 1.0."""
        part = await self._part(AgentReplyAny(content=[{"n": 1}], media_type=A2UI))

        [[item]] = get_data_parts([part])
        assert item["n"] == 1 and isinstance(item["n"], float)


class TestFailures:
    async def _assert_generic_failure(self, client, caplog, expected_message=A2A.Executor.ERROR_MESSAGE):
        events, raised = await _execute(client)

        assert events == []
        assert raised is not None
        assert raised.message == expected_message
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

        assert events == []
        assert raised.message == A2A.Executor.ERROR_MESSAGE

    @pytest.mark.asyncio
    async def test_cancel_is_still_unsupported(self):
        with pytest.raises(UnsupportedOperationError):
            await A2A.Executor(AGENT).cancel(_context(), RecordingEventQueue())


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
