"""The LangGraph tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 23).

A compiled graph cannot be changed, so the gate is inside the tools `LangGraphToolBuilder` binds: each one
asks the run's tool filter before its function runs and answers with the reason instead. A tool the
application bound some other way cannot be gated, so with an `authorization` block an agent holding one does
not load (design Q12).

On real compiled graphs: a scripted model node calls the tools the test names and answers with what they
returned, so what is asserted is what ran and what the model saw, with no model call.
"""

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from agentkernel.core.base import Session
from agentkernel.core.model import AccessLevel, AgentPausedReplyAny, AgentRequestText, AgentResumeRequestAny, Principal, ResumeDecision, ToolFilter
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.factory import AKConfigError
from agentkernel.framework.langgraph.langgraph import LangGraphAgent, LangGraphModule, LangGraphRunner, LangGraphToolBuilder, LangGraphToolGate

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"
PROMPT = [AgentRequestText(prompt="refund order 7")]


class _Tools:
    """A `lookup` and a `refund` function that record their runs; `refund` can ask a human first."""

    def __init__(self, *, refund_asks: bool = False):
        self.ran: list[str] = []
        ran = self.ran

        def lookup(order_id: str) -> str:
            """Look an order up."""
            ran.append("lookup")
            return f"order {order_id}"

        def refund(order_id: str) -> str:
            """Refund an order."""
            if refund_asks:
                interrupt({"question": f"refund order {order_id}?"})
            ran.append("refund")
            return f"refunded {order_id}"

        async def invoice(order_id: str) -> str:
            """Send the invoice of an order."""
            ran.append("invoice")
            return f"invoiced {order_id}"

        self.lookup, self.refund, self.invoice = lookup, refund, invoice


def _graph(tools: list, *calls: str) -> StateGraph:
    """A model node that calls `calls` once and then reports what the tools returned, and a tool node."""

    def model(state: MessagesState):
        returned = [message.content for message in state["messages"] if isinstance(message, ToolMessage)]
        if returned or not calls:
            return {"messages": [AIMessage(content="model saw: " + " | ".join(returned))]}
        return {"messages": [AIMessage(content="", tool_calls=[{"name": name, "args": {"order_id": "7"}, "id": f"call-{name}"} for name in calls])]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", lambda state: "tools" if state["messages"][-1].tool_calls else END)
    builder.add_edge("tools", "model")
    return builder


def _agent(graph: StateGraph, name: str = "billing") -> LangGraphAgent:
    return LangGraphAgent(name=name, runner=LangGraphRunner(), agent=graph.compile(name=name))


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


REFUND_DENIED = _allowing("lookup", "invoice", refund=REFUND_REASON)


class TestWhatACallAnswers:
    @pytest.mark.asyncio
    async def test_a_denied_tool_is_not_run_and_the_model_sees_the_reason(self):
        tools = _Tools()
        agent = _agent(_graph(LangGraphToolBuilder.bind([tools.lookup, tools.refund]), "refund"))

        reply = await agent.runner.run(agent, _session(REFUND_DENIED), PROMPT)

        assert tools.ran == []
        assert str(reply) == f"model saw: {REFUND_REASON}"

    @pytest.mark.asyncio
    async def test_an_allowed_tool_runs_beside_a_denied_one(self):
        tools = _Tools()
        agent = _agent(_graph(LangGraphToolBuilder.bind([tools.lookup, tools.refund]), "lookup", "refund"))

        reply = await agent.runner.run(agent, _session(REFUND_DENIED), PROMPT)

        assert tools.ran == ["lookup"]
        assert str(reply) == f"model saw: order 7 | {REFUND_REASON}"

    @pytest.mark.asyncio
    async def test_a_tool_the_filter_never_listed_is_refused(self):
        tools = _Tools()
        agent = _agent(_graph(LangGraphToolBuilder.bind([tools.lookup, tools.refund]), "refund"))

        reply = await agent.runner.run(agent, _session(_allowing("lookup")), PROMPT)

        assert tools.ran == []
        assert str(reply) == "model saw: Tool 'refund' is not available to the current principal"

    @pytest.mark.asyncio
    async def test_an_async_tool_is_gated_the_same(self):
        tools = _Tools()
        agent = _agent(_graph(LangGraphToolBuilder.bind([tools.invoice]), "invoice"))

        denied = await agent.runner.run(agent, _session(_allowing(invoice="Tool 'invoice' is denied for agent 'billing'")), PROMPT)

        assert tools.ran == []
        assert str(denied) == "model saw: Tool 'invoice' is denied for agent 'billing'"

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_runs_every_tool(self):
        tools = _Tools()
        agent = _agent(_graph(LangGraphToolBuilder.bind([tools.lookup, tools.refund, tools.invoice]), "lookup", "refund", "invoice"))

        reply = await agent.runner.run(agent, _session(None), PROMPT)

        assert sorted(tools.ran) == ["invoice", "lookup", "refund"]
        assert str(reply) == "model saw: order 7 | refunded 7 | invoiced 7"

    @pytest.mark.asyncio
    async def test_a_streamed_run_is_gated_the_same(self):
        tools = _Tools()
        agent = _agent(_graph(LangGraphToolBuilder.bind([tools.lookup, tools.refund]), "lookup", "refund"))

        events = [event async for event in agent.runner.stream(agent, _session(REFUND_DENIED), PROMPT)]

        assert events
        assert tools.ran == ["lookup"]

    @pytest.mark.parametrize("stream", [False, True], ids=["resume", "resume-stream"])
    @pytest.mark.asyncio
    async def test_a_call_approved_while_paused_is_refused_when_the_tool_is_denied_by_then(self, stream):
        # LangGraph runs an interrupted node again on resume, so the gate asks again, with the resume's filter.
        tools = _Tools(refund_asks=True)
        agent = _agent(_graph(LangGraphToolBuilder.bind([tools.lookup, tools.refund]), "refund"))
        session = _session(_allowing("lookup", "refund"))
        paused = await agent.runner.run(agent, session, PROMPT)
        assert isinstance(paused, AgentPausedReplyAny), paused
        record = PausedRunState.get(session, paused.run_id)
        decisions = [ResumeDecision(id=paused.interruptions[0].id, payload="yes")]
        requests = [AgentResumeRequestAny(decisions=decisions)]

        session._publish_run(ALICE, REFUND_DENIED)
        if stream:
            [event async for event in agent.runner.resume_stream(agent, session, requests, decisions, record)]
        else:
            assert str(await agent.runner.resume(agent, session, requests, decisions, record)) == f"model saw: {REFUND_REASON}"

        assert tools.ran == []


class TestWhatTheBuilderBinds:
    def test_a_bound_tool_is_marked_gated_and_keeps_its_functions_schema(self):
        tools = _Tools()
        [bound] = LangGraphToolBuilder.bind([tools.refund])
        plain = StructuredTool.from_function(func=tools.refund, name="refund", description="d")

        assert LangGraphToolGate.gated(bound)
        assert bound.args == plain.args
        assert (bound.func is not None, bound.coroutine is None) == (True, True)

    def test_an_async_function_stays_a_coroutine(self):
        [bound] = LangGraphToolBuilder.bind([_Tools().invoice])

        assert (bound.func is None, bound.coroutine is not None) == (True, True)

    @pytest.mark.asyncio
    async def test_a_tool_renamed_after_binding_is_asked_about_under_its_new_name(self):
        tools = _Tools()
        [lookup, refund] = LangGraphToolBuilder.bind([tools.lookup, tools.refund])
        refund.name = "refund_order"
        agent = _agent(_graph([lookup, refund], "refund_order"))

        await agent.runner.run(agent, _session(_allowing("lookup", "refund_order")), PROMPT)

        assert agent.get_tool_names() == ["lookup", "refund_order"]
        assert tools.ran == ["refund"]


class TestWhatIsDeclared:
    def test_the_tools_of_a_compiled_subgraph_mounted_as_a_node_are_declared(self):
        tools = _Tools()
        billing = _graph(LangGraphToolBuilder.bind([tools.refund])).compile(name="billing_team")
        outer = StateGraph(MessagesState)
        outer.add_node("triage", ToolNode(LangGraphToolBuilder.bind([tools.lookup])))
        outer.add_node("billing", billing)
        outer.add_edge(START, "triage")
        outer.add_edge("triage", "billing")
        outer.add_edge("billing", END)

        agent = LangGraphAgent(name="desk", runner=LangGraphRunner(), agent=outer.compile(name="desk"))

        assert agent.get_tool_names() == ["lookup", "refund"]
        assert agent._tool_descriptions()["refund"] == "Refund an order."


class TestWhatCannotBeGated:
    """A tool the application bound itself runs where no gate is: it is named, and refused under the block."""

    @staticmethod
    def _native():
        @tool
        def export_ledger(order_id: str) -> str:
            """Export the ledger."""
            return "exported"

        return export_ledger

    def test_an_agent_whose_tools_the_builder_bound_has_none(self):
        tools = _Tools()

        assert _agent(_graph(LangGraphToolBuilder.bind([tools.lookup, tools.refund]))).ungated_tool_names() == []

    def test_a_tool_bound_another_way_is_named(self):
        tools = _Tools()
        agent = _agent(_graph([*LangGraphToolBuilder.bind([tools.lookup]), self._native()]))

        assert agent.get_tool_names() == ["lookup", "export_ledger"]
        assert agent.ungated_tool_names() == ["export_ledger"]

    def test_one_in_a_subgraph_is_named_too(self):
        billing = _graph([self._native()]).compile(name="billing_team")
        outer = StateGraph(MessagesState)
        outer.add_node("billing", billing)
        outer.add_edge(START, "billing")
        outer.add_edge("billing", END)

        agent = LangGraphAgent(name="desk", runner=LangGraphRunner(), agent=outer.compile(name="desk"))

        assert agent.ungated_tool_names() == ["export_ledger"]

    def test_such_an_agent_does_not_load_under_an_authorization_block(self, authorization):
        authorization(grants=[{"subjects": ["*"], "agents": ["*"], "level": "write"}])
        graph = _graph([self._native()]).compile(name="ledger")

        with Runtime(InMemorySessionStore()) as runtime:
            with pytest.raises(AKConfigError, match=r"agent 'ledger' on langgraph has tools Agent Kernel cannot gate: \['export_ledger'\]"):
                LangGraphModule([graph])
            assert runtime.agents() == {}

    def test_without_the_block_it_loads(self):
        graph = _graph([self._native()]).compile(name="ledger")

        with Runtime(InMemorySessionStore()) as runtime:
            LangGraphModule([graph])
            assert list(runtime.agents()) == ["ledger"]


class TestARunThroughRuntime:
    @pytest.mark.asyncio
    async def test_the_principals_level_decides_what_a_call_answers(self, authorization):
        authorization(
            grants=[{"subjects": ["group:support"], "agents": ["billing"], "level": "write"}],
            tools=[{"agent": "billing", "tiers": {"refund": "admin"}}],
        )
        tools = _Tools()
        graph = _graph(LangGraphToolBuilder.bind([tools.lookup, tools.refund]), "lookup", "refund").compile(name="billing")

        with Runtime(InMemorySessionStore()) as runtime:
            agent = LangGraphModule([graph]).get_agent("billing")
            reply = await runtime.run(agent, runtime.sessions().new("s1"), PROMPT, principal=ALICE)

        assert tools.ran == ["lookup"]
        assert str(reply) == f"model saw: order 7 | {REFUND_REASON}"
