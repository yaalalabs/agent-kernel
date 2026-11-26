"""The OpenAI Agents SDK tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 21).

On real SDK objects and with no model call: the SDK's own `Agent.get_all_tools` decides what a turn offers and
its own `ToolInputGuardrail.run` decides what a call answers, so the gate is tested through the two seams the
SDK calls it by. A run through `Runtime` shows the filter the access gate publishes reaching those seams.
"""

import dataclasses
import typing
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents import Agent as SDKAgent
from agents import FunctionTool, RunContextWrapper, WebSearchTool, function_tool, handoff
from agents.handoffs import Handoff
from agents.mcp import MCPServerStdio
from agents.tool_context import ToolContext as SDKToolContext
from agents.tool_guardrails import ToolGuardrailFunctionOutput, ToolInputGuardrail, ToolInputGuardrailData
from agents.usage import Usage

from agentkernel.core import ToolContext
from agentkernel.core.base import Session
from agentkernel.core.model import AccessLevel, AgentRequestText, Principal, SystemTool, ToolFilter
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import SystemToolFactory
from agentkernel.core.util.factory import AKConfigError
from agentkernel.framework.openai.openai import OpenAIAgent, OpenAIRunner, OpenAIToolGate
from agentkernel.identity.authz.gate import AccessGate

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"
EVERYONE_WRITES = [{"subjects": ["*"], "agents": ["*"], "level": "write"}]


def lookup(order_id: str) -> str:
    """Look an order up."""
    return f"order {order_id}"


def refund(order_id: str) -> str:
    """Refund an order."""
    return f"refunded {order_id}"


def invoice(order_id: str) -> str:
    """Send the invoice of an order."""
    return f"invoiced {order_id}"


def _native(name: str = "billing", tools=None, **fields) -> SDKAgent:
    return SDKAgent(name=name, instructions="Bill customers.", tools=function_tool_list(tools if tools is not None else [lookup, refund]), **fields)


def function_tool_list(tools: list) -> list:
    return [tool if not callable(tool) or isinstance(tool, FunctionTool) else function_tool(tool) for tool in tools]


def _wrapped(native: SDKAgent) -> OpenAIAgent:
    return OpenAIAgent(native.name, OpenAIRunner(), native)


def _tool(native: SDKAgent, name: str) -> FunctionTool:
    return next(tool for tool in native.tools if tool.name == name)


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


async def _offered(native: SDKAgent) -> list[str]:
    """The tools the SDK would offer the model this turn: its own enablement check, hosted tools included."""
    return [tool.name for tool in await native.get_all_tools(RunContextWrapper(context=None))]


async def _answer(native: SDKAgent, name: str) -> list[ToolGuardrailFunctionOutput]:
    """What each input guardrail of a tool answers for one call, in the order the SDK runs them."""
    tool = _tool(native, name)
    data = ToolInputGuardrailData(
        context=SDKToolContext(context=None, usage=Usage(), tool_name=name, tool_call_id="call-1", tool_arguments="{}"), agent=native
    )
    return [await guardrail.run(data) for guardrail in tool.tool_input_guardrails or []]


@pytest.fixture
def running():
    """Returns a function that makes a session the one of the current `ToolContext`, as the runner does for a run.

    An async test sets it inside its own task's context, which ends with the test, so there is no token to hand
    back here; the variable is cleared for the case of a test that set it in this one.
    """

    def _run(tool_filter: ToolFilter | None) -> Session:
        session = _session(tool_filter)
        ToolContext(MagicMock(), MagicMock(), session, []).set()
        return session

    yield _run
    ToolContext._context.set(None)


@pytest.fixture
def gated(authorization):
    """An `authorization` block is configured, which is when the adapter puts its gate on the native tools."""
    authorization(grants=EVERYONE_WRITES)


class TestWhatATurnOffers:
    @pytest.mark.asyncio
    async def test_a_denied_tool_is_not_offered(self, gated, running):
        native = _native()
        _wrapped(native)
        running(_allowing("lookup", refund=REFUND_REASON))

        assert await _offered(native) == ["lookup"]

    @pytest.mark.asyncio
    async def test_a_tool_the_filter_never_listed_is_not_offered(self, gated, running):
        native = _native()
        _wrapped(native)
        running(_allowing("refund"))

        assert await _offered(native) == ["refund"]

    @pytest.mark.asyncio
    async def test_a_tool_the_application_disabled_stays_disabled(self, gated, running):
        native = _native(tools=[function_tool(lookup, is_enabled=False), refund])
        _wrapped(native)
        running(_allowing("lookup", "refund"))

        assert await _offered(native) == ["refund"]

    @pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
    @pytest.mark.asyncio
    async def test_the_applications_own_check_is_asked_once_the_gate_allows(self, gated, running, is_async):
        asked: list[str] = []

        def sync_check(run_context, agent) -> bool:
            asked.append(agent.name)
            return False

        async def async_check(run_context, agent) -> bool:
            return sync_check(run_context, agent)

        native = _native(tools=[function_tool(lookup, is_enabled=async_check if is_async else sync_check), refund])
        _wrapped(native)
        running(_allowing("lookup", "refund"))

        assert await _offered(native) == ["refund"]
        assert asked == ["billing"]

    @pytest.mark.asyncio
    async def test_the_gate_answers_before_the_applications_own_check(self, gated, running):
        asked: list[str] = []
        native = _native(tools=[function_tool(lookup, is_enabled=lambda run_context, agent: asked.append("asked") or True), refund])
        _wrapped(native)
        running(_allowing("refund", lookup="Tool 'lookup' is denied for agent 'billing'"))

        assert await _offered(native) == ["refund"]
        assert asked == []

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_offers_what_the_application_set(self, gated, running):
        native = _native(tools=[function_tool(lookup, is_enabled=False), refund])
        _wrapped(native)
        running(None)

        assert await _offered(native) == ["refund"]

    @pytest.mark.asyncio
    async def test_outside_a_run_the_agent_offers_what_the_application_set(self, gated):
        native = _native()
        _wrapped(native)

        assert await _offered(native) == ["lookup", "refund"]

    @pytest.mark.asyncio
    async def test_a_hosted_tool_is_listed_and_cannot_be_gated(self, gated, running):
        # The provider runs a hosted tool: the SDK asks no `is_enabled` for it and runs no guardrail around it.
        native = _native(tools=[lookup, WebSearchTool()])
        wrapped = _wrapped(native)
        running(_allowing("lookup", web_search="Tool 'web_search' is denied for agent 'billing'"))

        assert wrapped.get_tool_names() == ["lookup", "web_search"]
        assert await _offered(native) == ["lookup", "web_search"]


class TestWhatACallAnswers:
    @pytest.mark.asyncio
    async def test_a_denied_tool_answers_the_reason_and_is_not_run(self, gated, running):
        native = _native()
        _wrapped(native)
        running(_allowing("lookup", refund=REFUND_REASON))

        [answer] = await _answer(native, "refund")

        assert answer.behavior == {"type": "reject_content", "message": REFUND_REASON}

    @pytest.mark.asyncio
    async def test_an_allowed_tool_is_let_through(self, gated, running):
        native = _native()
        _wrapped(native)
        running(_allowing("lookup", refund=REFUND_REASON))

        [answer] = await _answer(native, "lookup")

        assert answer.behavior == {"type": "allow"}

    @pytest.mark.asyncio
    async def test_a_call_in_a_run_that_is_not_gated_is_let_through(self, gated, running):
        native = _native()
        _wrapped(native)
        running(None)

        assert [answer.behavior for answer in await _answer(native, "refund")] == [{"type": "allow"}]

    @pytest.mark.asyncio
    async def test_the_gate_runs_ahead_of_the_applications_own_guardrails_and_keeps_them(self, gated, running):
        own = ToolInputGuardrail(guardrail_function=lambda data: ToolGuardrailFunctionOutput.reject_content("not on a Sunday"), name="office_hours")
        native = _native(tools=[function_tool(refund, tool_input_guardrails=[own]), lookup])
        _wrapped(native)
        running(_allowing("lookup", "refund"))

        guardrails = _tool(native, "refund").tool_input_guardrails

        assert [guardrail.get_name() for guardrail in guardrails] == [OpenAIToolGate.GUARDRAIL_NAME, "office_hours"]
        assert [answer.behavior["type"] for answer in await _answer(native, "refund")] == ["allow", "reject_content"]


class TestWhereTheGateIsPut:
    def test_without_an_authorization_block_the_native_tools_are_left_as_they_are(self):
        native = _native()
        _wrapped(native)

        assert [(tool.is_enabled, tool.tool_input_guardrails) for tool in native.tools] == [(True, None), (True, None)]

    def test_with_the_block_every_function_tool_carries_it_once(self, gated):
        native = _native()
        _wrapped(native)
        _wrapped(native)  # the same native agent wrapped again (a module loaded twice in a test, a traced runner)

        for tool in native.tools:
            assert [guardrail.get_name() for guardrail in tool.tool_input_guardrails] == [OpenAIToolGate.GUARDRAIL_NAME]
            assert callable(tool.is_enabled)

    @pytest.mark.asyncio
    async def test_a_system_tool_attached_to_the_agent_is_gated(self, gated, running, monkeypatch):
        def analyze_attachments() -> str:
            """Analyze the attachments of this conversation."""
            return "none"

        system_tools = [SystemTool(name="analyze_attachments", description="", func=analyze_attachments)]
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: system_tools))
        native = _native(tools=[lookup])
        _wrapped(native)
        running(_allowing("lookup"))

        assert [tool.name for tool in native.tools] == ["lookup", "analyze_attachments"]
        assert await _offered(native) == ["lookup"]

    @pytest.mark.asyncio
    async def test_a_tool_attached_after_the_agent_was_wrapped_is_gated(self, gated, running):
        native = _native(tools=[lookup])
        wrapped = _wrapped(native)
        wrapped.attach_tool(refund)
        running(_allowing("lookup"))

        assert await _offered(native) == ["lookup"]


class TestAgentsARunCanReach:
    """A run of one agent can end up calling the tools of another: one it hands off to, or one it uses as a tool.
    The run's filter is the first agent's, so those tools are declared under it and carry the gate as well."""

    def test_the_tools_of_a_handoff_target_are_declared_after_the_agents_own(self, gated):
        billing = _native("billing", tools=[refund, invoice])
        triage = _wrapped(_native("triage", tools=[lookup], handoffs=[billing]))

        assert triage.get_tool_names() == ["lookup", "refund", "invoice"]
        assert triage.descriptor.tools == ["lookup", "refund", "invoice"]

    def test_a_handoff_object_is_followed_to_its_agent(self, gated):
        billing = _native("billing", tools=[refund])
        triage = _wrapped(_native("triage", tools=[lookup], handoffs=[handoff(billing)]))

        assert triage.get_tool_names() == ["lookup", "refund"]

    def test_the_tools_of_an_agent_used_as_a_tool_are_declared(self, gated):
        billing = _native("billing", tools=[refund])
        triage = _wrapped(_native("triage", tools=[lookup, billing.as_tool(tool_name="ask_billing", tool_description="Ask billing.")]))

        assert triage.get_tool_names() == ["lookup", "ask_billing", "refund"]

    def test_agents_that_hand_off_to_each_other_are_walked_once_and_a_name_is_declared_once(self, gated):
        billing = _native("billing", tools=[lookup, refund])
        triage = _native("triage", tools=[lookup], handoffs=[billing])
        billing.handoffs.append(triage)

        assert _wrapped(triage).get_tool_names() == ["lookup", "refund"]

    def test_each_reached_tool_carries_its_description(self, gated):
        billing = _native("billing", tools=[refund])
        triage = _wrapped(_native("triage", tools=[lookup], handoffs=[billing]))

        assert triage._tool_descriptions() == {"lookup": "Look an order up.", "refund": "Refund an order."}

    @pytest.mark.asyncio
    async def test_a_handoff_targets_tools_are_gated_by_the_run_that_reaches_them(self, gated, running):
        billing = _native("billing", tools=[refund, invoice])
        _wrapped(_native("triage", tools=[lookup], handoffs=[billing]))
        running(_allowing("lookup", "invoice", refund=REFUND_REASON))

        assert await _offered(billing) == ["invoice"]
        assert [answer.behavior["type"] for answer in await _answer(billing, "refund")] == ["reject_content"]

    @pytest.mark.asyncio
    async def test_the_tools_of_an_agent_used_as_a_tool_are_gated(self, gated, running):
        billing = _native("billing", tools=[refund, invoice])
        _wrapped(_native("triage", tools=[lookup, billing.as_tool(tool_name="ask_billing", tool_description="Ask billing.")]))
        running(_allowing("lookup", "ask_billing", "invoice", refund=REFUND_REASON))

        assert await _offered(billing) == ["invoice"]


class TestWhatCannotBeGated:
    """Tools the application bound that the adapter can neither declare nor gate: an MCP server lists its tools
    only once a run connects, and a handoff built by hand names its agent without holding it."""

    def test_an_agent_with_only_function_and_hosted_tools_has_none(self):
        assert _wrapped(_native(tools=[lookup, WebSearchTool()])).ungated_tool_names() == []

    @staticmethod
    def _local_tools() -> list:
        """The SDK tool types that run the application's own code in this process, where no gate reaches."""
        from agents import ApplyPatchTool, ComputerTool, CustomTool, LocalShellTool, ShellTool

        async def run_sql(context, text):
            return "rows"

        class Browser:
            environment, dimensions = "browser", (1024, 768)

        return [
            ShellTool(executor=lambda request: "ok"),
            LocalShellTool(executor=lambda request: "ok"),
            CustomTool(name="sql", description="Run SQL.", on_invoke_tool=run_sql),
            ApplyPatchTool(editor=object()),
            ComputerTool(computer=Browser()),
        ]

    def test_tools_the_sdk_runs_in_this_process_are_ungated_not_provider_run(self):
        # A local shell, a custom tool, an apply-patch editor, a computer: the application's code, run by the SDK
        # here, which asks no `is_enabled` and runs no input guardrail for them.
        wrapped = _wrapped(_native(tools=[lookup, *self._local_tools()]))

        assert wrapped.ungated_tool_names() == ["shell", "local_shell", "sql", "apply_patch", "computer_use_preview"]
        assert wrapped.provider_tool_names() == []

    @pytest.mark.parametrize("environment", [{"type": "container_auto"}, {"type": "container_reference", "container_id": "cntr_1"}])
    def test_a_shell_in_a_hosted_container_is_provider_run(self, environment):
        from agents import ShellTool

        wrapped = _wrapped(_native(tools=[lookup, ShellTool(environment=environment)]))

        assert (wrapped.ungated_tool_names(), wrapped.provider_tool_names()) == ([], ["shell"])

    def test_a_shell_in_an_environment_the_adapter_does_not_know_is_ungated(self):
        # Only the hosted environments the SDK defines are trusted: one added later may run in this process.
        from agents import ShellTool

        wrapped = _wrapped(_native(tools=[lookup, ShellTool(environment={"type": "container_gpu"})]))

        assert (wrapped.ungated_tool_names(), wrapped.provider_tool_names()) == (["shell"], [])

    def test_a_tool_type_the_adapter_does_not_know_is_ungated(self):
        # A tool type the SDK adds later is refused until it is classified, never trusted as the provider's.
        @dataclasses.dataclass
        class VideoGenerationTool:
            name: str = "video_generation"

        wrapped = _wrapped(_native(tools=[lookup, VideoGenerationTool()]))

        assert (wrapped.ungated_tool_names(), wrapped.provider_tool_names()) == (["video_generation"], [])

    def test_a_tool_with_no_name_is_refused_by_its_type_at_load(self, gated):
        # The refusal names the type, rather than the load failing on the missing attribute.
        @dataclasses.dataclass
        class Nameless:
            kind: str = "unknown"

        with Runtime(InMemorySessionStore()) as runtime:
            with pytest.raises(AKConfigError, match=r"cannot gate: \['Nameless'\]"):
                from agentkernel.framework.openai.openai import OpenAIModule

                OpenAIModule([_native(tools=[lookup, Nameless()])])
            assert runtime.agents() == {}

    def test_every_tool_type_the_sdk_defines_is_classified(self):
        # Fails when an `openai-agents` upgrade adds or removes a tool type. Classify a new one here: a type OpenAI
        # runs on its side goes into `OpenAIToolGate.HOSTED_TOOLS`; one the SDK runs in this process stays ungated.
        import agents
        from agents import ApplyPatchTool, ComputerTool, CustomTool, LocalShellTool, ShellTool

        from agentkernel.framework.openai.openai import OpenAIToolGate

        gated, local, by_environment = {FunctionTool}, {ApplyPatchTool, ComputerTool, CustomTool, LocalShellTool}, {ShellTool}
        defined = {typing.get_origin(member) or member for member in typing.get_args(agents.Tool)}

        assert defined == gated | set(OpenAIToolGate.HOSTED_TOOLS) | local | by_environment

    def test_an_agent_with_a_local_sdk_tool_does_not_load_under_the_block(self, gated):
        from agents import ShellTool

        native = _native(tools=[lookup, ShellTool(executor=lambda request: "ok")])

        with Runtime(InMemorySessionStore()) as runtime:
            with pytest.raises(AKConfigError, match=r"agent 'billing' on openai has tools Agent Kernel cannot gate: \['shell'\]"):
                from agentkernel.framework.openai.openai import OpenAIModule

                OpenAIModule([native])
            assert runtime.agents() == {}

    def test_hosted_tools_are_reported_as_run_by_the_provider(self):
        billing = _native("billing", tools=[refund, WebSearchTool()])
        triage = _wrapped(_native("triage", tools=[lookup], handoffs=[billing]))

        assert triage.provider_tool_names() == ["web_search"]
        assert _wrapped(_native(tools=[lookup, refund])).provider_tool_names() == []

    def test_an_mcp_server_is_named(self):
        native = _native(tools=[lookup], mcp_servers=[MCPServerStdio(params={"command": "true"}, name="files")])

        assert _wrapped(native).ungated_tool_names() == ["the tools of MCP server 'files' on agent 'billing'"]

    def test_an_mcp_server_of_an_agent_the_run_can_reach_is_named(self):
        billing = _native("billing", tools=[refund], mcp_servers=[MCPServerStdio(params={"command": "true"}, name="ledger")])
        triage = _wrapped(_native("triage", tools=[lookup], handoffs=[billing]))

        assert triage.ungated_tool_names() == ["the tools of MCP server 'ledger' on agent 'billing'"]

    def test_a_handoff_that_does_not_hold_its_agent_is_named(self):
        async def to_billing(run_context, arguments):
            return _native("billing", tools=[refund])

        by_hand = Handoff(
            tool_name="transfer_to_billing",
            tool_description="Hand off to billing.",
            input_json_schema={},
            on_invoke_handoff=to_billing,
            agent_name="billing",
        )
        triage = _wrapped(_native("triage", tools=[lookup], handoffs=[by_hand]))

        assert triage.ungated_tool_names() == ["the tools of agent 'billing', which agent 'triage' hands off to"]

    def test_such_an_agent_is_refused_when_authorization_is_configured(self, gated):
        native = _native(tools=[lookup], mcp_servers=[MCPServerStdio(params={"command": "true"}, name="files")])
        wrapped = _wrapped(native)

        with (
            Runtime(InMemorySessionStore()),
            pytest.raises(AKConfigError, match=r"agent 'billing' on openai has tools Agent Kernel cannot gate.*MCP server 'files'"),
        ):
            AccessGate.get().validate_configuration([wrapped], registry_wide=False)


class TestARunThroughRuntime:
    """The filter the access gate publishes for a run is the one the SDK's enablement check reads during it."""

    @staticmethod
    async def _run(authorization, tools_policy) -> tuple[list[str], dict]:
        seen: dict = {}

        async def native_run(agent, input_data, **kwargs):
            seen["offered"] = await _offered(agent)
            seen["kwargs"] = kwargs
            result = MagicMock()
            result.interruptions = []
            result.final_output = "done"
            return result

        if tools_policy is not None:
            authorization(grants=[{"subjects": ["group:support"], "agents": ["billing"], "level": "write"}], tools=tools_policy)
        runtime = Runtime(InMemorySessionStore())
        wrapped = _wrapped(_native())
        runtime.register(wrapped)
        with runtime, patch("agentkernel.framework.openai.openai.Runner") as native_runner:
            native_runner.run = AsyncMock(side_effect=native_run)
            session = runtime.sessions().new("s1")
            reply = await runtime.run(wrapped, session, [AgentRequestText(prompt="refund order 7")], principal=ALICE)
        assert str(reply) == "done"
        return seen["offered"], seen["kwargs"]

    @pytest.mark.asyncio
    async def test_the_principals_level_decides_what_the_model_is_offered(self, authorization):
        offered, _ = await self._run(authorization, [{"agent": "billing", "tiers": {"refund": "admin"}}])

        assert offered == ["lookup"]

    @pytest.mark.asyncio
    async def test_the_native_call_is_keyword_for_keyword_what_it_is_without_the_block(self, authorization):
        offered, without_the_block = await self._run(authorization, None)
        _, with_the_block = await self._run(authorization, [{"agent": "billing", "tiers": {"refund": "admin"}}])

        assert offered == ["lookup", "refund"]
        assert sorted(with_the_block) == sorted(without_the_block) == ["context", "session"]
