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
from agentkernel.core.model import AgentReplyText, AgentRequestAny, BaseRunRequest, Principal, ScheduleSpec
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.model import ScheduledTask

FUTURE_AT = "2030-06-01T09:00:00"
PRINCIPAL = Principal(subject="u1", provider="static", namespace="static")
SOMEONE_ELSE = Principal(subject="someone-else", provider="static", namespace="static")


def _scheduled_request(**overrides) -> BaseRunRequest:
    fields = {"prompt": "send the weekly report", "session_id": "s1", "principal": PRINCIPAL, "schedule": ScheduleSpec(at=FUTURE_AT)}
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

    @pytest.mark.asyncio
    async def test_a_schedule_block_without_a_principal_is_a_403(self, manager, handler):
        """The manager's refusal is a PermissionError; the wrappers map it beside the 400, not to a 500 (#603)."""
        manager.create_from_request.side_effect = PermissionError("scheduling requires an authenticated principal")

        status_code, body = await ChatService().process_async_chat_request(_scheduled_request(principal=None))

        assert status_code == 403
        assert body["error"] == "scheduling requires an authenticated principal"

    def test_the_sync_wrapper_answers_403_too(self, manager, handler):
        manager.create_from_request.side_effect = PermissionError("scheduling requires an authenticated principal")

        status_code, body = ChatService().process_chat_request(_scheduled_request(principal=None))

        assert status_code == 403
        assert body["error"] == "scheduling requires an authenticated principal"


class TestUserIdIsRefusedBeforeAnySideEffect:
    """``_validate`` runs after scheduling and trigger recording, so the refusal has to sit ahead of both."""

    @pytest.mark.asyncio
    async def test_a_scheduled_request_carrying_user_id_creates_no_task(self, manager, handler):
        with pytest.raises(ValueError, match="user_id is not a request field"):
            await ChatService().execute(_scheduled_request(user_id="u-1"))

        manager.create_from_request.assert_not_called()

    def test_the_sync_path_creates_no_task_either(self, manager, handler):
        with pytest.raises(ValueError, match="user_id is not a request field"):
            ChatService().execute_sync(_scheduled_request(user_id="u-1"))

        manager.create_from_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_trigger_carrying_user_id_records_no_occurrence(self, manager, handler):
        request = BaseRunRequest(prompt="hi", session_id="s1", principal=PRINCIPAL, scheduled_task_id="t1", user_id="u-1")

        with pytest.raises(ValueError, match="user_id is not a request field"):
            await ChatService().execute(request)

        manager.record_trigger.assert_not_called()


class TestTriggerRecording:
    @pytest.fixture(autouse=True)
    def _an_agent_to_run_on(self, surface_agent):
        # The occurrence is asked the run's own question before it is recorded (#603), and that asks the registry.
        runtime = Runtime(InMemorySessionStore())
        runtime.register(surface_agent("reports"))
        with runtime:
            yield

    def _trigger_request(self, **overrides) -> BaseRunRequest:
        fields = {
            "prompt": "send the weekly report",
            "session_id": "s1",
            "principal": PRINCIPAL,
            "scheduled_task_id": "t1",
            "scheduled_time": "2030-06-01T09:00:00Z",
            "request_id": "r1",
        }
        fields.update(overrides)
        return BaseRunRequest(**fields)

    @pytest.mark.asyncio
    async def test_occurrence_is_recorded_and_the_request_runs(self, manager, handler):
        result, _ = await ChatService().execute(self._trigger_request())

        manager.record_trigger.assert_called_once_with("t1", PRINCIPAL, request_id="r1", occurred_at="2030-06-01T09:00:00Z")
        assert str(result) == "agent ran"

    @pytest.mark.asyncio
    async def test_the_principal_is_forwarded_so_the_manager_can_reject_a_foreign_task(self, manager, handler):
        """The trigger metadata rides on a client-bindable request, so ownership is the manager's call."""
        await ChatService().execute(self._trigger_request(principal=SOMEONE_ELSE))

        manager.record_trigger.assert_called_once_with("t1", SOMEONE_ELSE, request_id="r1", occurred_at="2030-06-01T09:00:00Z")

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


class TestAnOccurrenceTheOwnerMayNoLongerRun:
    """#603, iteration 19: an occurrence runs as the task's owner, long after the task was created, so the owner's
    access is checked again when it fires. One the owner may no longer run is recorded with the reason and
    skipped: the agent never runs, and the reply says so with a 403.

    Nothing below the service is mocked: a runtime hosting `reports` (private, granted to u1) and `status`
    (public, granted to nobody), the real access gate over a static policy, and a stubbed schedule manager to
    read what was recorded."""

    SKIPPED = "scheduled task skipped: the owner no longer holds access to the agent"
    OCCURRED_AT = "2030-06-01T09:00:00Z"

    @pytest.fixture
    def hosting(self, authorization, surface_agent):
        authorization(grants=[{"subjects": ["user:u1"], "agents": ["reports"], "level": "read"}])
        runtime = Runtime(InMemorySessionStore())
        runtime.register(surface_agent("reports"))
        status = surface_agent("status")
        status._set_descriptor(status.descriptor.model_copy(update={"visibility": "public"}))
        runtime.register(status)
        with runtime:
            yield runtime

    def _occurrence(self, agent="reports", principal=PRINCIPAL, **overrides) -> BaseRunRequest:
        fields = {
            "prompt": "send the weekly report",
            "session_id": "s1",
            "agent": agent,
            "principal": principal,
            "scheduled_task_id": "t1",
            "scheduled_time": self.OCCURRED_AT,
            "request_id": "r1",
        }
        fields.update(overrides)
        return BaseRunRequest(**fields)

    def test_an_occurrence_its_owner_may_run_runs_and_is_recorded_as_it_always_was(self, hosting, manager):
        result, _ = ChatService().execute_sync(self._occurrence())

        assert str(result) == "reports"
        manager.record_trigger.assert_called_once_with("t1", PRINCIPAL, request_id="r1", occurred_at=self.OCCURRED_AT)

    def test_an_owner_who_may_no_longer_see_the_agent_is_skipped(self, hosting, manager):
        store = hosting.sessions()
        with patch.object(store, "load", wraps=store.load) as load:
            result, session_id = ChatService().execute_sync(self._occurrence(principal=SOMEONE_ELSE))

        assert (str(result), session_id) == (self.SKIPPED, "s1")
        load.assert_not_called()  # the run never started
        manager.record_trigger.assert_called_once_with(
            "t1", SOMEONE_ELSE, request_id="r1", occurred_at=self.OCCURRED_AT, error="Agent 'reports' not found"
        )

    def test_an_owner_who_sees_the_agent_and_holds_no_level_is_skipped_too(self, hosting, manager):
        result, _ = ChatService().execute_sync(self._occurrence(agent="status"))

        assert str(result) == self.SKIPPED
        assert manager.record_trigger.call_args.kwargs["error"] == "Principal 'u1' holds no level on agent 'status'"

    def test_a_task_whose_agent_is_gone_is_skipped_as_well(self, hosting, manager):
        # A removed agent and one the owner may not see are one answer, here as on every route.
        result, _ = ChatService().execute_sync(self._occurrence(agent="retired"))

        assert str(result) == self.SKIPPED
        assert manager.record_trigger.call_args.kwargs["error"] == "Agent 'retired' not found"

    def test_a_task_kept_to_a_surface_its_agent_has_left_is_skipped(self, manager, surface_agent):
        # The surface the task was created over rides the trigger body; no authorization block is needed for it.
        runtime = Runtime(InMemorySessionStore())
        runtime.register(surface_agent("reports", ["a2a"]))

        with runtime:
            result, _ = ChatService().execute_sync(self._occurrence(surface="rest"))

        assert str(result) == self.SKIPPED
        assert manager.record_trigger.call_args.kwargs["error"] == "Agent 'reports' not found"

    def test_a_task_whose_agent_now_runs_in_another_process_is_skipped(self, manager, descriptor_only_registry):
        """The occurrence runs here, so the agent has to be hosted here: one the registry only knows from another
        process cannot be run by this one, and saying so is the skip, not an error after the record is written."""
        from agentkernel.core.model import AgentDescriptor

        registry = descriptor_only_registry([AgentDescriptor(id="reports", name="reports")])

        with Runtime(InMemorySessionStore(), registry=registry):
            status, body = ChatService().process_chat_request(self._occurrence())

        assert (status, body) == (403, {"result": self.SKIPPED, "session_id": "s1"})
        assert manager.record_trigger.call_args.kwargs["error"] == "Agent 'reports' not found"

    @pytest.mark.asyncio
    async def test_the_async_path_skips_it(self, hosting, manager):
        result, session_id = await ChatService().execute(self._occurrence(principal=SOMEONE_ELSE))

        assert (str(result), session_id) == (self.SKIPPED, "s1")
        manager.record_trigger.assert_called_once()

    def test_the_wrappers_answer_a_skipped_occurrence_with_a_403_and_the_reply(self, hosting, manager):
        status, body = ChatService().process_chat_request(self._occurrence(principal=SOMEONE_ELSE))

        # A reply, not an error body: the occurrence was handled, by not running it.
        assert (status, body) == (403, {"result": self.SKIPPED, "session_id": "s1"})

    @pytest.mark.asyncio
    async def test_the_async_wrapper_answers_the_same(self, hosting, manager):
        status, body = await ChatService().process_async_chat_request(self._occurrence(principal=SOMEONE_ELSE))

        assert (status, body) == (403, {"result": self.SKIPPED, "session_id": "s1"})

    @pytest.mark.asyncio
    async def test_in_rest_api_mode_the_403_is_on_the_response(self, hosting, manager):
        response = await ChatService(rest_api_mode=True).process_async_chat_request(self._occurrence(principal=SOMEONE_ELSE))

        assert isinstance(response, JSONResponse)
        assert (response.status_code, json.loads(response.body)) == (403, {"result": self.SKIPPED, "session_id": "s1"})

    def test_an_occurrence_that_runs_keeps_its_200(self, hosting, manager):
        assert ChatService().process_chat_request(self._occurrence()) == (200, {"result": "reports", "session_id": "s1"})

    def test_a_reply_that_reads_like_a_skip_is_not_one(self, hosting, manager):
        # The status follows what the service did, never the text an agent happened to answer with.
        request = self._occurrence()

        assert ChatService.success_status(request, AgentReplyText(response=self.SKIPPED)) == 200

    @pytest.mark.asyncio
    async def test_a_stream_is_one_error_chunk_and_never_opens_the_run(self, hosting, manager):
        chunks = [chunk async for chunk in await ChatService().execute_stream(self._occurrence(principal=SOMEONE_ELSE))]

        assert [(chunk.error, chunk.done, chunk.delta) for chunk in chunks] == [(self.SKIPPED, True, None)]
        manager.record_trigger.assert_called_once()

    def test_the_sync_stream_is_one_error_chunk_too(self, hosting, manager):
        # The queue runner's streaming path: raised instead, the refusal would be retried and recorded each time.
        chunks = list(ChatService().execute_stream_sync(self._occurrence(principal=SOMEONE_ELSE)))

        assert [(chunk.error, chunk.done) for chunk in chunks] == [(self.SKIPPED, True)]
        manager.record_trigger.assert_called_once()

    def test_one_warning_names_the_task(self, hosting, manager, caplog):
        with caplog.at_level("WARNING", logger="ak.chatservice"):
            ChatService().execute_sync(self._occurrence(principal=SOMEONE_ELSE))

        [warning] = [record.getMessage() for record in caplog.records if record.name == "ak.chatservice"]
        assert "t1" in warning and "Agent 'reports' not found" in warning

    def test_it_is_skipped_even_where_scheduling_is_not_configured(self, hosting, disabled_capability):
        # Nothing can be recorded here, and the owner may still not run the agent.
        result, _ = ChatService().execute_sync(self._occurrence(principal=SOMEONE_ELSE))

        assert str(result) == self.SKIPPED

    def test_a_store_that_cannot_take_the_record_does_not_turn_the_skip_into_a_run(self, hosting, manager):
        manager.record_trigger.side_effect = RuntimeError("store down")

        result, _ = ChatService().execute_sync(self._occurrence(principal=SOMEONE_ELSE))

        assert str(result) == self.SKIPPED

    def test_a_request_that_is_no_occurrence_is_refused_as_before(self, hosting, manager):
        # The skip is for a trigger. The same refusal on an ordinary request stays the surface's 404.
        status, body = ChatService().process_chat_request(BaseRunRequest(prompt="hi", session_id="s1", agent="reports", principal=SOMEONE_ELSE))

        assert (status, body) == (404, {"error": "Agent 'reports' not found", "session_id": "s1"})
        manager.record_trigger.assert_not_called()

    def test_an_occurrence_with_no_agent_to_default_to_is_recorded_with_that_and_answers_as_before(self, manager):
        """A task naming no agent whose default is gone, or one its owner may not see: there is no name to refuse,
        so the answer stays the 400 of any such request, and the record still says the occurrence did not run."""
        with Runtime(InMemorySessionStore()):
            status, body = ChatService().process_chat_request(self._occurrence(agent=None))

        assert (status, body) == (400, {"error": "No agent available", "session_id": "s1"})
        manager.record_trigger.assert_called_once_with("t1", PRINCIPAL, request_id="r1", occurred_at=self.OCCURRED_AT, error="No agent available")


class TestAdditionalContext:
    def test_scheduling_fields_never_reach_the_agent_as_context(self):
        # These are envelope concerns: the schedule is consumed before the run, and the trigger
        # metadata describes the occurrence rather than the user's request.
        req = BaseRunRequest(
            prompt="send the weekly report",
            session_id="s1",
            principal=PRINCIPAL,
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
