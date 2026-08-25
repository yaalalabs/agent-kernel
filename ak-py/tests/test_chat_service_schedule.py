"""ChatService interception of scheduled requests (#629 Phase 3).

Every chat surface funnels through ChatService, so the interception is pinned on all four
execution-core entry points plus the two process wrappers: a request carrying a schedule block is
registered and acknowledged with 202 instead of reaching an agent, and a request carrying trigger
metadata records its occurrence and then runs normally.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

from agentkernel.core.chat_service import ChatService, RequestBuilder
from agentkernel.core.model import AgentReplyText, AgentRequestAny, BaseRunRequest, ScheduleSpec
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.model import ScheduledTask

FUTURE_AT = "2030-06-01T09:00:00"


def _scheduled_request(**overrides) -> BaseRunRequest:
    fields = {"prompt": "send the weekly report", "session_id": "s1", "user_id": "u1", "schedule": ScheduleSpec(at=FUTURE_AT)}
    fields.update(overrides)
    return BaseRunRequest(**fields)


def _task(task_id: str = "t1") -> ScheduledTask:
    return ScheduledTask(
        task_id=task_id,
        user_id="u1",
        prompt="send the weekly report",
        session_id="s1",
        spec=ScheduleSpec(at=FUTURE_AT),
        created_at="2030-01-01T00:00:00+00:00",
        updated_at="2030-01-01T00:00:00+00:00",
    )


@pytest.fixture
def manager():
    """A stubbed ScheduleManager standing in for the configured capability."""
    stub = MagicMock(spec=ScheduleManager)
    stub.create_from_request.return_value = _task()
    with patch.object(ScheduleManager, "get", classmethod(lambda cls: stub)):
        yield stub


@pytest.fixture
def disabled_capability():
    with patch.object(ScheduleManager, "get", classmethod(lambda cls: None)):
        yield


@pytest.fixture
def handler():
    """A mocked AgentHandler that fails the test if the request ever reaches an agent."""
    mocked = MagicMock()
    mocked.get_response_session_id.side_effect = lambda session_id: session_id
    mocked.run_async = AsyncMock(return_value=AgentReplyText(response="agent ran"))
    mocked.run_sync.return_value = AgentReplyText(response="agent ran")
    with patch("agentkernel.core.chat_service.AgentHandler", return_value=mocked):
        yield mocked


def _ack_content(result) -> dict:
    return json.loads(str(result))


class TestInterception:
    @pytest.mark.asyncio
    async def test_execute_defers_instead_of_running(self, manager, handler):
        result, session_id = await ChatService().execute(_scheduled_request())

        assert _ack_content(result) == {"status": "SCHEDULED", "scheduled_task_id": "t1", "session_id": "s1"}
        assert session_id == "s1"
        handler.run_async.assert_not_called()
        manager.create_from_request.assert_called_once()

    def test_execute_sync_defers_instead_of_running(self, manager, handler):
        result, session_id = ChatService().execute_sync(_scheduled_request())

        assert _ack_content(result)["status"] == "SCHEDULED"
        assert session_id == "s1"
        handler.run_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_stream_yields_one_terminal_chunk(self, manager, handler):
        chunks = [chunk async for chunk in await ChatService().execute_stream(_scheduled_request())]

        assert len(chunks) == 1
        assert chunks[0].done is True
        # An acknowledgement, not a failure: the request was deferred as asked.
        assert chunks[0].error is None
        assert _ack_content(chunks[0].delta)["scheduled_task_id"] == "t1"
        handler.run_stream_async.assert_not_called()

    def test_execute_stream_sync_yields_one_terminal_chunk(self, manager, handler):
        chunks = list(ChatService().execute_stream_sync(_scheduled_request()))

        assert len(chunks) == 1
        assert chunks[0].done is True
        assert chunks[0].error is None
        handler.run_stream_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_unscheduled_request_still_runs(self, manager, handler):
        result, _ = await ChatService().execute(BaseRunRequest(prompt="hi", session_id="s1"))

        assert str(result) == "agent ran"
        manager.create_from_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_schedule_block_without_the_capability_is_a_validation_error(self, disabled_capability, handler):
        with pytest.raises(ValueError, match="Scheduling is not configured"):
            await ChatService().execute(_scheduled_request())

    @pytest.mark.asyncio
    async def test_interception_precedes_agent_selection(self, manager, handler):
        # The schedule is registered even when the request names no agent, so a deferred request
        # never depends on an agent being resolvable at creation time.
        await ChatService().execute(_scheduled_request(agent=None))

        handler.initialize.assert_not_called()


class TestStatusPlumbing:
    def test_sync_wrapper_returns_202_for_a_deferred_request(self, manager, handler):
        status_code, body = ChatService().process_chat_request(_scheduled_request())

        assert status_code == 202
        assert json.loads(body["result"])["scheduled_task_id"] == "t1"
        assert body["session_id"] == "s1"

    def test_sync_wrapper_still_returns_200_for_a_normal_request(self, manager, handler):
        status_code, _ = ChatService().process_chat_request(BaseRunRequest(prompt="hi", session_id="s1"))

        assert status_code == 200

    @pytest.mark.asyncio
    async def test_async_wrapper_returns_202_for_a_deferred_request(self, manager, handler):
        status_code, body = await ChatService().process_async_chat_request(_scheduled_request())

        assert status_code == 202
        assert json.loads(body["result"])["status"] == "SCHEDULED"

    @pytest.mark.asyncio
    async def test_rest_api_mode_carries_the_202_on_the_response(self, manager, handler):
        response = await ChatService(rest_api_mode=True).process_async_chat_request(_scheduled_request())

        assert isinstance(response, JSONResponse)
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_rest_api_mode_returns_a_plain_dict_for_a_normal_request(self, manager, handler):
        response = await ChatService(rest_api_mode=True).process_async_chat_request(BaseRunRequest(prompt="hi", session_id="s1"))

        assert isinstance(response, dict)
        assert response["result"] == "agent ran"

    @pytest.mark.asyncio
    async def test_unusable_schedule_is_reported_as_a_400(self, manager, handler):
        manager.create_from_request.side_effect = ValueError("schedule 'at' must be in the future")

        status_code, body = await ChatService().process_async_chat_request(_scheduled_request())

        assert status_code == 400
        assert "must be in the future" in body["error"]


class TestTriggerRecording:
    def _trigger_request(self, **overrides) -> BaseRunRequest:
        fields = {
            "prompt": "send the weekly report",
            "session_id": "s1",
            "user_id": "u1",
            "scheduled_task_id": "t1",
            "scheduled_time": "2030-06-01T09:00:00Z",
            "request_id": "r1",
        }
        fields.update(overrides)
        return BaseRunRequest(**fields)

    @pytest.mark.asyncio
    async def test_occurrence_is_recorded_and_the_request_runs(self, manager, handler):
        result, _ = await ChatService().execute(self._trigger_request())

        manager.record_trigger.assert_called_once_with("t1", "u1", request_id="r1", occurred_at="2030-06-01T09:00:00Z")
        assert str(result) == "agent ran"

    @pytest.mark.asyncio
    async def test_the_acting_user_is_forwarded_so_the_manager_can_reject_a_foreign_task(self, manager, handler):
        """The trigger metadata rides on a client-bindable request, so ownership is the manager's call."""
        await ChatService().execute(self._trigger_request(user_id="someone-else"))

        manager.record_trigger.assert_called_once_with("t1", "someone-else", request_id="r1", occurred_at="2030-06-01T09:00:00Z")

    def test_occurrence_is_recorded_on_the_sync_path(self, manager, handler):
        ChatService().execute_sync(self._trigger_request())

        manager.record_trigger.assert_called_once()

    @pytest.mark.asyncio
    async def test_recording_failure_does_not_fail_the_run(self, manager, handler):
        manager.record_trigger.side_effect = RuntimeError("store down")

        result, _ = await ChatService().execute(self._trigger_request())

        assert str(result) == "agent ran"

    @pytest.mark.asyncio
    async def test_trigger_arriving_without_the_capability_still_runs(self, disabled_capability, handler):
        result, _ = await ChatService().execute(self._trigger_request())

        assert str(result) == "agent ran"

    @pytest.mark.asyncio
    async def test_request_without_trigger_metadata_records_nothing(self, manager, handler):
        await ChatService().execute(BaseRunRequest(prompt="hi", session_id="s1"))

        manager.record_trigger.assert_not_called()


class TestAdditionalContext:
    def test_scheduling_fields_never_reach_the_agent_as_context(self):
        # These are envelope concerns: the schedule is consumed before the run, and the trigger
        # metadata describes the occurrence rather than the user's request.
        req = BaseRunRequest(
            prompt="send the weekly report",
            session_id="s1",
            user_id="u1",
            schedule=ScheduleSpec(at=FUTURE_AT),
            scheduled_task_id="t1",
            scheduled_time="2030-06-01T09:00:00Z",
        )

        requests = RequestBuilder.from_base_request_sync(req)

        leaked = [request.name for request in requests if isinstance(request, AgentRequestAny)]
        assert leaked == []

    def test_unknown_fields_are_still_passed_as_context(self):
        req = BaseRunRequest.model_validate({"prompt": "hi", "session_id": "s1", "tenant": "acme"})

        requests = RequestBuilder.from_base_request_sync(req)

        assert [request.name for request in requests if isinstance(request, AgentRequestAny)] == ["tenant"]
