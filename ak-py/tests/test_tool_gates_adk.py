"""The Google ADK tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 22).

On real ADK agents over a scripted model, so no model is called and what is asserted is what ADK's own
function-call handling ran and what the model received for each call. ADK has no list-time hook (the tool list
is static on an `LlmAgent`), so the gate is a `before_tool_callback` on every agent a run can reach.
"""

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import pytest
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import FunctionTool
from google.adk.tools import ToolContext as ADKToolContext
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.set_model_response_tool import SetModelResponseTool
from google.adk.tools.transfer_to_agent_tool import TransferToAgentTool
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import BaseModel

from agentkernel.core.base import Session
from agentkernel.core.model import AccessLevel, AgentPausedReplyAny, AgentRequestText, AgentResumeRequestAny, Principal, ResumeDecision, ToolFilter
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import ToolContext as AKToolContext
from agentkernel.framework.adk.adk import GoogleADKAgent, GoogleADKRunner, GoogleADKToolGate

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"
REFUSED = {"error": REFUND_REASON}
EVERYONE_WRITES = [{"subjects": ["*"], "agents": ["*"], "level": "write"}]
PROMPT = [AgentRequestText(prompt="refund order 7")]


class Scripted(BaseLlm):
    """Calls the tools the test names, once, then answers; keeps what each call returned to it."""

    model: str = "scripted"
    calls: list = []
    seen: list = []
    rounds: int = 0

    async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self.rounds += 1
        returned = [part.function_response.response for content in llm_request.contents for part in (content.parts or []) if part.function_response]
        self.seen[:] = returned
        if self.rounds == 1 and self.calls:
            parts = [types.Part(function_call=types.FunctionCall(id=f"call-{name}", name=name, args=args)) for name, args in self.calls]
            yield LlmResponse(content=types.Content(role="model", parts=parts))
        else:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="done")]))


def _model(*calls) -> Scripted:
    """A model that calls the named tools; a bare name is called with an order id."""
    return Scripted(calls=[call if isinstance(call, tuple) else (call, {"order_id": "7"}) for call in calls], seen=[])


class _Billing:
    """A real `billing` agent with a `lookup` and a `refund` tool that record their runs."""

    def __init__(self, *calls, refund_needs_confirmation: bool = False, **fields):
        self.ran: list[str] = []
        self.model = _model(*calls)

        def lookup(order_id: str) -> str:
            """Look an order up."""
            self.ran.append("lookup")
            return f"order {order_id}"

        def refund(order_id: str) -> str:
            """Refund an order."""
            self.ran.append("refund")
            return f"refunded {order_id}"

        tools = [lookup, FunctionTool(func=refund, require_confirmation=True) if refund_needs_confirmation else refund]
        self.native = LlmAgent(name="billing", model=self.model, tools=tools, **fields)

    def wrap(self) -> GoogleADKAgent:
        self.runner = GoogleADKRunner()
        self.agent = GoogleADKAgent("billing", self.runner, self.native)
        return self.agent


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


REFUND_DENIED = _allowing("lookup", refund=REFUND_REASON)


@pytest.fixture
def gated(authorization):
    """An `authorization` block is configured, which is when the adapter puts its gate on the native agents."""
    authorization(grants=EVERYONE_WRITES)


@pytest.fixture
def billing(gated):
    def build(*calls, **options) -> _Billing:
        billing = _Billing(*calls, **options)
        billing.wrap()
        return billing

    return build


class TestWhatACallAnswers:
    @pytest.mark.asyncio
    async def test_a_denied_tool_is_not_run_and_the_model_is_given_the_reason(self, billing):
        b = billing("refund")

        reply = await b.runner.run(b.agent, _session(REFUND_DENIED), PROMPT)

        assert str(reply) == "done"
        assert b.ran == []
        assert b.model.seen == [REFUSED]

    @pytest.mark.asyncio
    async def test_an_allowed_tool_runs_beside_a_denied_one(self, billing):
        b = billing("lookup", "refund")

        await b.runner.run(b.agent, _session(REFUND_DENIED), PROMPT)

        assert b.ran == ["lookup"]
        assert b.model.seen == [{"result": "order 7"}, REFUSED]

    @pytest.mark.asyncio
    async def test_a_tool_the_filter_never_listed_is_refused(self, billing):
        b = billing("refund")

        await b.runner.run(b.agent, _session(_allowing("lookup")), PROMPT)

        assert b.ran == []
        assert b.model.seen == [{"error": "Tool 'refund' is not available to the current principal"}]

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_runs_every_tool(self, billing):
        b = billing("lookup", "refund")

        await b.runner.run(b.agent, _session(None), PROMPT)

        assert b.ran == ["lookup", "refund"]
        assert b.model.seen == [{"result": "order 7"}, {"result": "refunded 7"}]

    @pytest.mark.asyncio
    async def test_a_streamed_run_is_gated_the_same(self, billing):
        b = billing("lookup", "refund")

        events = [event async for event in b.runner.stream(b.agent, _session(REFUND_DENIED), PROMPT)]

        assert events
        assert b.ran == ["lookup"]
        assert b.model.seen == [{"result": "order 7"}, REFUSED]

    @pytest.mark.asyncio
    async def test_a_denied_tool_that_needs_confirmation_is_refused_and_never_pauses(self, billing):
        b = billing("refund", refund_needs_confirmation=True)

        reply = await b.runner.run(b.agent, _session(REFUND_DENIED), PROMPT)

        assert str(reply) == "done"
        assert b.ran == []
        assert b.model.seen == [REFUSED]

    @pytest.mark.parametrize("stream", [False, True], ids=["resume", "resume-stream"])
    @pytest.mark.asyncio
    async def test_a_call_confirmed_while_paused_is_refused_when_the_tool_is_denied_by_then(self, billing, stream):
        b, session = billing("refund", refund_needs_confirmation=True), _session(_allowing("lookup", "refund"))
        paused = await b.runner.run(b.agent, session, PROMPT)
        assert isinstance(paused, AgentPausedReplyAny), paused
        record = PausedRunState.get(session, paused.run_id)
        decisions = [ResumeDecision(id=paused.interruptions[0].id, status="approved")]
        requests = [AgentResumeRequestAny(decisions=decisions)]

        session._publish_run(ALICE, REFUND_DENIED)
        if stream:
            [event async for event in b.runner.resume_stream(b.agent, session, requests, decisions, record)]
        else:
            await b.runner.resume(b.agent, session, requests, decisions, record)

        assert b.ran == []
        assert REFUSED in b.model.seen


class TestWhereTheGateIsPut:
    def test_without_an_authorization_block_the_native_agents_are_left_as_they_are(self):
        b = _Billing("lookup")
        b.wrap()

        assert b.native.before_tool_callback is None

    def test_with_the_block_an_agent_carries_the_gate_once(self, billing):
        b = billing("lookup")
        GoogleADKAgent("billing", GoogleADKRunner(), b.native)  # the same native agent wrapped again

        assert b.native.before_tool_callback == [GoogleADKToolGate.before_tool]

    @pytest.mark.parametrize("as_list", [False, True], ids=["one-callback", "a-list"])
    def test_the_applications_own_callbacks_are_kept_behind_the_gate(self, gated, as_list):
        def audit(tool, args, tool_context):
            return None

        def limit(tool, args, tool_context):
            return None

        own = [audit, limit] if as_list else audit
        b = _Billing("lookup", before_tool_callback=own)
        b.wrap()

        assert b.native.before_tool_callback == [GoogleADKToolGate.before_tool, *([audit, limit] if as_list else [audit])]

    @pytest.mark.asyncio
    async def test_the_applications_callback_is_asked_about_an_allowed_call_only(self, gated):
        asked: list[str] = []

        def audit(tool, args, tool_context):
            asked.append(tool.name)
            return None

        b = _Billing("lookup", "refund", before_tool_callback=audit)
        b.wrap()

        await b.runner.run(b.agent, _session(REFUND_DENIED), PROMPT)

        assert asked == ["lookup"]
        assert b.ran == ["lookup"]


class TestAgentsARunCanReach:
    """One run can call the tools of any `LlmAgent` under the root, and the run's filter is the root's: each of
    them carries the gate, and their tools are declared under the root."""

    @staticmethod
    def _agent(name: str, *tools, **fields) -> LlmAgent:
        return LlmAgent(name=name, model=_model(), tools=list(tools), **fields)

    @staticmethod
    def lookup(order_id: str) -> str:
        """Look an order up."""
        return "order"

    @staticmethod
    def refund(order_id: str) -> str:
        """Refund an order."""
        return "refunded"

    @staticmethod
    def invoice(order_id: str) -> str:
        """Send an invoice."""
        return "invoiced"

    def _gates(self, *agents: LlmAgent) -> list[bool]:
        return [GoogleADKToolGate.before_tool in agent.canonical_before_tool_callbacks for agent in agents]

    def test_sub_agents_carry_the_gate(self, gated):
        refunds = self._agent("refunds", self.refund)
        root = self._agent("returns", self.lookup, sub_agents=[refunds])

        GoogleADKAgent("returns", GoogleADKRunner(), root)

        assert self._gates(root, refunds) == [True, True]

    def test_the_nodes_of_a_workflow_nested_in_a_workflow_are_reached(self, gated):
        first = self._agent("first", self.lookup, mode="chat", description="Opens.")
        deep = self._agent("deep", self.refund, mode="chat", description="Refunds.")
        inner = Workflow(name="inner", edges=[("START", deep)])
        flow = Workflow(name="flow", edges=[("START", first), (first, inner)])
        wrapped = GoogleADKAgent("flow", GoogleADKRunner(), flow)
        reached = GoogleADKToolGate.agents(flow)  # a workflow keeps copies of the agents it is given

        assert wrapped.get_tool_names() == ["lookup", "refund"]
        assert [agent.name for agent in reached] == ["first", "deep"]
        assert self._gates(*reached) == [True, True]

    def test_an_agent_used_as_a_tool_is_reached(self, gated):
        refunds = self._agent("refunds", self.refund, self.invoice)
        root = self._agent("returns", self.lookup, AgentTool(agent=refunds))
        wrapped = GoogleADKAgent("returns", GoogleADKRunner(), root)

        assert wrapped.get_tool_names() == ["lookup", "refunds", "refund", "invoice"]
        assert self._gates(root, refunds) == [True, True]

    def test_agents_that_reach_each_other_are_walked_once(self, gated):
        refunds = self._agent("refunds", self.refund)
        root = self._agent("returns", self.lookup, AgentTool(agent=refunds))
        refunds.tools.append(AgentTool(agent=root))

        assert GoogleADKAgent("returns", GoogleADKRunner(), root).get_tool_names() == ["lookup", "refunds", "refund", "returns"]

    @pytest.mark.asyncio
    async def test_a_sub_agents_tool_is_gated_by_the_run_that_transfers_to_it(self, gated):
        ran: list[str] = []

        def refund(order_id: str) -> str:
            """Refund an order."""
            ran.append("refund")
            return "refunded"

        refunds_model = _model("refund")
        refunds = LlmAgent(name="refunds", model=refunds_model, description="Refunds orders.", tools=[refund])
        root = LlmAgent(name="returns", model=_model(("transfer_to_agent", {"agent_name": "refunds"})), tools=[self.lookup], sub_agents=[refunds])
        runner = GoogleADKRunner()
        wrapped = GoogleADKAgent("returns", runner, root)

        await runner.run(wrapped, _session(REFUND_DENIED), PROMPT)

        assert ran == []
        assert refunds_model.seen[-1] == REFUSED  # the transfer went through, and the tool it led to was refused


class TestADKsOwnTools:
    """ADK adds two tools of its own to a request: the one a model transfers to another agent with, and the one
    it sets a structured response with. They are how a run moves, not tools the application declared, so the
    gate leaves them alone though no filter lists them."""

    class _Out(BaseModel):
        answer: str

    @pytest.fixture
    def run(self):
        """A run whose filter lists nothing but `lookup`, and the ADK tool context of a call in it."""
        context = AKToolContext(MagicMock(), MagicMock(), _session(_allowing("lookup")), [])
        with context:
            native = MagicMock(spec=ADKToolContext)
            native.state = {"ak_tool_context": context.id}
            yield native

    def test_a_transfer_is_not_refused(self, run):
        assert (
            GoogleADKToolGate.before_tool(tool=TransferToAgentTool(agent_names=["refunds"]), args={"agent_name": "refunds"}, tool_context=run) is None
        )

    def test_a_structured_response_is_not_refused(self, run):
        assert GoogleADKToolGate.before_tool(tool=SetModelResponseTool(self._Out), args={"answer": "x"}, tool_context=run) is None

    def test_any_other_tool_the_filter_never_listed_is(self, run):
        def export_ledger() -> str:
            """Export the ledger."""
            return "exported"

        assert GoogleADKToolGate.before_tool(tool=FunctionTool(func=export_ledger), args={}, tool_context=run) == {
            "error": "Tool 'export_ledger' is not available to the current principal"
        }


class TestToolsTheModelRuns:
    def test_a_built_in_tool_is_reported_as_run_by_the_provider(self):
        from google.adk.tools import google_search

        def lookup(order_id: str) -> str:
            """Look an order up."""
            return "order"

        researcher = LlmAgent(name="researcher", model=_model(), tools=[google_search])
        root = LlmAgent(name="desk", model=_model(), tools=[lookup, AgentTool(agent=researcher)])
        wrapped = GoogleADKAgent("desk", GoogleADKRunner(), root)

        assert wrapped.provider_tool_names() == ["google_search"]
        assert GoogleADKAgent("plain", GoogleADKRunner(), LlmAgent(name="plain", model=_model(), tools=[lookup])).provider_tool_names() == []


class TestACallOutsideARun:
    def _refund(self) -> FunctionTool:
        def refund(order_id: str) -> str:
            """Refund an order."""
            return "refunded"

        return FunctionTool(func=refund)

    def test_a_call_no_agent_kernel_run_started_is_not_gated(self):
        # The application running its ADK agent itself: the state carries no tool context of ours.
        native = MagicMock(spec=ADKToolContext)
        native.state = {}

        assert GoogleADKToolGate.before_tool(tool=self._refund(), args={}, tool_context=native) is None

    def test_a_call_whose_run_can_no_longer_be_found_is_refused(self):
        # Fail closed: the state names a run, and the run's filter cannot be read.
        native = MagicMock(spec=ADKToolContext)
        native.state = {"ak_tool_context": "gone"}

        assert GoogleADKToolGate.before_tool(tool=self._refund(), args={}, tool_context=native) == {"error": "tool gate failed: KeyError"}


class TestARunThroughRuntime:
    @pytest.mark.asyncio
    async def test_the_principals_level_decides_what_a_call_answers(self, authorization):
        authorization(
            grants=[{"subjects": ["group:support"], "agents": ["billing"], "level": "write"}],
            tools=[{"agent": "billing", "tiers": {"refund": "admin"}}],
        )
        b, runtime = _Billing("lookup", "refund"), Runtime(InMemorySessionStore())
        runtime.register(b.wrap())

        with runtime:
            reply = await runtime.run(b.agent, runtime.sessions().new("s1"), PROMPT, principal=ALICE)

        assert str(reply) == "done"
        assert b.ran == ["lookup"]
        assert b.model.seen == [{"result": "order 7"}, REFUSED]
