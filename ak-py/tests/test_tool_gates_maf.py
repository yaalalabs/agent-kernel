"""The Microsoft Agent Framework tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iterations 21 and 23).

On a real `Agent` over a scripted chat client, so no model is called and what is asserted is what the model was
offered, what the function loop ran and what the model received for each call. With an `authorization` block
the adapter puts two middleware first on the native agent: a chat middleware that leaves denied tools out of
what each request offers the model, and a function middleware that answers a call to a denied tool with the
reason. MAF runs the agent's own middleware ahead of any passed with a run, so that is where the gate goes.
"""

import json

import pytest
from agent_framework import (
    Agent,
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    FunctionInvocationLayer,
    FunctionMiddleware,
    Message,
    ResponseStream,
)
from agent_framework import tool as maf_tool
from agent_framework.observability import ChatTelemetryLayer

from agentkernel.core.base import Session
from agentkernel.core.model import AccessLevel, AgentPausedReplyAny, AgentRequestText, AgentResumeRequestAny, Principal, ResumeDecision, ToolFilter
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.framework.maf.maf import AKToolGateMiddleware, AKToolOfferMiddleware, MAFAgent, MAFRunner

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"
EVERYONE_WRITES = [{"subjects": ["*"], "agents": ["*"], "level": "write"}]
PROMPT = [AgentRequestText(prompt="refund order 7")]


class _CallsTools(FunctionInvocationLayer, ChatMiddlewareLayer, ChatTelemetryLayer, BaseChatClient):
    """Calls the tools the test names, once, then answers with what each call returned to it.

    It records the tools each request offered. `offered_only` makes it call only the named tools it was offered,
    as a model does; without it, it calls them whether offered or not, to reach the gate on a stray call.
    """

    def __init__(self, calls: list[str], offered_only: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.calls = calls
        self.offered_only = offered_only
        self.offered: list[list[str]] = []

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        offered = [tool.name for tool in options.get("tools") or [] if getattr(tool, "name", None)]
        self.offered.append(offered)
        calls = [name for name in self.calls if name in offered] if self.offered_only else self.calls
        if messages[-1].role == "tool" or not calls:
            results = [content.result for content in messages[-1].contents if content.type == "function_result"]
            contents = [Content.from_text("model saw: " + " | ".join(str(result) for result in results))]
        else:
            contents = [Content.from_function_call(call_id=f"call_{name}", name=name, arguments=json.dumps({"order_id": "7"})) for name in calls]
        if stream:

            async def updates():
                yield ChatResponseUpdate(role="assistant", contents=contents, message_id="m1")

            return ResponseStream(updates(), finalizer=ChatResponse.from_updates)

        async def response():
            return ChatResponse(messages=[Message("assistant", contents)])

        return response()


class _Billing:
    """A real agent with a `lookup` and a `refund` tool that record their runs."""

    def __init__(self, calls: list[str], *, refund_needs_approval: bool = False, offered_only: bool = False, middleware=None):
        self.ran: list[str] = []

        def lookup(order_id: str) -> str:
            """Look an order up."""
            self.ran.append("lookup")
            return f"order {order_id}"

        def refund(order_id: str) -> str:
            """Refund an order."""
            self.ran.append("refund")
            return f"refunded {order_id}"

        tools = [maf_tool(lookup), maf_tool(refund, approval_mode="always_require") if refund_needs_approval else maf_tool(refund)]
        self.client = _CallsTools(calls, offered_only=offered_only)
        self.native = Agent(self.client, name="billing", instructions="Bill customers.", tools=tools, middleware=middleware)
        self.runner = MAFRunner()
        self.agent = MAFAgent("billing", self.runner, self.native)


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


REFUND_DENIED = _allowing("lookup", refund=REFUND_REASON)


@pytest.fixture
def gated(authorization):
    """An `authorization` block is configured, which is when the adapter puts its gate on the native agent."""
    authorization(grants=EVERYONE_WRITES)


class _Own(FunctionMiddleware):
    """An application's own function middleware: records what it sees, and can answer without running the tool."""

    def __init__(self, answers: str | None = None):
        self.saw: list[str] = []
        self.answers = answers

    async def process(self, context, call_next):
        self.saw.append(context.function.name)
        if self.answers is not None:
            context.result = self.answers
            return
        await call_next()


class TestWhatTheModelIsOffered:
    @pytest.mark.asyncio
    async def test_a_denied_tool_is_left_out_of_every_request(self, gated):
        billing = _Billing(["lookup"], offered_only=True)

        await billing.runner.run(billing.agent, _session(REFUND_DENIED), PROMPT)

        assert billing.client.offered == [["lookup"], ["lookup"]]

    @pytest.mark.asyncio
    async def test_a_streamed_run_is_offered_the_same(self, gated):
        billing = _Billing(["lookup"], offered_only=True)

        [event async for event in billing.runner.stream(billing.agent, _session(REFUND_DENIED), PROMPT)]

        assert billing.client.offered[0] == ["lookup"]

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_is_offered_every_tool(self, gated):
        billing = _Billing(["lookup"], offered_only=True)

        await billing.runner.run(billing.agent, _session(None), PROMPT)

        assert billing.client.offered[0] == ["lookup", "refund"]

    @pytest.mark.asyncio
    async def test_a_denied_tool_that_needs_approval_is_not_offered_so_nobody_is_asked_to_approve_it(self, gated):
        # MAF asks for an approval before any function middleware runs: hiding the tool is what keeps a person from
        # being asked to approve a call the gate would refuse, and from seeing its arguments.
        billing = _Billing(["refund"], refund_needs_approval=True, offered_only=True)

        reply = await billing.runner.run(billing.agent, _session(REFUND_DENIED), PROMPT)

        assert not isinstance(reply, AgentPausedReplyAny)
        assert billing.client.offered[0] == ["lookup"]
        assert billing.ran == []


class TestWhatACallAnswers:
    """A model calls only what it is offered; these script a call to a denied tool all the same, to reach the gate."""

    @pytest.mark.asyncio
    async def test_a_denied_tool_is_not_run_and_the_model_is_given_the_reason(self, gated):
        billing = _Billing(["refund"])

        reply = await billing.runner.run(billing.agent, _session(REFUND_DENIED), PROMPT)

        assert billing.ran == []
        assert str(reply) == f"model saw: {REFUND_REASON}"

    @pytest.mark.asyncio
    async def test_an_allowed_tool_runs_beside_a_denied_one(self, gated):
        billing = _Billing(["lookup", "refund"])

        reply = await billing.runner.run(billing.agent, _session(REFUND_DENIED), PROMPT)

        assert billing.ran == ["lookup"]
        assert str(reply) == f"model saw: order 7 | {REFUND_REASON}"

    @pytest.mark.asyncio
    async def test_a_tool_the_filter_never_listed_is_refused(self, gated):
        billing = _Billing(["refund"])

        reply = await billing.runner.run(billing.agent, _session(_allowing("lookup")), PROMPT)

        assert billing.ran == []
        assert str(reply) == "model saw: Tool 'refund' is not available to the current principal"

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_runs_every_tool(self, gated):
        billing = _Billing(["lookup", "refund"])

        reply = await billing.runner.run(billing.agent, _session(None), PROMPT)

        assert billing.ran == ["lookup", "refund"]
        assert str(reply) == "model saw: order 7 | refunded 7"

    @pytest.mark.asyncio
    async def test_a_streamed_run_is_gated_the_same(self, gated):
        billing = _Billing(["lookup", "refund"])

        events = [event async for event in billing.runner.stream(billing.agent, _session(REFUND_DENIED), PROMPT)]

        assert events
        assert billing.ran == ["lookup"]

    @pytest.mark.asyncio
    async def test_a_call_approved_while_paused_is_refused_when_the_tool_is_denied_by_then(self, gated):
        billing, session = _Billing(["refund"], refund_needs_approval=True), _session(_allowing("lookup", "refund"))
        paused = await billing.runner.run(billing.agent, session, PROMPT)
        assert isinstance(paused, AgentPausedReplyAny), paused
        record = PausedRunState.get(session, paused.run_id)
        decisions = [ResumeDecision(id=interruption.id, status="approved") for interruption in paused.interruptions]

        session._publish_run(ALICE, REFUND_DENIED)
        reply = await billing.runner.resume(billing.agent, session, [AgentResumeRequestAny(decisions=decisions)], decisions, record)

        assert billing.ran == []
        assert str(reply) == f"model saw: {REFUND_REASON}"


class TestWhereTheGateIsPut:
    @staticmethod
    async def _native_kwargs(billing: _Billing, tool_filter: ToolFilter | None) -> dict:
        native_run = billing.native.run
        seen: dict = {}

        def spy(*args, **kwargs):
            seen.update(kwargs)
            return native_run(*args, **kwargs)

        billing.native.run = spy
        await billing.runner.run(billing.agent, _session(tool_filter), PROMPT)
        return seen

    def test_without_an_authorization_block_the_native_agent_is_left_as_it_is(self):
        billing = _Billing(["lookup"])

        assert billing.native.middleware is None

    def test_with_the_block_the_gate_is_first_among_the_agents_middleware_once(self, gated):
        own = _Own()
        billing = _Billing(["lookup"], middleware=[own])
        MAFAgent("billing", MAFRunner(), billing.native)  # the same native agent wrapped again

        assert [type(middleware) for middleware in billing.native.middleware] == [AKToolGateMiddleware, AKToolOfferMiddleware, _Own]
        assert billing.native.middleware[2] is own

    @pytest.mark.asyncio
    async def test_the_agents_own_middleware_never_sees_a_call_the_gate_refused(self, gated):
        # MAF runs the agent's own middleware ahead of any passed with the run; one that answers without running the
        # tool (a cache) would otherwise answer for a denied tool before the gate is asked.
        cache = _Own(answers="cached result")
        billing = _Billing(["refund"], middleware=[cache])

        reply = await billing.runner.run(billing.agent, _session(REFUND_DENIED), PROMPT)

        assert str(reply) == f"model saw: {REFUND_REASON}"
        assert cache.saw == []

    @pytest.mark.asyncio
    async def test_middleware_the_run_options_carry_runs_behind_the_gate(self, gated):
        billing, own = _Billing(["lookup", "refund"]), _Own()
        billing.agent.run_options["middleware"] = [own]

        await billing.runner.run(billing.agent, _session(REFUND_DENIED), PROMPT)

        assert own.saw == ["lookup"]
        assert billing.agent.run_options["middleware"] == [own]  # the declared options are not changed by a run

    @pytest.mark.asyncio
    async def test_the_native_call_is_keyword_for_keyword_what_it_is_without_the_block(self, gated):
        assert sorted(await self._native_kwargs(_Billing(["lookup"]), REFUND_DENIED)) == ["session"]
        assert sorted(await self._native_kwargs(_Billing(["lookup"]), None)) == ["session"]


class TestARunThroughRuntime:
    @pytest.mark.asyncio
    async def test_the_principals_level_decides_what_a_call_answers(self, authorization):
        authorization(
            grants=[{"subjects": ["group:support"], "agents": ["billing"], "level": "write"}],
            tools=[{"agent": "billing", "tiers": {"refund": "admin"}}],
        )
        billing, runtime = _Billing(["lookup", "refund"]), Runtime(InMemorySessionStore())
        runtime.register(billing.agent)

        with runtime:
            reply = await runtime.run(billing.agent, runtime.sessions().new("s1"), PROMPT, principal=ALICE)

        assert billing.client.offered[0] == ["lookup"]
        assert billing.ran == ["lookup"]
        assert str(reply) == f"model saw: order 7 | {REFUND_REASON}"
