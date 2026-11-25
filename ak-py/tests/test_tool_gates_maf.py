"""The Microsoft Agent Framework tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 21).

On a real `Agent` over a scripted chat client, so no model is called and what is asserted is what the function
loop ran and what the model received for each call. MAF has no list-time hook (the tool list is static on the
agent), so the gate is one function middleware added to a gated run.
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
from agentkernel.framework.maf.maf import AKToolGateMiddleware, MAFAgent, MAFRunner

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"
PROMPT = [AgentRequestText(prompt="refund order 7")]


class _CallsTools(FunctionInvocationLayer, ChatMiddlewareLayer, ChatTelemetryLayer, BaseChatClient):
    """Calls the tools the test names, once, then answers with what each call returned to it."""

    def __init__(self, calls: list[str], **kwargs):
        super().__init__(**kwargs)
        self.calls = calls

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if messages[-1].role == "tool":
            results = [content.result for content in messages[-1].contents if content.type == "function_result"]
            contents = [Content.from_text("model saw: " + " | ".join(str(result) for result in results))]
        else:
            contents = [Content.from_function_call(call_id=f"call_{name}", name=name, arguments=json.dumps({"order_id": "7"})) for name in self.calls]
        if stream:

            async def updates():
                yield ChatResponseUpdate(role="assistant", contents=contents, message_id="m1")

            return ResponseStream(updates(), finalizer=ChatResponse.from_updates)

        async def response():
            return ChatResponse(messages=[Message("assistant", contents)])

        return response()


class _Billing:
    """A real agent with a `lookup` and a `refund` tool that record their runs."""

    def __init__(self, calls: list[str], refund_needs_approval: bool = False):
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
        self.native = Agent(_CallsTools(calls), name="billing", instructions="Bill customers.", tools=tools)
        self.runner = MAFRunner()
        self.agent = MAFAgent("billing", self.runner, self.native)


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


class TestWhatACallAnswers:
    @pytest.mark.asyncio
    async def test_a_denied_tool_is_not_run_and_the_model_is_given_the_reason(self):
        billing = _Billing(["refund"])

        reply = await billing.runner.run(billing.agent, _session(_allowing("lookup", refund=REFUND_REASON)), PROMPT)

        assert billing.ran == []
        assert str(reply) == f"model saw: {REFUND_REASON}"

    @pytest.mark.asyncio
    async def test_an_allowed_tool_runs_beside_a_denied_one(self):
        billing = _Billing(["lookup", "refund"])

        reply = await billing.runner.run(billing.agent, _session(_allowing("lookup", refund=REFUND_REASON)), PROMPT)

        assert billing.ran == ["lookup"]
        assert str(reply) == f"model saw: order 7 | {REFUND_REASON}"

    @pytest.mark.asyncio
    async def test_a_tool_the_filter_never_listed_is_refused(self):
        billing = _Billing(["refund"])

        reply = await billing.runner.run(billing.agent, _session(_allowing("lookup")), PROMPT)

        assert billing.ran == []
        assert str(reply) == "model saw: Tool 'refund' is not available to the current principal"

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_runs_every_tool(self):
        billing = _Billing(["lookup", "refund"])

        reply = await billing.runner.run(billing.agent, _session(None), PROMPT)

        assert billing.ran == ["lookup", "refund"]
        assert str(reply) == "model saw: order 7 | refunded 7"

    @pytest.mark.asyncio
    async def test_a_streamed_run_is_gated_the_same(self):
        billing = _Billing(["lookup", "refund"])

        events = [event async for event in billing.runner.stream(billing.agent, _session(_allowing("lookup", refund=REFUND_REASON)), PROMPT)]

        assert events
        assert billing.ran == ["lookup"]

    @pytest.mark.asyncio
    async def test_a_call_approved_while_paused_is_refused_when_the_tool_is_denied_by_then(self):
        billing, session = _Billing(["refund"], refund_needs_approval=True), _session(_allowing("lookup", "refund"))
        paused = await billing.runner.run(billing.agent, session, PROMPT)
        assert isinstance(paused, AgentPausedReplyAny), paused
        record = PausedRunState.get(session, paused.run_id)
        decisions = [ResumeDecision(id=interruption.id, status="approved") for interruption in paused.interruptions]

        session._publish_run(ALICE, _allowing("lookup", refund=REFUND_REASON))
        reply = await billing.runner.resume(billing.agent, session, [AgentResumeRequestAny(decisions=decisions)], decisions, record)

        assert billing.ran == []
        assert str(reply) == f"model saw: {REFUND_REASON}"


class TestTheNativeCall:
    """The gate is one more middleware on a gated run, and nothing at all on any other."""

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

    @pytest.mark.asyncio
    async def test_a_run_that_is_not_gated_passes_no_middleware(self):
        kwargs = await self._native_kwargs(_Billing(["lookup"]), None)

        assert sorted(kwargs) == ["session"]

    @pytest.mark.asyncio
    async def test_a_gated_run_passes_the_gate_and_nothing_else_new(self):
        kwargs = await self._native_kwargs(_Billing(["lookup"]), _allowing("lookup"))

        assert sorted(kwargs) == ["middleware", "session"]
        assert [type(middleware) for middleware in kwargs["middleware"]] == [AKToolGateMiddleware]

    @pytest.mark.asyncio
    async def test_the_gate_goes_ahead_of_the_middleware_the_run_options_carry(self):
        class Own(FunctionMiddleware):
            def __init__(self):
                self.saw: list[str] = []

            async def process(self, context, call_next):
                self.saw.append(context.function.name)
                await call_next()

        billing, own = _Billing(["lookup", "refund"]), Own()
        billing.agent.run_options["middleware"] = [own]

        kwargs = await self._native_kwargs(billing, _allowing("lookup", refund=REFUND_REASON))

        assert [type(middleware) for middleware in kwargs["middleware"]] == [AKToolGateMiddleware, Own]
        assert own.saw == ["lookup"]  # the application's middleware never sees the call the gate refused
        assert billing.agent.run_options["middleware"] == [own]  # the declared options are not changed by a run


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

        assert billing.ran == ["lookup"]
        assert str(reply) == f"model saw: order 7 | {REFUND_REASON}"
