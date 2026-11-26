"""The smolagents tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 23).

smolagents calls a tool through `Tool.__call__`, which calls the instance's `forward`, so the gate wraps
`forward` on every tool a run can call: the agent's own and its managed agents'. The wrapper answers a call to
a tool the run's tool filter does not allow with the reason. A tool the gate could not wrap (one added after
the agent was loaded, or one a code agent runs in a remote sandbox) is named, and with an `authorization`
block such an agent does not load (design Q12).

On real agents over a scripted model, so what is asserted is what ran and what the model was shown.
"""

import pytest
from smolagents import CodeAgent, ToolCallingAgent
from smolagents import tool as smol_tool
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole, Model

from agentkernel.core.base import Session
from agentkernel.core.model import AccessLevel, AgentRequestText, Principal, ToolFilter
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.factory import AKConfigError
from agentkernel.framework.smolagents.smolagents import SmolagentsAgent, SmolagentsModule, SmolagentsRunner, SmolagentsToolBuilder, SmolagentsToolGate

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"
EVERYONE_WRITES = [{"subjects": ["*"], "agents": ["*"], "level": "write"}]
PROMPT = [AgentRequestText(prompt="refund order 7")]


class Scripted(Model):
    """Calls the tools the test names, one a step, then gives the final answer; keeps what it was shown.

    A bare name is called with an order id; a `(name, arguments)` pair with its own arguments.
    """

    def __init__(self, *calls: str | tuple[str, dict]):
        super().__init__(model_id="scripted")
        self._calls = [call if isinstance(call, tuple) else (call, {"order_id": "7"}) for call in calls]
        self.shown: list[str] = []

    def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kwargs):
        self.shown.append(" ".join(str(getattr(message, "content", message)) for message in messages))
        name, arguments = self._calls.pop(0) if self._calls else ("final_answer", {"answer": "done"})
        call = ChatMessageToolCall(
            id=f"call-{len(self.shown)}", type="function", function=ChatMessageToolCallFunction(name=name, arguments=arguments)
        )
        return ChatMessage(role=MessageRole.ASSISTANT, content="", tool_calls=[call])

    @property
    def read(self) -> str:
        return self.shown[-1]


class _Tools:
    """A `lookup` and a `refund` tool that record their runs."""

    def __init__(self):
        self.ran: list[str] = []
        ran = self.ran

        def lookup(order_id: str) -> str:
            """Look an order up."""
            ran.append("lookup")
            return f"order {order_id}"

        def refund(order_id: str) -> str:
            """Refund an order."""
            ran.append("refund")
            return f"refunded {order_id}"

        self.lookup, self.refund = SmolagentsToolBuilder.bind([lookup, refund])


def _billing(*calls: str, tools: _Tools | None = None, **fields) -> tuple[SmolagentsAgent, Scripted, _Tools]:
    tools = tools or _Tools()
    model = Scripted(*calls)
    native = ToolCallingAgent(tools=[tools.lookup, tools.refund], model=model, name="billing", max_steps=4, **fields)
    return SmolagentsAgent("billing", SmolagentsRunner(), native), model, tools


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


REFUND_DENIED = _allowing("lookup", refund=REFUND_REASON)


@pytest.fixture
def gated(authorization):
    """An `authorization` block is configured, which is when the adapter puts its gate on the native tools."""
    authorization(grants=EVERYONE_WRITES)


class TestWhatACallAnswers:
    @pytest.mark.asyncio
    async def test_a_denied_tool_is_not_run_and_the_model_is_shown_the_reason(self, gated):
        agent, model, tools = _billing("refund")

        reply = await agent.runner.run(agent, _session(REFUND_DENIED), PROMPT)

        assert str(reply) == "done"
        assert tools.ran == []
        assert REFUND_REASON in model.read

    @pytest.mark.asyncio
    async def test_an_allowed_tool_runs_beside_a_denied_one(self, gated):
        agent, model, tools = _billing("lookup", "refund")

        await agent.runner.run(agent, _session(REFUND_DENIED), PROMPT)

        assert tools.ran == ["lookup"]
        assert "order 7" in model.read and REFUND_REASON in model.read

    @pytest.mark.asyncio
    async def test_a_tool_the_filter_never_listed_is_refused(self, gated):
        agent, model, tools = _billing("refund")

        await agent.runner.run(agent, _session(_allowing("lookup")), PROMPT)

        assert tools.ran == []
        assert "Tool 'refund' is not available to the current principal" in model.read

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_runs_every_tool(self, gated):
        agent, model, tools = _billing("lookup", "refund")

        await agent.runner.run(agent, _session(None), PROMPT)

        assert tools.ran == ["lookup", "refund"]

    @pytest.mark.asyncio
    async def test_the_final_answer_is_never_refused(self, gated):
        # A filter lists the tools an agent declares, and `final_answer` is how a run ends, not one of them.
        agent, model, tools = _billing()

        assert str(await agent.runner.run(agent, _session(_allowing()), PROMPT)) == "done"

    @pytest.mark.asyncio
    async def test_the_tools_of_a_managed_agent_are_gated_by_the_run_of_its_manager(self, gated):
        refunds_tools = _Tools()
        refunds_model = Scripted("refund")
        refunds = ToolCallingAgent(tools=[refunds_tools.refund], model=refunds_model, name="refunds", description="Refunds orders.", max_steps=3)
        manager_model = Scripted(("refunds", {"task": "refund order 7"}))
        manager = ToolCallingAgent(tools=[], model=manager_model, name="desk", managed_agents=[refunds], max_steps=3)
        agent = SmolagentsAgent("desk", SmolagentsRunner(), manager)

        await agent.runner.run(agent, _session(_allowing(refund=REFUND_REASON)), PROMPT)

        assert refunds_tools.ran == []
        assert REFUND_REASON in refunds_model.read  # the call to the managed agent went through; its tool was refused


class TestWhereTheGateIsPut:
    def test_without_an_authorization_block_the_native_tools_are_left_as_they_are(self):
        agent, _, tools = _billing()

        assert not SmolagentsToolGate.gated(tools.refund)
        assert agent.ungated_tool_names() == ["lookup", "refund"]  # true, and asked only under the block

    def test_with_the_block_every_tool_carries_it_once_and_the_final_answer_none(self, gated):
        agent, _, tools = _billing()
        forward = tools.refund.forward
        SmolagentsAgent("billing", SmolagentsRunner(), agent.agent)  # the same native agent wrapped again

        assert SmolagentsToolGate.gated(tools.lookup) and SmolagentsToolGate.gated(tools.refund)
        assert tools.refund.forward is forward
        assert not SmolagentsToolGate.gated(agent.agent.tools["final_answer"])
        assert agent.ungated_tool_names() == []

    def test_a_tool_attached_through_the_adapter_is_gated(self, gated):
        agent, _, _ = _billing()

        def invoice(order_id: str) -> str:
            """Send an invoice."""
            return "invoiced"

        agent.attach_tool(invoice)

        assert SmolagentsToolGate.gated(agent.agent.tools["invoice"])
        assert agent.ungated_tool_names() == []

    def test_the_tools_keep_their_inputs(self, gated):
        agent, _, tools = _billing()

        assert tools.refund.inputs == {"order_id": {"type": "string", "description": "order_id"}}
        tools.refund.validate_arguments()


class TestWhatIsDeclared:
    def test_a_managers_declared_tools_include_those_of_its_managed_agents(self):
        refunds_tools = _Tools()
        refunds = ToolCallingAgent(tools=[refunds_tools.refund], model=Scripted(), name="refunds", description="Refunds orders.")
        own = _Tools()
        manager = ToolCallingAgent(tools=[own.lookup], model=Scripted(), name="desk", managed_agents=[refunds])

        agent = SmolagentsAgent("desk", SmolagentsRunner(), manager)

        assert agent.get_tool_names() == ["lookup", "refund"]


class TestWhatCannotBeGated:
    def test_a_tool_added_to_the_agent_after_it_was_loaded_is_named(self, gated):
        agent, _, _ = _billing()

        @smol_tool
        def export_ledger(order_id: str) -> str:
            """Export the ledger.

            Args:
                order_id: The order whose ledger to export.
            """
            return "exported"

        agent.agent.tools["export_ledger"] = export_ledger

        assert agent.ungated_tool_names() == ["export_ledger"]

    def test_a_code_agent_that_runs_its_tools_in_a_remote_sandbox_names_them_all(self, gated):
        # A remote executor rebuilds each tool from its source in the sandbox, where no wrapper of ours runs.
        tools = _Tools()
        native = CodeAgent(tools=[tools.lookup, tools.refund], model=Scripted(), name="coder")
        native.python_executor = object()  # anything but the local executor

        agent = SmolagentsAgent("coder", SmolagentsRunner(), native)

        assert agent.ungated_tool_names() == ["lookup", "refund"]
        assert not SmolagentsToolGate.gated(tools.refund)

    def test_a_code_agent_on_the_local_executor_is_gated(self, gated):
        tools = _Tools()

        agent = SmolagentsAgent("coder", SmolagentsRunner(), CodeAgent(tools=[tools.lookup, tools.refund], model=Scripted(), name="coder"))

        assert agent.ungated_tool_names() == []

    def test_such_an_agent_does_not_load_under_an_authorization_block(self, gated):
        tools = _Tools()
        native = CodeAgent(tools=[tools.lookup], model=Scripted(), name="coder")
        native.python_executor = object()

        with Runtime(InMemorySessionStore()) as runtime:
            with pytest.raises(AKConfigError, match=r"agent 'coder' on smolagents has tools Agent Kernel cannot gate: \['lookup'\]"):
                SmolagentsModule([native])
            assert runtime.agents() == {}


class TestARunThroughRuntime:
    @pytest.mark.asyncio
    async def test_the_principals_level_decides_what_a_call_answers(self, authorization):
        authorization(
            grants=[{"subjects": ["group:support"], "agents": ["billing"], "level": "write"}],
            tools=[{"agent": "billing", "tiers": {"refund": "admin"}}],
        )
        tools, model = _Tools(), Scripted("lookup", "refund")
        native = ToolCallingAgent(tools=[tools.lookup, tools.refund], model=model, name="billing", max_steps=4)

        with Runtime(InMemorySessionStore()) as runtime:
            agent = SmolagentsModule([native]).get_agent("billing")
            reply = await runtime.run(agent, runtime.sessions().new("s1"), PROMPT, principal=ALICE)

        assert str(reply) == "done"
        assert tools.ran == ["lookup"]
        assert REFUND_REASON in model.read
