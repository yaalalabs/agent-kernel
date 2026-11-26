"""The CrewAI tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 22).

On real crews over a scripted model, so no model is called and what is asserted is what CrewAI's own executor
ran and what the model read as the result of each call. CrewAI has one process-wide list of tool-call hooks, so
the gate is two hooks in it: one blocks a refused call, the other puts the reason where CrewAI's own
"blocked by hook" line would be.

CrewAI is not installed beside the test extra, so this file runs through an overlay:
`uv run --no-sync --with "crewai>=1.15.0,<2.0.0" pytest tests/test_tool_gates_crewai.py`.
"""

import json

import pytest

pytest.importorskip("crewai")

from crewai import Agent as CrewAgent
from crewai import BaseLLM
from crewai.hooks.tool_hooks import (
    ToolCallHookContext,
    clear_all_tool_call_hooks,
    get_after_tool_call_hooks,
    get_before_tool_call_hooks,
    register_before_tool_call_hook,
    run_before_tool_call_hooks,
)
from crewai.tools import BaseTool
from crewai.tools import tool as crewai_tool
from crewai.tools.agent_tools.agent_tools import AgentTools

from agentkernel.core import ToolContext
from agentkernel.core.base import Session
from agentkernel.core.model import AccessLevel, AgentRequestText, Principal, ToolFilter
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.framework.crewai.crewai import CrewAIAgent, CrewAIModule, CrewAIRunner, CrewAIToolGate

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"
BLOCKED_BY_HOOK = "Tool execution blocked by hook"
PROMPT = [AgentRequestText(prompt="refund order 7")]


class Scripted(BaseLLM):
    """Calls the tools the test names, one a turn, then answers; keeps everything it was shown."""

    def __init__(self, *calls):
        super().__init__(model="scripted")
        self._calls = [call if isinstance(call, tuple) else (call, {"order_id": "7"}) for call in calls]
        self.shown: list[str] = []

    def supports_function_calling(self) -> bool:
        return False  # the ReAct path: the call and its result travel as text, which the test can read

    def call(self, messages, tools=None, callbacks=None, available_functions=None, from_task=None, from_agent=None, response_model=None):
        turn = len(self.shown)
        self.shown.append(messages if isinstance(messages, str) else "\n".join(str(message.get("content", "")) for message in messages))
        if turn < len(self._calls):
            name, arguments = self._calls[turn]
            return f"Thought: I should use a tool.\nAction: {name}\nAction Input: {json.dumps(arguments)}"
        return "Thought: I now know the final answer\nFinal Answer: done"

    @property
    def read(self) -> str:
        """Everything the model was shown on its last turn: the conversation so far, tool results included."""
        return self.shown[-1]


class _Crew:
    """A real `billing` agent with a `lookup` and a `refund` tool that record their runs."""

    def __init__(self, *calls, **fields):
        self.ran: list[str] = []
        ran = self.ran

        @crewai_tool
        def lookup(order_id: str) -> str:
            """Look an order up."""
            ran.append("lookup")
            return f"order {order_id}"

        @crewai_tool
        def refund(order_id: str) -> str:
            """Refund an order."""
            ran.append("refund")
            return f"refunded {order_id}"

        self.model = Scripted(*calls)
        self.native = CrewAgent(role="billing", goal="Bill customers", backstory="Bills.", llm=self.model, tools=[lookup, refund], **fields)
        self.runner = CrewAIRunner()
        self.agent = CrewAIAgent("billing", self.runner, self.native, [self.native])


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


REFUND_DENIED = _allowing("lookup", refund=REFUND_REASON)


@pytest.fixture(autouse=True)
def _crewai_hooks():
    """CrewAI's hook lists are the process's: each test starts with none and leaves none behind."""
    clear_all_tool_call_hooks()
    yield
    clear_all_tool_call_hooks()


@pytest.fixture
def installed():
    """The gate's hooks are registered, as loading a module under an `authorization` block does."""
    CrewAIToolGate.install()


class TestWhatACallAnswers:
    @pytest.mark.asyncio
    async def test_a_denied_tool_is_not_run_and_the_model_reads_the_reason(self, installed):
        crew = _Crew("refund")

        reply = await crew.runner.run(crew.agent, _session(REFUND_DENIED), PROMPT)

        assert str(reply) == "done"
        assert crew.ran == []
        assert REFUND_REASON in crew.model.read
        assert BLOCKED_BY_HOOK not in crew.model.read

    @pytest.mark.asyncio
    async def test_an_allowed_tool_runs_beside_a_denied_one(self, installed):
        crew = _Crew("lookup", "refund")

        await crew.runner.run(crew.agent, _session(REFUND_DENIED), PROMPT)

        assert crew.ran == ["lookup"]
        assert "order 7" in crew.model.read and REFUND_REASON in crew.model.read

    @pytest.mark.asyncio
    async def test_a_tool_the_filter_never_listed_is_refused(self, installed):
        crew = _Crew("refund")

        await crew.runner.run(crew.agent, _session(_allowing("lookup")), PROMPT)

        assert crew.ran == []
        assert "Tool 'refund' is not available to the current principal" in crew.model.read

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_runs_every_tool(self, installed):
        crew = _Crew("lookup", "refund")

        await crew.runner.run(crew.agent, _session(None), PROMPT)

        assert crew.ran == ["lookup", "refund"]
        assert "refunded 7" in crew.model.read

    @pytest.mark.asyncio
    async def test_without_the_hooks_nothing_is_stopped(self):
        # What a process with no `authorization` block runs: the hooks are never registered.
        crew = _Crew("refund")

        await crew.runner.run(crew.agent, _session(REFUND_DENIED), PROMPT)

        assert crew.ran == ["refund"]


class _RefundOrder(BaseTool):
    name: str = "Refund Order"
    description: str = "Refund an order."

    def _run(self, order_id: str) -> str:
        return f"refunded {order_id}"


def _named(name: str) -> BaseTool:
    """A tool declared under `name`, exactly as written."""

    class _Tool(BaseTool):
        description: str = "A tool."

        def _run(self, order_id: str = "") -> str:
            return "ran"

    return _Tool(name=name)


class TestTheNameACallIsMatchedBy:
    """CrewAI serves a tool under a sanitized name; the filter lists the name the agent declares."""

    @staticmethod
    def _context(tool: BaseTool, called: str) -> ToolCallHookContext:
        return ToolCallHookContext(tool_name=called, tool_input={}, tool=tool.to_structured_tool())

    @pytest.fixture
    def running(self):
        def _run(tool_filter: ToolFilter | None) -> None:
            ToolContext(Runtime.current(), None, _session(tool_filter), []).set()

        yield _run
        ToolContext._context.set(None)

    def test_a_declared_name_is_found_by_the_name_crewai_calls_it(self, running):
        reason = "Tool 'Refund Order' requires level admin; the current principal has write"
        running(_allowing("lookup", **{"Refund Order": reason}))

        assert CrewAIToolGate.refusal(self._context(_RefundOrder(), "refund_order")) == reason

    def test_an_allowed_tool_with_a_display_name_is_let_through(self, running):
        running(_allowing("Refund Order"))

        assert CrewAIToolGate.refusal(self._context(_RefundOrder(), "refund_order")) is None

    def test_two_tools_whose_names_sanitize_alike_are_decided_each_by_its_own_name(self, running):
        # `Refund Order` on the agent is allowed, `refund_order` on a coworker is denied: CrewAI calls both
        # `refund_order`, and the call is decided by the tool CrewAI selected, never by whichever name comes first.
        running(_allowing("Refund Order", refund_order="Tool 'refund_order' is denied for agent 'billing'"))

        assert CrewAIToolGate.refusal(self._context(_named("refund_order"), "refund_order")) == "Tool 'refund_order' is denied for agent 'billing'"
        assert CrewAIToolGate.refusal(self._context(_named("Refund Order"), "refund_order")) is None

    def test_without_the_selected_tool_a_served_name_two_declared_names_share_is_refused(self, running):
        running(_allowing("Refund Order", "refund_order"))
        context = self._context(_named("refund_order"), "refund_order")
        context.tool = None

        assert CrewAIToolGate.refusal(context) == "Tool 'refund_order' is ambiguous: ['Refund Order', 'refund_order'] are all served under that name"

    def test_outside_a_run_nothing_is_refused(self):
        assert CrewAIToolGate.refusal(self._context(_RefundOrder(), "refund_order")) is None

    def test_a_hook_that_cannot_decide_refuses_the_call(self, running, installed):
        # CrewAI lets a call through when a hook raises, so the gate must answer instead of failing.
        running(_allowing("Refund Order"))
        context = self._context(_RefundOrder(), "refund_order")
        context.tool, context.tool_name = None, None  # nothing a name can be matched by

        assert CrewAIToolGate.refusal(context).startswith("tool gate failed: ")
        assert run_before_tool_call_hooks(context) is True  # CrewAI's own dispatch: the call is blocked


class TestDelegation:
    @staticmethod
    def _agents(allow_delegation: bool) -> tuple[CrewAgent, CrewAgent]:
        @crewai_tool
        def lookup(order_id: str) -> str:
            """Look an order up."""
            return "order"

        @crewai_tool
        def refund(order_id: str) -> str:
            """Refund an order."""
            return "refunded"

        triage = CrewAgent(role="triage", goal="Route", backstory="Routes.", llm=Scripted(), tools=[lookup], allow_delegation=allow_delegation)
        billing = CrewAgent(role="billing", goal="Bill", backstory="Bills.", llm=Scripted(), tools=[lookup, refund])
        return triage, billing

    def test_an_agent_that_may_delegate_declares_its_coworkers_tools_after_its_own(self):
        triage, billing = self._agents(allow_delegation=True)
        wrapped = CrewAIAgent("triage", CrewAIRunner(), triage, [triage, billing])

        assert wrapped.get_tool_names() == ["lookup", "refund"]
        assert wrapped._tool_descriptions()["refund"].endswith("Refund an order.")

    def test_an_agent_that_may_not_delegate_declares_its_own_tools_only(self):
        triage, billing = self._agents(allow_delegation=False)

        assert CrewAIAgent("triage", CrewAIRunner(), triage, [triage, billing]).get_tool_names() == ["lookup"]
        assert CrewAIAgent("billing", CrewAIRunner(), billing, [triage, billing]).get_tool_names() == ["lookup", "refund"]

    def test_the_tools_crewai_adds_for_delegation_are_not_refused(self):
        triage, billing = self._agents(allow_delegation=True)
        ToolContext(Runtime.current(), None, _session(_allowing("lookup")), []).set()
        try:
            answers = [
                CrewAIToolGate.refusal(ToolCallHookContext(tool_name=tool.name, tool_input={}, tool=tool.to_structured_tool()))
                for tool in AgentTools(agents=[billing]).tools()
            ]
        finally:
            ToolContext._context.set(None)

        assert answers == [None, None]


class TestTheHooks:
    def test_installing_twice_registers_each_hook_once(self):
        CrewAIToolGate.install()
        CrewAIToolGate.install()

        assert get_before_tool_call_hooks() == [CrewAIToolGate.before_tool_call]
        assert get_after_tool_call_hooks() == [CrewAIToolGate.after_tool_call]

    def test_the_gate_goes_ahead_of_the_applications_own_hooks_registered_before_it(self):
        # CrewAI runs before hooks in order, so an approval hook registered first would ask a person about a call
        # the gate then refuses. The application's hooks are kept, in their order, behind the gate.
        def audit(context):
            return None

        def approve(context):
            return None

        register_before_tool_call_hook(audit)
        register_before_tool_call_hook(approve)
        CrewAIToolGate.install()

        assert get_before_tool_call_hooks() == [CrewAIToolGate.before_tool_call, audit, approve]

    def test_the_applications_hooks_never_see_a_call_the_gate_refused(self):
        seen: list[str] = []

        def audit(context):
            seen.append(context.tool_name)
            return None

        register_before_tool_call_hook(audit)
        CrewAIToolGate.install()
        ToolContext(Runtime.current(), None, _session(REFUND_DENIED), []).set()
        try:
            refused = run_before_tool_call_hooks(ToolCallHookContext(tool_name="refund", tool_input={}, tool=_named("refund").to_structured_tool()))
        finally:
            ToolContext._context.set(None)

        assert refused is True
        assert seen == []

    def test_loading_a_module_registers_the_hooks_only_under_an_authorization_block(self, authorization):
        native = CrewAgent(role="billing", goal="Bill", backstory="Bills.", llm=Scripted())

        with Runtime(InMemorySessionStore()):
            CrewAIModule([native])
            without_the_block = (get_before_tool_call_hooks(), get_after_tool_call_hooks())
        authorization(grants=[{"subjects": ["*"], "agents": ["*"], "level": "write"}])
        with Runtime(InMemorySessionStore()):
            CrewAIModule([native])

        assert without_the_block == ([], [])
        assert get_before_tool_call_hooks() == [CrewAIToolGate.before_tool_call]
        assert get_after_tool_call_hooks() == [CrewAIToolGate.after_tool_call]


class TestARunThroughRuntime:
    @pytest.mark.asyncio
    async def test_the_principals_level_decides_what_a_call_answers(self, authorization):
        authorization(
            grants=[{"subjects": ["group:support"], "agents": ["billing"], "level": "write"}],
            tools=[{"agent": "billing", "tiers": {"refund": "admin"}}],
        )
        crew = _Crew("lookup", "refund")
        runtime = Runtime(InMemorySessionStore())
        with runtime:
            module = CrewAIModule([crew.native])
            agent = module.get_agent("billing")
            reply = await runtime.run(agent, runtime.sessions().new("s1"), PROMPT, principal=ALICE)

        assert str(reply) == "done"
        assert crew.ran == ["lookup"]
        assert REFUND_REASON in crew.model.read
