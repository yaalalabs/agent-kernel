"""
The chat surface for pause and resume (spec `docs/specs/606-human-in-the-loop/`, iteration 3).

Nothing dispatches on a resume yet — this is the envelope: a request can carry decisions instead of
a prompt, and a paused reply comes back as 202 with a top-level discriminator a client can branch on
without parsing `result`. The `schedule` + `resume` test is the one that matters most, because it
catches a guard placed one layer too low.
"""

import json

import pytest
from pydantic import ValidationError

from agentkernel.core.chat_service import ChatService, RequestBuilder, ResponseBuilder
from agentkernel.core.event import PausedInterruption
from agentkernel.core.model import (
    AgentPausedReplyAny,
    AgentReplyText,
    AgentRequestText,
    AgentResumeRequestAny,
    BaseChatRequest,
    BaseRunRequest,
    ResumeDecision,
    ResumeSpec,
    ScheduleSpec,
)


def _resume(**kwargs) -> ResumeSpec:
    return ResumeSpec(decisions=kwargs.pop("decisions", [ResumeDecision(id="i1", status="approved")]), **kwargs)


def _paused_reply() -> AgentPausedReplyAny:
    return AgentPausedReplyAny(
        run_id="run-1",
        session_id="sess-1",
        agent="refunds",
        interruptions=[PausedInterruption(id="i1", kind="tool_call", tool_name="refund")],
    )


class TestRequestShape:
    def test_a_resume_only_request_needs_no_prompt(self):
        """The public model change: prompt is no longer required, so a decision can stand alone."""
        req = BaseChatRequest(session_id="s1", resume=_resume())
        assert req.prompt == ""

    def test_an_explicitly_empty_prompt_with_no_resume_is_still_rejected(self):
        """What ChatService still owns: the key is there, the turn is empty."""
        with pytest.raises(ValueError, match="No prompt provided in the request"):
            ChatService._validate(BaseChatRequest(session_id="s1", prompt=""), None)

    def test_a_body_carrying_neither_key_is_rejected_by_the_model(self):
        """Earlier than ChatService, and deliberately so: a queue consumer spots a poison message by
        `model_validate` raising, which is what drives retry -> max_receive_count -> dead-letter."""
        with pytest.raises(ValidationError, match="must carry a 'prompt'"):
            BaseChatRequest(session_id="s1")

    def test_a_resume_only_request_validates(self):
        ChatService._validate(BaseChatRequest(session_id="s1", resume=_resume()), None)

    def test_session_id_is_still_required(self):
        with pytest.raises(ValueError, match="No session_id"):
            ChatService._validate(BaseChatRequest(resume=_resume()), None)


class TestRequestBuilding:
    def test_decisions_become_a_resume_request(self):
        requests = RequestBuilder.from_base_request_sync(BaseRunRequest(session_id="s1", resume=_resume()))

        assert len(requests) == 1
        assert isinstance(requests[0], AgentResumeRequestAny)
        assert requests[0].decisions[0].id == "i1"

    def test_no_empty_text_request_is_built_for_a_resume_only_request(self):
        """An empty AgentRequestText would reach the adapter as a blank prompt."""
        requests = RequestBuilder.from_base_request_sync(BaseRunRequest(session_id="s1", resume=_resume()))

        assert not any(isinstance(r, AgentRequestText) for r in requests)

    def test_a_prompt_sent_alongside_a_decision_stays_first(self):
        requests = RequestBuilder.from_base_request_sync(BaseRunRequest(session_id="s1", prompt="and the weather?", resume=_resume()))

        assert isinstance(requests[0], AgentRequestText)
        assert isinstance(requests[-1], AgentResumeRequestAny)

    def test_an_ordinary_request_is_unchanged(self):
        requests = RequestBuilder.from_base_request_sync(BaseRunRequest(session_id="s1", prompt="hello"))

        assert len(requests) == 1
        assert isinstance(requests[0], AgentRequestText)

    def test_resume_never_reaches_the_agent_as_context(self):
        """Like `schedule`, the block is consumed by the runner and is not the user's request."""
        requests = RequestBuilder.from_base_request_sync(BaseRunRequest(session_id="s1", prompt="hi", resume=_resume()))

        assert not any(getattr(r, "name", None) == "resume" for r in requests)


class TestAmbiguousCombinations:
    def test_schedule_plus_resume_is_rejected(self):
        req = BaseChatRequest(session_id="s1", prompt="later", schedule=ScheduleSpec(at="2030-01-01T00:00:00"), resume=_resume())

        with pytest.raises(ValueError, match="cannot carry both 'schedule' and 'resume'"):
            ChatService._reject_ambiguous(req)

    @pytest.mark.parametrize("entry_point", ["execute", "execute_sync", "execute_stream", "execute_stream_sync"])
    def test_the_guard_runs_before_scheduling_on_every_entry_point(self, entry_point):
        """A guard placed in _validate never fires: _maybe_schedule has already returned its 202.

        Asserting the source order rather than driving each entry point, because reaching
        _validate needs a configured agent and session that this iteration does not wire up.
        """
        import inspect

        body = inspect.getsource(getattr(ChatService, entry_point))
        assert body.index("_reject_ambiguous") < body.index("_maybe_schedule")

    def test_prompt_plus_resume_is_allowed(self):
        """Not blocked: three of the four frameworks carry new content beside a decision."""
        ChatService._reject_ambiguous(BaseChatRequest(session_id="s1", prompt="and the weather?", resume=_resume()))


class TestPausedResponse:
    def test_a_paused_reply_carries_202(self):
        assert ChatService.success_status(BaseChatRequest(session_id="s1", prompt=""), _paused_reply()) == 202

    def test_an_ordinary_reply_carries_200(self):
        assert ChatService.success_status(BaseChatRequest(session_id="s1", prompt=""), AgentReplyText(response="hi")) == 200

    def test_a_deferred_request_still_carries_202(self):
        req = BaseChatRequest(session_id="s1", prompt="later", schedule=ScheduleSpec(at="2030-01-01T00:00:00"))
        assert ChatService.success_status(req) == 202

    def test_the_body_carries_a_top_level_discriminator(self):
        body = ResponseBuilder.build_response(202, "sess-1", rest_api_mode=False, result=_paused_reply())[1]

        assert body["status"] == "PAUSED"
        assert body["run_id"] == "run-1"
        assert [i["id"] for i in body["interruptions"]] == ["i1"]

    def test_the_body_names_the_agent_that_paused(self):
        """A resume must name that agent, and a request that named none was served by the default."""
        body = ResponseBuilder.build_response(202, "sess-1", rest_api_mode=False, result=_paused_reply())[1]

        assert body["agent"] == "refunds"

    def test_the_result_key_still_renders_the_reply(self):
        body = ResponseBuilder.build_response(202, "sess-1", rest_api_mode=False, result=_paused_reply())[1]

        assert json.loads(body["result"])["agent"] == "refunds"

    def test_an_ordinary_reply_gains_no_discriminator(self):
        body = ResponseBuilder.build_response(200, "sess-1", rest_api_mode=False, result=AgentReplyText(response="hi"))[1]

        assert "status" not in body

    def test_paused_is_distinguishable_from_scheduled(self):
        """202 now means two things; the body key is what separates them."""
        from agentkernel.core.model import AgentReplyAny

        scheduled = ResponseBuilder.build_response(
            202, "sess-1", rest_api_mode=False, result=AgentReplyAny(content={"status": "SCHEDULED", "scheduled_task_id": "t1"})
        )[1]
        paused = ResponseBuilder.build_response(202, "sess-1", rest_api_mode=False, result=_paused_reply())[1]

        assert "status" not in scheduled
        assert paused["status"] == "PAUSED"


class TestAsyncRequestBuilding:
    """
    The async builder is what every REST, streaming and thread request goes through.

    Mirrors TestRequestBuilding on purpose: the two builders diverged once — `_add_resume` was
    added to the sync one alone — and a resume-only request here built an empty list that failed
    validation as "No requests provided", making the feature unusable everywhere but the sync path.
    """

    @pytest.mark.asyncio
    async def test_decisions_become_a_resume_request(self):
        requests = await RequestBuilder.from_base_request_async(BaseRunRequest(session_id="s1", resume=_resume()))

        assert len(requests) == 1
        assert isinstance(requests[0], AgentResumeRequestAny)
        assert requests[0].decisions[0].id == "i1"

    @pytest.mark.asyncio
    async def test_a_multipart_style_request_also_carries_the_decisions(self):
        """The other branch: a request that is not a BaseRunRequest takes the async attachment path."""
        requests = await RequestBuilder.from_base_request_async(BaseChatRequest(session_id="s1", resume=_resume()))

        assert [type(r) for r in requests] == [AgentResumeRequestAny]

    @pytest.mark.asyncio
    async def test_a_prompt_sent_alongside_a_decision_stays_first(self):
        requests = await RequestBuilder.from_base_request_async(BaseRunRequest(session_id="s1", prompt="and the weather?", resume=_resume()))

        assert isinstance(requests[0], AgentRequestText)
        assert isinstance(requests[-1], AgentResumeRequestAny)

    @pytest.mark.asyncio
    async def test_an_ordinary_request_is_unchanged(self):
        requests = await RequestBuilder.from_base_request_async(BaseRunRequest(session_id="s1", prompt="hello"))

        assert [type(r) for r in requests] == [AgentRequestText]

    @pytest.mark.asyncio
    async def test_a_resume_only_request_survives_the_whole_chat_service(self):
        """End to end past validation, which is where the empty list actually failed."""
        from unittest.mock import AsyncMock, MagicMock, patch

        handler = MagicMock()
        handler.get_response_session_id.side_effect = lambda sid: sid
        handler.run_async = AsyncMock(return_value=AgentReplyText(response="resumed"))

        with patch("agentkernel.core.chat_service.AgentHandler", return_value=handler):
            result, _ = await ChatService().execute(BaseRunRequest(session_id="s1", agent="a1", resume=_resume()))

        assert result.response == "resumed"
        assert any(isinstance(r, AgentResumeRequestAny) for r in handler.run_async.call_args.args[0])
