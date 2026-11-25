"""The Claude Agent SDK tool gate (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 21).

The SDK runs its agent loop in a subprocess, so what the adapter controls is the `ClaudeAgentOptions` it hands a
run and the `PreToolUse` hook it installs in them. These tests assert both: the options a gated run is built
with (what the SDK may offer) and what the hook answers for a call (what it may run), through the runner's own
builders and through runs over a stand-in for `ClaudeSDKClient`.
"""

import pytest
from claude_agent_sdk import ClaudeAgentOptions, DeferredToolUse, HookMatcher, ResultMessage

import agentkernel.framework.claude.claude as claude_mod
from agentkernel.core.base import Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import AccessLevel, AgentRequestText, AgentResumeRequestAny, Principal, ResumeDecision, ToolFilter
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.framework.claude.claude import ClaudeAgentSpec, ClaudeModule, ClaudeRunner, ClaudeSession, ClaudeToolBuilder

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example", groups=["support"])
REFUND_REASON = "Tool 'refund' requires level admin; the current principal has write"
REFUND, LOOKUP = "mcp__ak__refund", "mcp__ak__lookup"
DENIED = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": REFUND_REASON}}
PROMPT = [AgentRequestText(prompt="refund order 7")]


def lookup(order_id: str) -> str:
    """Look an order up."""
    return f"order {order_id}"


def refund(order_id: str) -> str:
    """Refund an order."""
    return f"refunded {order_id}"


class FakeClient:
    """Stands in for ClaudeSDKClient: keeps the options each run was built with and replays a scripted reply."""

    instances: list["FakeClient"] = []
    script: list = []

    def __init__(self, options: ClaudeAgentOptions):
        self.options = options
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        if not isinstance(prompt, str):
            [message async for message in prompt]

    @property
    def session_id(self) -> str:
        return self.options.resume or self.options.session_id

    async def receive_response(self):
        for step in self.script:
            message = await step(self)
            if message is not None:
                yield message


def _result(client: FakeClient, **fields) -> ResultMessage:
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id=client.session_id, **{"result": "done", **fields}
    )


async def _finish(client: FakeClient) -> ResultMessage:
    await client.options.session_store.append({"project_key": "p", "session_id": client.session_id}, [{"type": "user", "uuid": "u1"}])
    return _result(client)


async def _defer_refund(client: FakeClient) -> ResultMessage:
    await client.options.session_store.append({"project_key": "p", "session_id": client.session_id}, [{"type": "user", "uuid": "tu-1"}])
    return _result(client, result=None, deferred_tool_use=DeferredToolUse(id="tu-1", name=REFUND, input={"order_id": "7"}))


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.instances = []
    FakeClient.script = [_finish]
    monkeypatch.setattr(claude_mod, "ClaudeSDKClient", FakeClient)
    return FakeClient


@pytest.fixture
def runtime():
    with Runtime(SessionStoreBuilder.build()) as current:
        yield current


def _billing(*, refund_needs_approval: bool = False, **options):
    spec = ClaudeAgentSpec(name="billing", description="Bills customers", options=ClaudeAgentOptions(**options))
    spec.tools = ClaudeToolBuilder.bind([lookup]) + ClaudeToolBuilder.bind([refund], needs_approval=refund_needs_approval)
    return ClaudeModule([spec]).get_agent("billing")


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _allowing(*names: str, **reasons: str) -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset(names), reasons=reasons)


REFUND_DENIED = _allowing("lookup", refund=REFUND_REASON)


def _options(agent, session: Session | None, **kwargs) -> ClaudeAgentOptions:
    return agent.runner._native_options(agent, {}, ClaudeSession(), stream=False, session=session, **kwargs)


def _hook(options: ClaudeAgentOptions):
    """The hook the adapter installed: the last `PreToolUse` matcher, behind any the application declared."""
    return options.hooks["PreToolUse"][-1].hooks[0]


class TestWhatARunMayOffer:
    def test_a_denied_tool_is_not_approved_and_is_disallowed(self, runtime):
        options = _options(_billing(), _session(REFUND_DENIED))

        assert options.allowed_tools == [LOOKUP]
        assert options.disallowed_tools == [REFUND]

    def test_a_tool_the_filter_never_listed_is_disallowed(self, runtime):
        options = _options(_billing(), _session(_allowing("refund")))

        assert options.allowed_tools == [REFUND]
        assert options.disallowed_tools == [LOOKUP]

    def test_a_denied_tool_the_application_approved_by_name_is_not_approved_for_the_run(self, runtime):
        agent = _billing(allowed_tools=["Read", REFUND], disallowed_tools=["Bash"])

        options = _options(agent, _session(REFUND_DENIED))

        assert options.allowed_tools == ["Read", LOOKUP]
        assert options.disallowed_tools == ["Bash", REFUND]
        assert agent.agent.options.allowed_tools == ["Read", REFUND]  # the declared options are not changed by a run
        assert agent.agent.options.disallowed_tools == ["Bash"]

    def test_a_tool_the_application_disallowed_itself_is_listed_once(self, runtime):
        options = _options(_billing(disallowed_tools=[REFUND]), _session(REFUND_DENIED))

        assert options.disallowed_tools == [REFUND]

    def test_only_the_tools_the_adapter_serves_are_gated(self, runtime):
        # Claude Code's built-in tools and another server's tools stay with the SDK's own permission settings.
        agent = _billing(allowed_tools=["Bash", "mcp__files__read"])

        options = _options(agent, _session(_allowing("lookup", "refund")))

        assert options.allowed_tools == ["Bash", "mcp__files__read", LOOKUP, REFUND]
        assert options.disallowed_tools == []

    @pytest.mark.parametrize(
        "session", [None, _session(None), _session(_allowing("lookup", "refund"))], ids=["no-session", "not-gated", "all-allowed"]
    )
    def test_a_run_in_which_nothing_is_denied_is_built_as_it_always_was(self, runtime, session):
        agent = _billing()

        options = _options(agent, session)

        assert options.allowed_tools == [LOOKUP, REFUND]
        assert options.disallowed_tools == []
        assert options.hooks is None


class TestWhatACallAnswers:
    @pytest.mark.asyncio
    async def test_a_call_to_a_denied_tool_is_denied_with_the_reason(self, runtime):
        hook = _hook(_options(_billing(), _session(REFUND_DENIED)))

        assert await hook({"tool_name": REFUND, "tool_input": {"order_id": "7"}}, "tu-1", {}) == DENIED
        assert await hook({"tool_name": LOOKUP, "tool_input": {"order_id": "7"}}, "tu-2", {}) == {}
        assert await hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, "tu-3", {}) == {}

    @pytest.mark.asyncio
    async def test_a_denied_tool_that_needs_approval_is_denied_and_never_pauses(self, runtime):
        hook = _hook(_options(_billing(refund_needs_approval=True), _session(REFUND_DENIED)))

        assert await hook({"tool_name": REFUND, "tool_input": {"order_id": "7"}}, "tu-1", {}) == DENIED

    @pytest.mark.asyncio
    async def test_an_allowed_tool_that_needs_approval_still_pauses(self, runtime):
        hook = _hook(
            _options(_billing(refund_needs_approval=True), _session(_allowing("refund", lookup="Tool 'lookup' is denied for agent 'billing'")))
        )

        assert await hook({"tool_name": REFUND, "tool_input": {}}, "tu-1", {}) == {
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "defer"}
        }

    @pytest.mark.asyncio
    async def test_an_approval_does_not_run_a_tool_the_filter_denies_by_then(self, runtime):
        approved = ("tu-1", ResumeDecision(id="tu-1", status="approved"))
        hook = _hook(_options(_billing(refund_needs_approval=True), _session(REFUND_DENIED), resume_decision=approved))

        assert await hook({"tool_name": REFUND, "tool_input": {"order_id": "7"}}, "tu-1", {}) == DENIED

    @pytest.mark.asyncio
    async def test_the_applications_own_hooks_are_kept_ahead_of_the_gate(self, runtime):
        async def audit(input_data, tool_use_id, context):
            return {}

        own = HookMatcher(matcher=None, hooks=[audit])
        options = _options(_billing(hooks={"PreToolUse": [own]}), _session(REFUND_DENIED))

        assert options.hooks["PreToolUse"][0] is own
        assert len(options.hooks["PreToolUse"]) == 2
        assert await _hook(options)({"tool_name": REFUND}, "tu-1", {}) == DENIED


class TestARun:
    """Every way a run starts hands its session to the options builder, so each is gated."""

    @pytest.mark.asyncio
    async def test_a_run_is_gated(self, fake_client, runtime):
        agent = _billing()

        await agent.runner.run(agent, _session(REFUND_DENIED), PROMPT)

        assert fake_client.instances[0].options.disallowed_tools == [REFUND]

    @pytest.mark.asyncio
    async def test_a_streamed_run_is_gated(self, fake_client, runtime):
        agent = _billing()

        [event async for event in agent.runner.stream(agent, _session(REFUND_DENIED), PROMPT)]

        assert fake_client.instances[0].options.disallowed_tools == [REFUND]

    @pytest.mark.parametrize("stream", [False, True], ids=["resume", "resume-stream"])
    @pytest.mark.asyncio
    async def test_a_resumed_run_is_gated_by_the_filter_of_the_resume(self, fake_client, runtime, stream):
        agent, session = _billing(refund_needs_approval=True), _session(_allowing("lookup", "refund"))
        fake_client.script = [_defer_refund]
        paused = await agent.runner.run(agent, session, PROMPT)
        record = PausedRunState.get(session, paused.run_id)
        decisions = [ResumeDecision(id=paused.interruptions[0].id, status="approved")]
        requests = [AgentResumeRequestAny(decisions=decisions)]
        answers = []

        async def call_refund(client):
            answers.append(await _hook(client.options)({"tool_name": REFUND, "tool_input": {"order_id": "7"}}, "tu-1", {}))

        fake_client.script = [call_refund, _finish]
        session._publish_run(ALICE, REFUND_DENIED)
        if stream:
            [event async for event in agent.runner.resume_stream(agent, session, requests, decisions, record)]
        else:
            await agent.runner.resume(agent, session, requests, decisions, record)

        assert fake_client.instances[1].options.disallowed_tools == [REFUND]
        assert answers == [DENIED]

    @pytest.mark.asyncio
    async def test_the_principals_level_decides_through_runtime(self, fake_client, authorization):
        authorization(
            grants=[{"subjects": ["group:support"], "agents": ["billing"], "level": "write"}],
            tools=[{"agent": "billing", "tiers": {"refund": "admin"}}],
        )
        with Runtime(SessionStoreBuilder.build()) as runtime:
            agent = _billing()
            reply = await runtime.run(agent, runtime.sessions().new("s1"), PROMPT, principal=ALICE)

        options = fake_client.instances[0].options
        assert str(reply) == "done"
        assert (options.allowed_tools, options.disallowed_tools) == ([LOOKUP], [REFUND])
        assert await _hook(options)({"tool_name": REFUND}, "tu-1", {}) == DENIED
