"""The Pydantic AI tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 21).

On a real agent driven by `FunctionModel`, so no model is called and what is asserted is what the model is
offered and what it receives: the gate is a per-run capability, and only the SDK running it proves it is wired.
"""

from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Agent as NativeAgent
from pydantic_ai import DeferredToolRequests, FunctionToolset
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.tools import ToolDefinition

from agentkernel.core.base import Session
from agentkernel.core.model import AccessLevel, AgentRequestText, AgentResumeRequestAny, Principal, ResumeDecision, ToolFilter
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.framework.pydanticai.pydanticai import AKToolGateCapability, PydanticAIAgent, PydanticAIRunner, PydanticAIToolBuilder

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"


class _Billing:
    """A real agent whose model records the tools each step offers it and calls the ones the test scripts."""

    def __init__(self, *, calls: tuple[str, ...] = (), refund_needs_approval: bool = False, toolsets=None):
        self.offered: list[list[str]] = []
        self.returns: list[tuple[str, object]] = []
        self.ran: list[str] = []

        def lookup(order_id: str) -> str:
            """Look an order up."""
            self.ran.append("lookup")
            return f"order {order_id}"

        def refund(order_id: str) -> str:
            """Refund an order."""
            self.ran.append("refund")
            return f"refunded {order_id}"

        def model_fn(messages, info):
            self.offered.append([definition.name for definition in info.function_tools])
            done = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
            self.returns = [(part.tool_name, part.content) for part in done]
            if calls and not done:
                return ModelResponse(parts=[ToolCallPart(name, {"order_id": "7"}, tool_call_id=f"call-{name}") for name in calls])
            return ModelResponse(parts=[TextPart("done")])

        async def stream_fn(messages, info):
            self.offered.append([definition.name for definition in info.function_tools])
            yield "done"

        tools = PydanticAIToolBuilder.bind([lookup]) + PydanticAIToolBuilder.bind([refund], requires_approval=refund_needs_approval)
        self.native = NativeAgent(
            FunctionModel(model_fn, stream_function=stream_fn),
            name="billing",
            tools=tools,
            toolsets=toolsets,
            output_type=[str, DeferredToolRequests],
        )
        self.agent = PydanticAIAgent("billing", PydanticAIRunner(), self.native)


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


PROMPT = [AgentRequestText(prompt="refund order 7")]


class TestWhatAStepOffers:
    @pytest.mark.asyncio
    async def test_a_denied_tool_is_not_offered(self):
        billing = _Billing()

        reply = await PydanticAIRunner().run(billing.agent, _session(_allowing("lookup", refund=REFUND_REASON)), PROMPT)

        assert str(reply) == "done"
        assert billing.offered == [["lookup"]]

    @pytest.mark.asyncio
    async def test_a_streamed_run_is_gated_the_same(self):
        billing = _Billing()

        events = [event async for event in PydanticAIRunner().stream(billing.agent, _session(_allowing("lookup", refund=REFUND_REASON)), PROMPT)]

        assert events
        assert billing.offered == [["lookup"]]

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_offers_every_tool(self):
        billing = _Billing()

        await PydanticAIRunner().run(billing.agent, _session(None), PROMPT)

        assert billing.offered == [["lookup", "refund"]]

    @pytest.mark.asyncio
    async def test_a_tool_the_agent_does_not_declare_is_not_offered(self):
        # A toolset handed over for one run is listed inside the run only, so no policy could have offered it.
        def export_ledger() -> str:
            """Export the ledger."""
            return "exported"

        billing = _Billing()
        billing.agent.run_options["toolsets"] = [FunctionToolset([export_ledger])]

        await PydanticAIRunner().run(billing.agent, _session(_allowing("lookup", "refund")), PROMPT)
        await PydanticAIRunner().run(billing.agent, _session(None), PROMPT)

        assert billing.offered == [["lookup", "refund"], ["lookup", "refund", "export_ledger"]]

    @pytest.mark.asyncio
    async def test_a_tool_behind_a_prefix_is_matched_by_the_name_the_model_calls(self):
        def ledger(order_id: str) -> str:
            """Read the ledger."""
            return "ledger"

        billing = _Billing(toolsets=[FunctionToolset([ledger]).prefixed("crm")])

        await PydanticAIRunner().run(billing.agent, _session(_allowing("lookup", "crm_ledger", refund=REFUND_REASON)), PROMPT)

        assert billing.agent.get_tool_names() == ["lookup", "refund", "crm_ledger"]
        assert billing.offered == [["lookup", "crm_ledger"]]


class TestTheNativeCall:
    """The gate is one more capability on a gated run, and nothing at all on any other."""

    @staticmethod
    async def _native_kwargs(billing: _Billing, tool_filter: ToolFilter | None) -> dict:
        native_run = billing.native.run
        seen: dict = {}

        async def spy(content, **kwargs):
            seen.update(kwargs)
            return await native_run(content, **kwargs)

        billing.native.run = spy
        await PydanticAIRunner().run(billing.agent, _session(tool_filter), PROMPT)
        return seen

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_passes_no_capability(self):
        kwargs = await self._native_kwargs(_Billing(), None)

        assert sorted(kwargs) == ["deps", "message_history"]

    @pytest.mark.asyncio
    async def test_a_gated_run_passes_the_gate_and_nothing_else_new(self):
        kwargs = await self._native_kwargs(_Billing(), _allowing("lookup"))

        assert sorted(kwargs) == ["capabilities", "deps", "message_history"]
        assert [type(capability) for capability in kwargs["capabilities"]] == [AKToolGateCapability]

    @pytest.mark.asyncio
    async def test_the_gate_goes_ahead_of_the_capabilities_the_run_options_carry(self):
        class Own(AbstractCapability):
            pass

        billing, own = _Billing(), Own()
        billing.agent.run_options["capabilities"] = [own]

        kwargs = await self._native_kwargs(billing, _allowing("lookup"))

        assert [type(capability) for capability in kwargs["capabilities"]] == [AKToolGateCapability, Own]
        assert kwargs["capabilities"][1] is own
        assert billing.agent.run_options["capabilities"] == [own]  # the declared options are not changed by a run


class TestWhatACallAnswers:
    @pytest.mark.parametrize("stream", [False, True], ids=["resume", "resume-stream"])
    @pytest.mark.asyncio
    async def test_a_call_approved_while_paused_is_refused_when_the_tool_is_denied_by_then(self, stream):
        # The one way a denied tool is still called: it was offered and paused for approval, and the policy
        # (or the caller's level) changed before the approval came back.
        billing, runner, session = (
            _Billing(calls=("refund",), refund_needs_approval=True),
            PydanticAIRunner(),
            _session(_allowing("lookup", "refund")),
        )
        paused = await runner.run(billing.agent, session, PROMPT)
        record = PausedRunState.get(session, paused.run_id)
        decisions = [ResumeDecision(id=paused.interruptions[0].id, status="approved")]
        requests = [AgentResumeRequestAny(decisions=decisions)]

        session._publish_run(ALICE, _allowing("lookup", refund=REFUND_REASON))
        if stream:
            [event async for event in runner.resume_stream(billing.agent, session, requests, decisions, record)]
        else:
            assert str(await runner.resume(billing.agent, session, requests, decisions, record)) == "done"

        assert billing.ran == []
        assert billing.offered[-1] == ["lookup"]  # the resumed step is gated like any other
        if not stream:
            assert billing.returns == [("refund", REFUND_REASON)]  # what the model was given as the call's result

    @pytest.mark.asyncio
    async def test_an_approved_call_to_a_tool_still_allowed_runs(self):
        billing, runner, session = (
            _Billing(calls=("refund",), refund_needs_approval=True),
            PydanticAIRunner(),
            _session(_allowing("lookup", "refund")),
        )
        paused = await runner.run(billing.agent, session, PROMPT)
        record = PausedRunState.get(session, paused.run_id)
        decisions = [ResumeDecision(id=paused.interruptions[0].id, status="approved")]

        await runner.resume(billing.agent, session, [AgentResumeRequestAny(decisions=decisions)], decisions, record)

        assert billing.ran == ["refund"]
        assert billing.returns == [("refund", "refunded 7")]

    @pytest.mark.parametrize(
        "tool_filter, name, runs",
        [
            (_allowing("lookup", refund=REFUND_REASON), "refund", False),
            (_allowing("lookup", refund=REFUND_REASON), "lookup", True),
            (_allowing("lookup"), "never_declared", False),
            (None, "refund", True),
        ],
        ids=["denied", "allowed", "never-declared", "not-gated"],
    )
    @pytest.mark.asyncio
    async def test_the_capability_runs_the_tool_only_when_the_filter_allows_it(self, tool_filter, name, runs):
        handler = AsyncMock(return_value="ran")
        capability = AKToolGateCapability(_session(tool_filter))

        answer = await capability.wrap_tool_execute(None, call=None, tool_def=ToolDefinition(name=name), args={}, handler=handler)

        assert handler.await_count == (1 if runs else 0)
        assert answer == ("ran" if runs else tool_filter.reason(name))


class TestARunThroughRuntime:
    @pytest.mark.asyncio
    async def test_the_principals_level_decides_what_the_model_is_offered(self, authorization):
        authorization(
            grants=[{"subjects": ["group:support"], "agents": ["billing"], "level": "write"}],
            tools=[{"agent": "billing", "tiers": {"refund": "admin"}}],
        )
        billing, runtime = _Billing(), Runtime(InMemorySessionStore())
        runtime.register(billing.agent)

        with runtime:
            reply = await runtime.run(billing.agent, runtime.sessions().new("s1"), PROMPT, principal=ALICE)

        assert str(reply) == "done"
        assert billing.offered == [["lookup"]]
