"""
The human-in-the-loop vocabulary (spec `docs/specs/606-human-in-the-loop/`, iteration 1).

These types carry a pause out to a client and a decision back in. Two properties are load-bearing
and are what most of this file pins: `AgentPausedReplyAny` must satisfy `isinstance(x,
AgentReplyAny)` so the reply union and every existing tuple check keep working untouched, and its
`content` must be derived from the typed fields so a surface that only understands `AgentReplyAny`
still renders something useful.
"""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from agentkernel.core.base import Runner
from agentkernel.core.event import PausedInterruption, RunPaused, StreamEvent
from agentkernel.core.model import (
    AgentPausedReplyAny,
    AgentReplyAny,
    AgentRequest,
    AgentResumeRequestAny,
    ResumeDecision,
    ResumeSpec,
)


def _interruption(id_: str = "i1", **kwargs) -> PausedInterruption:
    return PausedInterruption(id=id_, kind=kwargs.pop("kind", "tool_call"), **kwargs)


def _paused_reply(**kwargs) -> AgentPausedReplyAny:
    return AgentPausedReplyAny(
        run_id=kwargs.pop("run_id", "run-1"),
        session_id=kwargs.pop("session_id", "sess-1"),
        agent=kwargs.pop("agent", "refunds"),
        interruptions=kwargs.pop("interruptions", [_interruption()]),
        **kwargs,
    )


class TestRoundTrips:
    """Every new type survives model_dump -> model_validate unchanged."""

    def test_paused_interruption_round_trips(self):
        original = _interruption(tool_name="refund", arguments=json.dumps({"amount": 100}), message="approve?", payload={"options": ["a", "b"]})
        assert PausedInterruption.model_validate(original.model_dump()) == original

    def test_resume_decision_round_trips(self):
        original = ResumeDecision(id="i1", status="approved", message="confirmed damaged", payload={"choice": "damaged"})
        assert ResumeDecision.model_validate(original.model_dump()) == original

    def test_resume_spec_round_trips(self):
        original = ResumeSpec(run_id="run-1", decisions=[ResumeDecision(id="i1", status="denied")])
        assert ResumeSpec.model_validate(original.model_dump()) == original

    def test_resume_request_round_trips(self):
        original = AgentResumeRequestAny(decisions=[ResumeDecision(id="i1")])
        assert AgentResumeRequestAny.model_validate(original.model_dump()) == original

    def test_paused_reply_round_trips(self):
        original = _paused_reply()
        assert AgentPausedReplyAny.model_validate(original.model_dump()) == original


class TestPausedReplyIsAnAgentReplyAny:
    """The subclass decision: the union is untouched and every existing isinstance site still fires."""

    def test_satisfies_isinstance_of_its_base(self):
        assert isinstance(_paused_reply(), AgentReplyAny)

    def test_discriminator_is_lowercase_paused(self):
        """The model's type stays lowercase; the response body's status is the uppercase PAUSED."""
        assert _paused_reply().type == "paused"

    def test_agent_reply_union_gained_no_member(self):
        """The whole point of the subclass: the public union is untouched."""
        from agentkernel.core import model

        assert "AgentPausedReplyAny" not in str(model.AgentReply)


class TestDerivedContent:
    """`content` is a view of the typed fields, never independent data."""

    def test_content_is_built_from_the_typed_fields(self):
        reply = _paused_reply(interruptions=[_interruption("i1"), _interruption("i2", kind="confirmation")])
        assert reply.content["run_id"] == "run-1"
        assert reply.content["session_id"] == "sess-1"
        assert reply.content["agent"] == "refunds"
        assert [i["id"] for i in reply.content["interruptions"]] == ["i1", "i2"]

    def test_caller_supplied_content_is_overwritten(self):
        reply = _paused_reply(content={"note": "this is discarded"})
        assert "note" not in reply.content
        assert reply.content["run_id"] == "run-1"

    def test_constructs_without_content(self):
        """AgentReplyAny.content is required; the subclass defaults it so no adapter passes a placeholder."""
        assert _paused_reply().content != {}

    def test_str_is_readable_json(self):
        """The degradation path: Slack, Teams and the REST result key all go through str()."""
        parsed = json.loads(str(_paused_reply()))
        assert parsed["agent"] == "refunds"
        assert parsed["interruptions"][0]["id"] == "i1"


class TestResumeStructuralValidation:
    """Structural rules only — matching a decision to a pending interruption is a Runtime check."""

    @pytest.mark.parametrize("model", [ResumeSpec, AgentResumeRequestAny])
    def test_empty_decisions_rejected(self, model):
        with pytest.raises(ValidationError, match="at least one decision"):
            model(decisions=[])

    @pytest.mark.parametrize("model", [ResumeSpec, AgentResumeRequestAny])
    def test_duplicate_decision_ids_rejected(self, model):
        with pytest.raises(ValidationError, match="more than one decision for: i1"):
            model(decisions=[ResumeDecision(id="i1"), ResumeDecision(id="i1")])

    @pytest.mark.parametrize("model", [ResumeSpec, AgentResumeRequestAny])
    def test_unmatched_decision_id_is_not_rejected_here(self, model):
        """An unmatched id is a Runtime failure with its own error; the model has no session to check."""
        assert model(decisions=[ResumeDecision(id="no-such-interruption")]).decisions[0].id == "no-such-interruption"

    @pytest.mark.parametrize("model", [ResumeSpec, AgentResumeRequestAny])
    def test_run_id_is_optional(self, model):
        """Optional because AG-UI has no field for it; the run resolves from the interruption ids."""
        assert model(decisions=[ResumeDecision(id="i1")]).run_id is None

    def test_status_is_optional(self):
        """A pause asking for a value rather than an approval has nothing to approve."""
        assert ResumeDecision(id="i1", message="none of those").status is None

    def test_status_rejects_an_unknown_verb(self):
        with pytest.raises(ValidationError):
            ResumeDecision(id="i1", status="maybe")


class TestRequestUnion:
    """AgentResumeRequestAny is a union member, discriminated on `type`."""

    def test_parses_back_to_its_own_class(self):
        adapter = TypeAdapter(AgentRequest)
        parsed = adapter.validate_python({"type": "resume", "decisions": [{"id": "i1", "status": "approved"}]})
        assert isinstance(parsed, AgentResumeRequestAny)
        assert parsed.decisions[0].status == "approved"

    def test_does_not_subclass_agent_request_any(self):
        """Inheriting AgentRequestAny would inherit its *skip* handling — wrong for a decision."""
        from agentkernel.core.model import AgentRequestAny

        assert not issubclass(AgentResumeRequestAny, AgentRequestAny)

    def test_the_serialised_union_carries_it_too(self):
        """AgentRequest and AgentRequestUnion must not diverge: the second is what crosses the queue."""
        from agentkernel.core.model import AgentRequestUnion

        parsed = TypeAdapter(AgentRequestUnion).validate_python({"type": "resume", "decisions": [{"id": "i1", "status": "approved"}]})

        assert isinstance(parsed, AgentResumeRequestAny)

    def test_a_prebuilt_resume_survives_a_run_request_round_trip(self):
        """The shape a surface that prebuilds its request list would send through the broker."""
        from agentkernel.core.model import BaseRunRequest

        req = BaseRunRequest(session_id="s1", requests=[AgentResumeRequestAny(decisions=[ResumeDecision(id="i1", status="approved")])])
        back = BaseRunRequest.model_validate(json.loads(req.model_dump_json()))

        assert isinstance(back.requests[0], AgentResumeRequestAny)


class TestPayloadIsAnyJsonValue:
    """
    A payload is the framework's own shape, and not every framework poses its question as an object.

    Measured in research/verification.md: Pydantic AI takes a bare list as a deferred call's result,
    and LangGraph's Command(resume=...) takes whatever the node author expects, often a plain
    string. Typed as `dict`, AK could only deliver `{"choices": [...]}` — a wrapper no framework
    asked for, contradicting the design's own "passed through exactly as the framework produced it".
    """

    @pytest.mark.parametrize("payload", [["damaged", "wrong_item"], "just a string", 42, True, {"choice": "a"}, None])
    def test_a_decision_round_trips_any_json_value(self, payload):
        decision = ResumeDecision(id="i1", status="approved", payload=payload)

        assert ResumeDecision.model_validate(json.loads(decision.model_dump_json())).payload == payload

    @pytest.mark.parametrize("payload", [["a", "b"], "a question", {"options": ["a"]}])
    def test_an_interruption_round_trips_any_json_value(self, payload):
        interruption = PausedInterruption(id="i1", kind="input_required", payload=payload)

        assert PausedInterruption.model_validate(json.loads(interruption.model_dump_json())).payload == payload

    def test_a_framework_native_object_is_still_refused(self):
        """Why JsonValue rather than Any: the event must stay JSON- and pickle-safe."""
        with pytest.raises(ValidationError):
            PausedInterruption(id="i1", kind="input_required", payload=object())


class TestRunPausedEvent:
    """RunPaused is an ordinary StreamEvent, and stays JSON- and pickle-safe."""

    def test_round_trips_through_the_stream_event_union(self):
        adapter = TypeAdapter(StreamEvent)
        event = RunPaused(run_id="run-1", agent="refunds", interruptions=[_interruption()])
        parsed = adapter.validate_python(json.loads(event.model_dump_json()))
        assert isinstance(parsed, RunPaused)
        assert parsed.run_id == "run-1"
        assert parsed.interruptions[0].kind == "tool_call"

    def test_it_names_the_agent_that_paused(self):
        """The one thing a streaming client cannot derive, and a resume is rejected without it."""
        with pytest.raises(ValidationError):
            RunPaused(run_id="run-1", interruptions=[_interruption()])

    def test_carries_no_framework_native_object(self):
        import pickle

        event = RunPaused(run_id="run-1", agent="refunds", interruptions=[_interruption(payload={"options": ["a"]})])
        assert pickle.loads(pickle.dumps(event)) == event


def test_cancelled_message_reads_as_undecided_not_refused():
    """On every adapter but LangGraph this wording is what keeps "nobody decided" from reading as a refusal."""
    assert "not a refusal" in Runner.CANCELLED_DECISION_MESSAGE
