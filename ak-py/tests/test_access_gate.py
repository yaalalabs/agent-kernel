"""
The access gate (spec `docs/specs/603-identity-rbac-registry/` section 7, iteration 18).

One `AccessGate` sits over the agent registry and the configured authorizer and answers what a surface and
`Runtime` ask before anything runs: may this principal use the agent (and at what level), which agents may it
see, which of the agent's tools is it offered, may it continue this session, and does the policy fit the
agents the process hosts. This file covers the gate on its own, over a static policy and a runtime of the
test's own; `test_runtime_principal.py` covers `Runtime` consulting it, and the surfaces have their own files.
"""

import asyncio
import logging

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AccessLevel, AgentDescriptor, AgentReplyText, Principal, SessionOwner
from agentkernel.core.module import Module
from agentkernel.core.registry import AgentNotFoundError, InMemoryAgentRegistry
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity.authz.base import Authorizer, Decision
from agentkernel.identity.authz.factory import AuthorizerFactory
from agentkernel.identity.authz.gate import AccessGate
from agentkernel.identity.authz.static import StaticAuthorizer

READ, WRITE, ADMIN = AccessLevel.READ, AccessLevel.WRITE, AccessLevel.ADMIN

ISSUER = "https://issuer.example"
ALICE = Principal(subject="alice", provider="oidc", namespace=ISSUER, groups=["support"])
BOB = Principal(subject="bob", provider="oidc", namespace=ISSUER)
ANONYMOUS = Principal.anonymous()

# triage: private, write for the support group, with a tool policy. faq: internal, read for anyone signed in.
# billing: private, reached only through its tag. status: public and granted to nobody. staff: internal and
# granted to nobody. vault: private and granted to nobody.
GRANTS = [
    {"subjects": ["group:support"], "agents": ["triage"], "level": "write"},
    {"subjects": ["authenticated"], "agents": ["faq"], "level": "read"},
    {"subjects": ["user:alice"], "agents": ["tag:finance"], "level": "admin"},
]
TOOLS = [{"agent": "triage", "tiers": {"create": "write", "refund": "admin"}, "deny": ["purge"]}]


class _Runner(Runner):
    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Agent(Agent):
    """An agent reporting the tools it is built with, described by the fields it is given."""

    def __init__(self, name: str, tools=(), ungated=(), runner: str = "stub", provider_run=(), **described):
        super().__init__(name, _Runner(runner))
        self._tools = list(tools)
        self._ungated = list(ungated)
        self._provider_run = list(provider_run)
        if described:
            self._set_descriptor(self.descriptor.model_copy(update=described))

    def get_tool_names(self) -> list[str]:
        return list(self._tools)

    def ungated_tool_names(self) -> list[str]:
        return list(self._ungated)

    def provider_tool_names(self) -> list[str]:
        return list(self._provider_run)

    def get_description(self) -> str:
        return "the agent's instructions"

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


def _agents() -> list[_Agent]:
    return [
        _Agent("triage", tools=["lookup", "create", "refund", "purge"]),
        _Agent("faq", visibility="internal"),
        _Agent("billing", tools=["invoice"], tags=["finance"]),
        _Agent("status", visibility="public"),
        _Agent("staff", visibility="internal"),
        _Agent("vault"),
    ]


@pytest.fixture(autouse=True)
def _fresh_gate():
    AuthorizerFactory.reset()
    AccessGate.reset()
    yield
    AuthorizerFactory.reset()
    AccessGate.reset()


@pytest.fixture
def runtime():
    """The current runtime for the test, hosting the six agents the policy is written about."""
    runtime = Runtime(InMemorySessionStore())
    for agent in _agents():
        runtime.register(agent)
    with runtime:
        yield runtime


def _gate(grants=GRANTS, tools=TOOLS, **authorizer_options) -> AccessGate:
    """A gate over a static policy whose tags are resolved against whichever runtime is current."""
    lookup = lambda: Runtime.current().registry.descriptors()  # noqa: E731
    return AccessGate(StaticAuthorizer(grants=grants, tools=tools, descriptor_lookup=lookup, **authorizer_options))


class TestTheSharedGate:
    """`AccessGate.get()` is the enabled-check: None without an `authorization` block, one gate otherwise."""

    def test_there_is_no_gate_without_an_authorizer(self, monkeypatch):
        monkeypatch.setattr(AuthorizerFactory, "get", classmethod(lambda cls: None))

        assert AccessGate.get() is None

    def test_one_gate_is_shared_over_the_process_wide_authorizer(self, monkeypatch):
        authorizer = StaticAuthorizer(grants=GRANTS, tools=TOOLS, descriptor_lookup=list)
        monkeypatch.setattr(AuthorizerFactory, "get", classmethod(lambda cls: authorizer))

        gate = AccessGate.get()

        assert isinstance(gate, AccessGate) and AccessGate.get() is gate

    def test_an_authorizer_built_again_gets_a_gate_of_its_own(self, monkeypatch):
        # A test, or a configuration reload, resets the authorizer: a gate kept over the old one would decide by it.
        first = StaticAuthorizer(grants=GRANTS, tools=TOOLS, descriptor_lookup=list)
        second = StaticAuthorizer(grants=[], tools=[], descriptor_lookup=list)
        monkeypatch.setattr(AuthorizerFactory, "get", classmethod(lambda cls: first))
        over_first = AccessGate.get()
        monkeypatch.setattr(AuthorizerFactory, "get", classmethod(lambda cls: second))

        assert AccessGate.get() is not over_first

    def test_reset_drops_the_shared_gate(self, monkeypatch):
        authorizer = StaticAuthorizer(grants=GRANTS, tools=TOOLS, descriptor_lookup=list)
        monkeypatch.setattr(AuthorizerFactory, "get", classmethod(lambda cls: authorizer))
        gate = AccessGate.get()

        AccessGate.reset()

        assert AccessGate.get() is not gate


class TestAuthorizeAgent:
    """The level a principal holds on an agent, or the refusal: a 403 for an agent it may see, and the unknown
    agent's 404 for one it may not, so the answer never says that a hidden name exists."""

    def test_the_level_the_policy_gives_is_returned(self, runtime):
        gate = _gate()

        assert gate.authorize_agent(ALICE, "triage") == WRITE
        assert gate.authorize_agent(BOB, "faq") == READ
        assert gate.authorize_agent(ALICE, "billing") == ADMIN  # through its tag

    def test_an_agent_the_registry_does_not_know_is_not_found(self, runtime):
        with pytest.raises(AgentNotFoundError, match="^Agent 'ghost' not found$"):
            _gate().authorize_agent(ALICE, "ghost")

    def test_a_private_agent_the_principal_holds_no_level_on_is_the_unknown_agents_error(self, runtime):
        gate = _gate()

        with pytest.raises(AgentNotFoundError) as hidden:
            gate.authorize_agent(BOB, "vault")
        with pytest.raises(AgentNotFoundError) as unknown:
            gate.authorize_agent(BOB, "ghost")

        # One class and one text shape: nothing tells the caller that `vault` exists.
        assert str(hidden.value) == "Agent 'vault' not found"
        assert str(unknown.value) == "Agent 'ghost' not found"

    def test_a_public_agent_is_seen_by_everyone_and_refused_without_a_level(self, runtime):
        gate = _gate()

        for principal in (ANONYMOUS, BOB):
            with pytest.raises(PermissionError, match=f"^Principal '{principal.subject}' holds no level on agent 'status'$"):
                gate.authorize_agent(principal, "status")

    def test_an_internal_agent_is_seen_by_anyone_signed_in_and_hidden_from_the_anonymous_principal(self, runtime):
        gate = _gate()

        with pytest.raises(PermissionError, match="holds no level on agent 'staff'"):
            gate.authorize_agent(BOB, "staff")
        with pytest.raises(AgentNotFoundError, match="^Agent 'staff' not found$"):
            gate.authorize_agent(ANONYMOUS, "staff")

    def test_visibility_never_confers_a_level(self, runtime):
        # `faq` is internal and granted to `authenticated`: the anonymous principal neither sees nor uses it.
        with pytest.raises(AgentNotFoundError):
            _gate().authorize_agent(ANONYMOUS, "faq")

    def test_a_hosted_agent_is_decided_without_reading_the_registrys_store(self):
        class _HostedOnly(InMemoryAgentRegistry):
            def descriptor(self, id):
                raise AssertionError("the registry's store was read for an agent this process hosts")

        runtime = Runtime(InMemorySessionStore(), registry=_HostedOnly())
        runtime.register(_Agent("triage", tools=["lookup"]))

        with runtime:
            assert _gate().authorize_agent(ALICE, "triage") == WRITE

    def test_an_agent_another_process_hosts_is_decided_from_the_descriptor_the_registry_holds(self, descriptor_only_registry):
        registry = descriptor_only_registry(
            [AgentDescriptor(id="triage", name="triage"), AgentDescriptor(id="status", name="status", visibility="public")]
        )

        with Runtime(InMemorySessionStore(), registry=registry):
            gate = _gate()
            assert gate.authorize_agent(ALICE, "triage") == WRITE
            with pytest.raises(PermissionError):
                gate.authorize_agent(BOB, "status")
            with pytest.raises(AgentNotFoundError):
                gate.authorize_agent(BOB, "triage")

    def test_a_descriptor_the_caller_holds_is_decided_on_without_any_registry(self):
        # Runtime decides for the agent it was handed, which need not be registered in the current runtime.
        gate = _gate(grants=[{"subjects": ["user:alice"], "agents": ["solo"], "level": "read"}], tools=[])
        solo = AgentDescriptor(id="solo", name="solo")

        with Runtime(InMemorySessionStore()):
            assert gate.authorize_agent(ALICE, "solo", descriptor=solo) == READ
            with pytest.raises(AgentNotFoundError, match="^Agent 'solo' not found$"):
                gate.authorize_agent(BOB, "solo", descriptor=solo)

    @pytest.mark.asyncio
    async def test_the_async_twin_decides_the_same(self, runtime):
        gate = _gate()

        assert await gate.authorize_agent_async(ALICE, "triage") == WRITE
        with pytest.raises(PermissionError):
            await gate.authorize_agent_async(BOB, "status")
        with pytest.raises(AgentNotFoundError):
            await gate.authorize_agent_async(BOB, "vault")

    @pytest.mark.asyncio
    async def test_the_sync_form_answers_inside_a_running_event_loop(self, runtime):
        # `AgentHandler.initialize` is synchronous and is reached from `ChatService.execute`, a coroutine.
        gate = _gate()

        assert gate.authorize_agent(ALICE, "billing") == ADMIN  # the tag lookup awaits a worker thread
        with pytest.raises(AgentNotFoundError):
            gate.authorize_agent(BOB, "vault")

    @pytest.mark.asyncio
    async def test_every_other_sync_form_answers_inside_a_running_event_loop_as_its_async_twin(self, runtime):
        # A sync form that ran its coroutine itself, rather than through the gate's worker thread, would raise here.
        gate = _gate()
        descriptors = runtime.registry.descriptors()
        billing = runtime.registry.get("billing")

        assert gate.visible_agents(ALICE) == await gate.visible_agents_async(ALICE)
        assert gate.narrow(ALICE, descriptors) == await gate.narrow_async(ALICE, descriptors)
        assert gate.tool_filter(ALICE, billing) == await gate.tool_filter_async(ALICE, billing)
        assert gate.visible_agents(ALICE) != []  # the comparison is over real answers, not two empty ones


class TestVisibility:
    """Which agents a principal may see: those it holds a level on, public ones, and internal ones once signed in."""

    @pytest.mark.parametrize(
        "principal, visible",
        [
            (ALICE, ["billing", "faq", "staff", "status", "triage"]),
            (BOB, ["faq", "staff", "status"]),
            (ANONYMOUS, ["status"]),
        ],
        ids=["alice", "bob", "anonymous"],
    )
    def test_the_listing_is_the_agents_a_level_or_the_visibility_admits(self, runtime, principal, visible):
        assert sorted(descriptor.id for descriptor in _gate().visible_agents(principal)) == visible

    def test_one_agent_is_judged_by_the_same_rule(self, runtime):
        gate = _gate()
        described = {descriptor.id: descriptor for descriptor in runtime.registry.descriptors()}

        assert [gate.visible(BOB, described[name]) for name in ("faq", "staff", "status", "triage", "vault")] == [True, True, True, False, False]
        assert [gate.visible(ANONYMOUS, described[name]) for name in ("faq", "staff", "status")] == [False, False, True]
        # A private agent is seen by the principals a grant names, and by nobody else.
        assert [gate.visible(ALICE, described[name]) for name in ("triage", "billing", "vault")] == [True, True, False]

    def test_the_listing_asks_the_authorizer_once_for_the_whole_registry(self, runtime):
        class _Counting(Authorizer):
            def __init__(self):
                self.listings: list[list[str]] = []

            async def agent_level(self, principal, agent_id):
                raise AssertionError("each candidate was asked about in turn")

            async def check_tool(self, principal, agent_id, tool):
                return Decision(allowed=True)

            async def visible_agents(self, principal, candidates):
                self.listings.append(list(candidates))
                return ["triage"]

        authorizer = _Counting()

        visible = AccessGate(authorizer).visible_agents(BOB)

        assert sorted(descriptor.id for descriptor in visible) == ["faq", "staff", "status", "triage"]
        assert [sorted(candidates) for candidates in authorizer.listings] == [["billing", "faq", "staff", "status", "triage", "vault"]]

    def test_a_surface_can_list_among_the_agents_it_serves_without_reading_the_registry(self, descriptor_only_registry):
        """A surface that serves a fixed set (the agents it hosts, the cards it mounted) hands that set in: the
        authorizer is still asked once, and the registry's store is not listed again for it."""

        class _NotListed(descriptor_only_registry):
            def descriptors(self):
                raise AssertionError("the registry was listed although the candidates were handed in")

        served = [
            AgentDescriptor(id="triage", name="triage"),
            AgentDescriptor(id="status", name="status", visibility="public"),
            AgentDescriptor(id="vault", name="vault"),
        ]
        gate = AccessGate(StaticAuthorizer(grants=GRANTS, tools=TOOLS, descriptor_lookup=lambda: served))

        with Runtime(InMemorySessionStore(), registry=_NotListed([])):
            assert [descriptor.id for descriptor in gate.visible_agents(ALICE, served)] == ["triage", "status"]
            assert [descriptor.id for descriptor in gate.visible_agents(ANONYMOUS, served)] == ["status"]
            assert gate.visible_agents(ALICE, []) == []

    def test_agents_another_process_hosts_are_listed_from_the_registry(self, descriptor_only_registry):
        registry = descriptor_only_registry([AgentDescriptor(id="triage", name="triage"), AgentDescriptor(id="vault", name="vault")])

        with Runtime(InMemorySessionStore(), registry=registry):
            assert [descriptor.id for descriptor in _gate().visible_agents(ALICE)] == ["triage"]

    @pytest.mark.asyncio
    async def test_the_async_twins_answer_the_same(self, runtime):
        gate = _gate()
        status = runtime.registry.descriptor("status")

        assert sorted(descriptor.id for descriptor in await gate.visible_agents_async(BOB)) == ["faq", "staff", "status"]
        assert await gate.visible_async(ANONYMOUS, status) is True


class TestToolFilter:
    """The per-run tool decision: what the principal is offered at its level, and why each other tool is not."""

    def test_the_filter_carries_the_level_the_allowed_tools_and_a_reason_for_each_denied_one(self, runtime):
        tool_filter = _gate().tool_filter(ALICE, runtime.registry.get("triage"))

        assert tool_filter.level == WRITE
        assert tool_filter.allowed == frozenset({"lookup", "create"})
        assert tool_filter.reasons == {
            "refund": "Tool 'refund' requires level admin; the current principal has write",
            "purge": "Tool 'purge' is denied for agent 'triage'",
        }
        assert (tool_filter.allows("create"), tool_filter.allows("refund")) == (True, False)

    def test_an_agent_with_no_tool_policy_offers_every_tool_at_the_read_tier(self, runtime):
        tool_filter = _gate().tool_filter(ALICE, runtime.registry.get("billing"))

        assert (tool_filter.level, tool_filter.allowed, tool_filter.reasons) == (ADMIN, frozenset({"invoice"}), {})

    def test_an_agent_with_no_tools_has_an_empty_filter(self, runtime):
        tool_filter = _gate().tool_filter(BOB, runtime.registry.get("faq"))

        assert (tool_filter.level, tool_filter.allowed, tool_filter.reasons) == (READ, frozenset(), {})

    def test_a_tier_agent_kernels_own_tool_declares_is_applied(self, runtime):
        gate = _gate(
            grants=[{"subjects": ["user:bob"], "agents": ["triage"], "level": "read"}],
            tools=[],
            system_tiers=lambda agent_id: {"create": WRITE},
        )

        tool_filter = gate.tool_filter(BOB, runtime.registry.get("triage"))

        assert tool_filter.allowed == frozenset({"lookup", "refund", "purge"})
        assert tool_filter.reasons == {"create": "Tool 'create' requires level write; the current principal has read"}

    def test_a_level_the_caller_already_resolved_is_not_asked_for_again(self, runtime):
        class _OneLevelQuestion(StaticAuthorizer):
            asked = 0

            async def agent_level(self, principal, agent_id):
                type(self).asked += 1
                return await super().agent_level(principal, agent_id)

        gate = AccessGate(_OneLevelQuestion(grants=GRANTS, tools=[], descriptor_lookup=list))

        tool_filter = gate.tool_filter(BOB, runtime.registry.get("faq"), level=READ)

        # `faq` has no tools, so nothing but the level could have asked.
        assert (tool_filter.level, _OneLevelQuestion.asked) == (READ, 0)

    def test_a_principal_with_no_level_has_no_filter(self, runtime):
        with pytest.raises(PermissionError, match="^Principal 'bob' holds no level on agent 'triage'$"):
            _gate().tool_filter(BOB, runtime.registry.get("triage"))

    @pytest.mark.asyncio
    async def test_the_async_twin_builds_the_same_filter(self, runtime):
        gate = _gate()
        triage = runtime.registry.get("triage")

        assert await gate.tool_filter_async(ALICE, triage) == await asyncio.to_thread(gate.tool_filter, ALICE, triage)


def _session(owner: SessionOwner | None = None) -> Session:
    session = Session("s1")
    if owner is not None:
        session._record_owner(owner)
    return session


class TestNarrow:
    """A descriptor as one principal is shown it: the tools it is offered, and the skills that go with them. What
    a surface lists (the catalog, and in iteration 20 an A2A card) never names a tool the caller would be denied."""

    @staticmethod
    def _triage() -> AgentDescriptor:
        skills = [
            {"id": "lookup", "name": "lookup"},
            {"id": "create", "name": "create"},
            {"id": "refund", "name": "refund"},
            {"id": "purge", "name": "purge"},
            {"id": "ticket-triage", "name": "Ticket triage", "description": "Sorts incoming tickets."},
        ]
        return AgentDescriptor(id="triage", name="triage", tools=["lookup", "create", "refund", "purge"], skills=skills, owner="support")

    def test_the_tools_are_the_ones_the_principal_is_offered(self, runtime):
        # alice holds write on triage: `refund` is tiered admin and `purge` is denied to everyone.
        [shown] = _gate().narrow(ALICE, [self._triage()])

        assert shown.tools == ["lookup", "create"]

    def test_a_skill_backed_by_a_tool_goes_with_it_and_a_declared_one_stays(self, runtime):
        [shown] = _gate().narrow(ALICE, [self._triage()])

        assert [skill.id for skill in shown.skills] == ["lookup", "create", "ticket-triage"]

    def test_nothing_else_about_the_agent_changes(self, runtime):
        descriptor = self._triage()

        [shown] = _gate().narrow(ALICE, [descriptor])

        assert shown.model_dump(exclude={"tools", "skills"}) == descriptor.model_dump(exclude={"tools", "skills"})
        assert descriptor.tools == ["lookup", "create", "refund", "purge"]  # the registry's record is not touched

    def test_a_principal_that_only_sees_the_agent_is_offered_no_tool(self, runtime):
        # Visibility lists an agent; it never confers a level, so there is no tool to offer.
        public = self._triage().model_copy(update={"visibility": "public"})

        [shown] = _gate().narrow(BOB, [public])

        assert (shown.tools, [skill.id for skill in shown.skills]) == ([], ["ticket-triage"])

    def test_an_agent_with_no_tools_costs_no_question(self, runtime):
        asked = []

        class _Counting(StaticAuthorizer):
            async def filter_tools(self, principal, agent_id, tools):
                asked.append(agent_id)
                return await super().filter_tools(principal, agent_id, tools)

        gate = AccessGate(_Counting(grants=GRANTS, tools=TOOLS, descriptor_lookup=lambda: Runtime.current().registry.descriptors()))

        shown = gate.narrow(ALICE, [AgentDescriptor(id="faq", name="faq"), self._triage()])

        assert ([descriptor.id for descriptor in shown], asked) == (["faq", "triage"], ["triage"])

    def test_the_order_handed_in_is_kept(self, runtime):
        billing = AgentDescriptor(id="billing", name="billing", tools=["invoice"], tags=["finance"])

        shown = _gate().narrow(ALICE, [self._triage(), billing])

        assert [(descriptor.id, descriptor.tools) for descriptor in shown] == [("triage", ["lookup", "create"]), ("billing", ["invoice"])]

    @pytest.mark.asyncio
    async def test_the_async_form_answers_inside_a_coroutine(self, runtime):
        [shown] = await _gate().narrow_async(ALICE, [self._triage()])

        assert shown.tools == ["lookup", "create"]


class TestAuthorizeSession:
    """A session belongs to the principal that first ran in it; a shared-channel session to its platform scope."""

    OWNED_BY_ALICE = SessionOwner(subject="alice", provider="oidc", namespace=ISSUER)
    SLACK_THREAD = SessionOwner(subject="U1", provider="messaging:slack", namespace="T1")

    def test_a_session_nobody_owns_is_open_to_anyone(self):
        gate = _gate()

        gate.authorize_session(ALICE, _session())
        gate.authorize_session(ANONYMOUS, _session())

    def test_the_owner_continues_its_session(self):
        _gate().authorize_session(ALICE, _session(self.OWNED_BY_ALICE))

    def test_the_owner_is_recognised_by_namespace_and_subject_not_by_its_provider_name(self):
        # The same person signing in through a second provider entry of one issuer is the same owner.
        through_another_entry = ALICE.model_copy(update={"provider": "entra"})

        _gate().authorize_session(through_another_entry, _session(self.OWNED_BY_ALICE))

    @pytest.mark.parametrize(
        "principal",
        [BOB, ALICE.model_copy(update={"namespace": "https://other.example"}), ANONYMOUS],
        ids=["another-subject", "same-subject-another-namespace", "anonymous"],
    )
    def test_anyone_else_is_refused(self, principal):
        with pytest.raises(PermissionError, match="^Session 's1' belongs to another principal$"):
            _gate().authorize_session(principal, _session(self.OWNED_BY_ALICE))

    def test_a_shared_channel_session_admits_another_sender_of_its_platform_scope(self):
        colleague = Principal(subject="U2", provider="messaging:slack", namespace="T1")

        _gate().authorize_session(colleague, _session(self.SLACK_THREAD))

    @pytest.mark.parametrize(
        "principal",
        [
            Principal(subject="U2", provider="messaging:slack", namespace="T2"),
            Principal(subject="U1", provider="messaging:teams", namespace="T1"),
            Principal(subject="U1", provider="oidc", namespace="T1"),
            ANONYMOUS,
        ],
        ids=["another-workspace", "another-platform", "a-rest-caller-with-the-senders-id", "anonymous"],
    )
    def test_a_shared_channel_session_refuses_everyone_outside_that_scope(self, principal):
        # Someone who learned a Slack conversation's session id cannot continue it over REST.
        with pytest.raises(PermissionError, match="belongs to another principal"):
            _gate().authorize_session(principal, _session(self.SLACK_THREAD))

    def test_a_realtime_session_is_bound_to_its_scope_the_same_way(self):
        room = SessionOwner(subject="caller-1", provider="realtime:livekit", namespace="lk-project")

        _gate().authorize_session(Principal(subject="caller-2", provider="realtime:livekit", namespace="lk-project"), _session(room))
        with pytest.raises(PermissionError):
            _gate().authorize_session(Principal(subject="caller-1", provider="realtime:livekit", namespace="other"), _session(room))


LOGGER = "ak.identity.authz.gate"


def _warnings(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER and record.levelno == logging.WARNING]


class TestValidateConfiguration:
    """A policy that cannot work for a hosted agent stops the process at startup; one that merely matches
    nothing yet is warned about once."""

    def test_a_policy_that_fits_the_hosted_agents_passes_in_silence(self, runtime, caplog):
        gate = _gate(grants=[{"subjects": ["group:support"], "agents": ["triage", "tag:finance"], "level": "write"}])

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            gate.validate_configuration(runtime.agents().values())

        assert _warnings(caplog) == []

    @pytest.mark.parametrize(
        "policy, named",
        [
            ({"agent": "triage", "allow": ["lookup", "looukp"]}, "allow ['looukp']"),
            ({"agent": "triage", "deny": ["purge_all"]}, "deny ['purge_all']"),
            ({"agent": "triage", "tiers": {"refnd": "admin"}}, "tiers ['refnd']"),
        ],
        ids=["allow", "deny", "tiers"],
    )
    def test_a_tool_policy_naming_a_tool_the_agent_does_not_have_is_refused(self, runtime, policy, named):
        gate = _gate(tools=[{"agent": "billing", "allow": ["invoice"]}, policy])

        with pytest.raises(AKConfigError) as refused:
            gate.validate_configuration(runtime.agents().values())

        # Names the setting, the agent, the entry and what the agent does have: a misspelt deny would deny nothing.
        message = str(refused.value)
        assert "authorization.static.tools[1]" in message and "agent 'triage'" in message and named in message
        assert "['create', 'lookup', 'purge', 'refund']" in message

    def test_a_tool_policy_for_an_agent_this_process_does_not_host_is_left_alone(self, runtime):
        # Another process hosts it and checks it: here there are no tools to compare the policy with.
        gate = _gate(tools=[{"agent": "remote", "deny": ["anything"]}])

        gate.validate_configuration(runtime.agents().values())

    def test_only_the_agents_handed_in_are_checked(self, runtime):
        gate = _gate(tools=[{"agent": "triage", "deny": ["no-such-tool"]}])

        gate.validate_configuration([runtime.registry.get("billing")])

    def test_an_agent_with_tools_agent_kernel_cannot_gate_is_refused(self, runtime):
        runtime.register(_Agent("graph", tools=["search"], ungated=["native_search", "browse"], runner="langgraph"))

        with pytest.raises(AKConfigError) as refused:
            _gate().validate_configuration(runtime.agents().values())

        assert str(refused.value) == (
            "authorization is configured but agent 'graph' on langgraph has tools Agent Kernel cannot gate: ['browse', 'native_search']"
        )

    def test_tools_the_provider_runs_are_warned_about_once_and_not_refused(self, runtime, caplog):
        # The design's Q12: a framework's hosted or built-in tools are run where no gate reaches, and no
        # deployment can rebind them, so they are reported and the agent still loads.
        runtime.register(_Agent("researcher", tools=["lookup", "web_search"], runner="openai", provider_run=["web_search", "file_search"]))
        gate = _gate()

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            gate.validate_configuration(runtime.agents().values(), registry_wide=False)
            gate.validate_configuration(runtime.agents().values(), registry_wide=False)

        assert _warnings(caplog) == [
            "agent 'researcher' on openai has tools its model provider or framework runs itself, which the authorization tool "
            "policy does not reach: ['file_search', 'web_search']"
        ]

    def test_an_agent_with_no_such_tool_is_not_warned_about(self, runtime, caplog):
        runtime.register(_Agent("plain", tools=["lookup"]))

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _gate().validate_configuration(runtime.agents().values(), registry_wide=False)

        assert _warnings(caplog) == []

    def test_a_grant_naming_an_agent_or_a_tag_nothing_carries_is_warned_about(self, runtime, caplog):
        gate = _gate(
            grants=[
                {"subjects": ["user:alice"], "agents": ["triage", "trige"], "level": "read"},
                {"subjects": ["user:alice"], "agents": ["tag:finance", "tag:finanse", "*"], "level": "read"},
            ]
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            gate.validate_configuration(runtime.agents().values())

        warnings = _warnings(caplog)
        assert len(warnings) == 2
        assert "authorization.static.grants[0]" in warnings[0] and "agent 'trige'" in warnings[0]
        assert "authorization.static.grants[1]" in warnings[1] and "tag 'finanse'" in warnings[1]

    def test_a_role_subject_without_a_role_mapper_is_warned_about(self, runtime, caplog):
        grants = [{"subjects": ["role:admin", "group:support"], "agents": ["triage"], "level": "admin"}]

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _gate(grants=grants, roles_mapped=lambda: False).validate_configuration(runtime.agents().values())
            unmapped = _warnings(caplog)
            caplog.clear()
            _gate(grants=grants, roles_mapped=lambda: True).validate_configuration(runtime.agents().values())
            mapped = _warnings(caplog)

        assert len(unmapped) == 1 and "'role:admin'" in unmapped[0] and "identity.role_mapper" in unmapped[0]
        assert mapped == []

    def test_each_finding_is_warned_about_once(self, runtime, caplog):
        gate = _gate(grants=[{"subjects": ["user:alice"], "agents": ["trige"], "level": "read"}])

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            gate.validate_configuration(runtime.agents().values())
            gate.validate_configuration(runtime.agents().values())

        assert len(_warnings(caplog)) == 1

    def test_a_module_that_is_one_of_several_skips_what_needs_every_agent_registered(self, runtime, caplog):
        # `Module.load` validates as it loads: the agents of a module loaded later are not in the registry yet.
        gate = _gate(
            grants=[{"subjects": ["role:admin"], "agents": ["loaded-later", "tag:later"], "level": "read"}],
            tools=[{"agent": "triage", "deny": ["no-such-tool"]}],
            roles_mapped=lambda: False,
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            with pytest.raises(AKConfigError, match="no-such-tool"):
                gate.validate_configuration(runtime.agents().values(), registry_wide=False)
            gate.validate_configuration([runtime.registry.get("billing")], registry_wide=False)

        # The role finding needs no registry and is still made; the two that do are left for the full check.
        warnings = _warnings(caplog)
        assert len(warnings) == 1 and "'role:admin'" in warnings[0]

    def test_a_backend_with_nothing_to_compare_validates_nothing(self, runtime, caplog):
        class _Engine(Authorizer):
            async def agent_level(self, principal, agent_id):
                return READ

            async def check_tool(self, principal, agent_id, tool):
                return Decision(allowed=True)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            AccessGate(_Engine()).validate_configuration(runtime.agents().values())

        assert _warnings(caplog) == []


class TestTheAvailabilityCheckAsksTheGate:
    """`AgentService.ensure_agent_available(name, principal)` is where a surface learns, before it commits
    anything, that the caller may not have the agent. It asks the gate after the registry and the surface, so
    an unknown agent, one kept off the surface and one the caller may not see are one answer."""

    @pytest.fixture(autouse=True)
    def _policy(self, authorization):
        authorization(grants=GRANTS, tools=TOOLS)

    @pytest.mark.parametrize("hosted", [False, True], ids=["registry-wide", "hosted"])
    def test_a_principal_with_a_level_passes(self, runtime, hosted):
        from agentkernel.core.service import AgentService

        AgentService.ensure_agent_available("triage", ALICE, hosted=hosted)
        AgentService.ensure_agent_available("faq", BOB, hosted=hosted, surface="rest")

    @pytest.mark.parametrize("hosted", [False, True], ids=["registry-wide", "hosted"])
    def test_an_agent_the_principal_may_not_see_is_the_unknown_agent(self, runtime, hosted):
        from agentkernel.core.service import AgentService

        with pytest.raises(AgentNotFoundError) as hidden:
            AgentService.ensure_agent_available("vault", BOB, hosted=hosted)
        with pytest.raises(AgentNotFoundError) as unknown:
            AgentService.ensure_agent_available("ghost", BOB, hosted=hosted)

        assert (str(hidden.value), str(unknown.value)) == ("Agent 'vault' not found", "Agent 'ghost' not found")

    def test_an_agent_the_principal_may_see_and_not_use_is_forbidden(self, runtime):
        from agentkernel.core.service import AgentService

        with pytest.raises(PermissionError, match="^Principal 'bob' holds no level on agent 'status'$"):
            AgentService.ensure_agent_available("status", BOB, hosted=True)

    def test_a_caller_that_names_no_principal_is_the_anonymous_one(self, runtime):
        # What Runtime would run it as: a surface that forgets the principal refuses, it does not let through.
        from agentkernel.core.service import AgentService

        with pytest.raises(AgentNotFoundError, match="^Agent 'triage' not found$"):
            AgentService.ensure_agent_available("triage", hosted=True)
        with pytest.raises(PermissionError, match="^Principal 'anonymous' holds no level on agent 'status'$"):
            AgentService.ensure_agent_available("status")

    def test_the_surface_is_decided_before_the_gate(self, runtime, monkeypatch):
        from agentkernel.core.service import AgentService

        runtime.registry.get("triage")._set_descriptor(runtime.registry.get("triage").descriptor.model_copy(update={"surfaces": ["a2a"]}))
        monkeypatch.setattr(AccessGate, "authorize_agent", lambda *args, **kwargs: pytest.fail("the gate was asked about an agent off the surface"))

        with pytest.raises(AgentNotFoundError, match="^Agent 'triage' not found$"):
            AgentService.ensure_agent_available("triage", ALICE, hosted=True, surface="rest")

    def test_an_agent_another_process_hosts_is_decided_from_the_registry(self, descriptor_only_registry):
        from agentkernel.core.service import AgentService

        registry = descriptor_only_registry([AgentDescriptor(id="triage", name="triage"), AgentDescriptor(id="vault", name="vault")])

        with Runtime(InMemorySessionStore(), registry=registry):
            AgentService.ensure_agent_available("triage", ALICE)
            with pytest.raises(AgentNotFoundError, match="^Agent 'vault' not found$"):
                AgentService.ensure_agent_available("vault", ALICE)

    def test_a_request_naming_no_agent_needs_the_default_agent_like_any_other(self, runtime):
        # Where the agent runs the default is known: the first agent hosted, `triage` here.
        from agentkernel.core.service import AgentService

        AgentService.ensure_agent_available(None, ALICE, hosted=True)

    def test_a_default_agent_the_caller_may_not_see_is_no_agent_at_all(self, runtime):
        # Not the 404 that would name it: the caller gave no name, and learns none.
        from agentkernel.core.service import AgentService

        with pytest.raises(ValueError, match="^No agent available$"):
            AgentService.ensure_agent_available(None, BOB, hosted=True)

    def test_a_default_agent_the_caller_may_see_and_not_use_is_forbidden(self, runtime):
        from agentkernel.core.service import AgentService

        runtime.deregister(runtime.registry.get("triage"))
        runtime.deregister(runtime.registry.get("faq"))
        runtime.deregister(runtime.registry.get("billing"))  # `status`, public and granted to nobody, is now first

        with pytest.raises(PermissionError, match="^Principal 'bob' holds no level on agent 'status'$"):
            AgentService.ensure_agent_available(None, BOB, hosted=True)

    def test_an_edge_does_not_decide_for_a_default_it_cannot_know(self, runtime):
        # The registry-wide form: whichever process runs the request picks the default, and decides there.
        from agentkernel.core.service import AgentService

        AgentService.ensure_agent_available(None, BOB)

    def test_without_an_authorization_block_nobody_is_asked(self, runtime, monkeypatch):
        from agentkernel.core.config import AKConfig
        from agentkernel.core.service import AgentService

        monkeypatch.setattr(AKConfig.get(), "authorization", None)

        AgentService.ensure_agent_available("vault", BOB, hosted=True)
        AgentService.ensure_agent_available(None, hosted=True)


class _Module(Module):
    """Loads agents that are already built, standing in for a framework module."""

    def __init__(self, agents):
        super().__init__()
        self.load(agents)

    def _wrap(self, agent, agents):
        return agent

    def load(self, agents):
        return super().load(agents)


class TestModuleLoadValidatesThePolicy:
    """`Module.load` asks the gate about the agents it has just registered, so a policy that cannot hold for
    one of them stops the process where the agent is declared, and leaves nothing registered behind."""

    def _load(self, agents) -> tuple[Runtime, _Module | None, Exception | None]:
        runtime = Runtime(InMemorySessionStore())
        with runtime:
            try:
                return runtime, _Module(agents), None
            except Exception as error:
                return runtime, None, error

    def test_a_policy_that_fits_loads(self, authorization):
        authorization(grants=GRANTS, tools=TOOLS)

        runtime, module, error = self._load([_Agent("triage", tools=["lookup", "create", "refund", "purge"])])

        assert error is None and sorted(runtime.agents()) == ["triage"]

    def test_a_tool_policy_naming_a_tool_the_agent_does_not_have_fails_the_load_and_registers_nothing(self, authorization):
        authorization(grants=GRANTS, tools=[{"agent": "triage", "deny": ["purge_everything"]}])

        runtime, _, error = self._load([_Agent("faq"), _Agent("triage", tools=["lookup", "purge"])])

        assert isinstance(error, AKConfigError) and "purge_everything" in str(error)
        # The agent that loaded cleanly before it is rolled back as well: a module loads whole or not at all.
        assert runtime.agents() == {}

    def test_an_agent_with_tools_that_cannot_be_gated_fails_the_load(self, authorization):
        authorization(grants=GRANTS)

        runtime, _, error = self._load([_Agent("graph", tools=["search"], ungated=["native_search"], runner="smolagents")])

        assert isinstance(error, AKConfigError)
        assert "agent 'graph' on smolagents has tools Agent Kernel cannot gate: ['native_search']" in str(error)
        assert runtime.agents() == {}

    def test_a_grant_for_an_agent_of_a_module_loaded_later_is_not_warned_about(self, authorization, caplog):
        authorization(grants=[{"subjects": ["authenticated"], "agents": ["faq", "triage", "tag:finance"], "level": "read"}])

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            runtime = Runtime(InMemorySessionStore())
            with runtime:
                _Module([_Agent("faq")])
                _Module([_Agent("triage"), _Agent("billing", tags=["finance"])])

        assert _warnings(caplog) == []
        assert sorted(runtime.agents()) == ["billing", "faq", "triage"]

    def test_without_an_authorization_block_nothing_is_validated(self):
        runtime, _, error = self._load([_Agent("graph", tools=["search"], ungated=["native_search"], runner="langgraph")])

        assert error is None and sorted(runtime.agents()) == ["graph"]


class TestTheConfiguredGate:
    """The gate as a configured process builds it: the real factory and the static backend with the lookups it
    supplies itself, so what Agent Kernel's own tools declare and what the `identity` block says reach a decision."""

    def test_a_tool_agent_kernel_tiers_write_is_kept_from_a_principal_held_to_read(self, authorization, monkeypatch):
        from agentkernel.core.model import SystemTool
        from agentkernel.core.tool import SystemToolFactory

        attached = [
            SystemTool(name="create_schedule", description="", func=print, tier=WRITE),
            SystemTool(name="analyze_attachments", description="", func=print),
        ]
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: attached if agent_name == "planner" else []))
        authorization(
            grants=[
                {"subjects": ["user:bob"], "agents": ["planner"], "level": "read"},
                {"subjects": ["group:support"], "agents": ["planner"], "level": "write"},
            ]
        )
        planner = _Agent("planner", tools=["lookup", "create_schedule", "analyze_attachments"])

        held_to_read = AccessGate.get().tool_filter(BOB, planner)
        may_write = AccessGate.get().tool_filter(ALICE, planner)

        assert held_to_read.allowed == frozenset({"lookup", "analyze_attachments"})
        assert held_to_read.reasons == {"create_schedule": "Tool 'create_schedule' requires level write; the current principal has read"}
        assert may_write.allowed == frozenset({"lookup", "create_schedule", "analyze_attachments"})

    def test_a_policy_tier_overrides_the_one_the_tool_declares(self, authorization, monkeypatch):
        from agentkernel.core.model import SystemTool
        from agentkernel.core.tool import SystemToolFactory

        monkeypatch.setattr(
            SystemToolFactory,
            "get_all",
            staticmethod(lambda agent_name=None: [SystemTool(name="create_schedule", description="", func=print, tier=WRITE)]),
        )
        authorization(
            grants=[{"subjects": ["user:bob"], "agents": ["planner"], "level": "read"}],
            tools=[{"agent": "planner", "tiers": {"create_schedule": "read"}}],
        )

        assert AccessGate.get().tool_filter(BOB, _Agent("planner", tools=["create_schedule"])).allowed == frozenset({"create_schedule"})

    def test_a_role_subject_is_warned_about_only_while_the_identity_block_maps_no_roles(self, authorization, monkeypatch, caplog):
        from agentkernel.core.config import (
            AKConfig,
            _IdentityConfig,
            _IdentityProviderConfig,
            _RoleMapperConfig,
            _StaticPrincipalConfig,
            _StaticProviderConfig,
        )

        grants = [{"subjects": ["role:admin"], "agents": ["*"], "level": "admin"}]
        provider = _IdentityProviderConfig(
            type="static", static=_StaticProviderConfig(principals={"ALICE_TOKEN": _StaticPrincipalConfig(subject="alice")})
        )

        with Runtime(InMemorySessionStore()), caplog.at_level(logging.WARNING, logger=LOGGER):
            monkeypatch.setattr(AKConfig.get(), "identity", _IdentityConfig(provider=provider))
            authorization(grants=grants)
            AccessGate.get().validate_configuration([])
            without_a_mapper = _warnings(caplog)
            caplog.clear()

            mapped = _IdentityConfig(provider=provider, role_mapper=_RoleMapperConfig(mapping={"ops": ["admin"]}))
            monkeypatch.setattr(AKConfig.get(), "identity", mapped)
            authorization(grants=grants)
            AccessGate.get().validate_configuration([])
            with_a_mapper = _warnings(caplog)

        assert len(without_a_mapper) == 1 and "'role:admin'" in without_a_mapper[0]
        assert with_a_mapper == []

    @staticmethod
    def _hosting_billing() -> tuple[Runtime, _Agent]:
        """A runtime hosting `billing`, tagged `finance`, over a registry that fails the test if it is listed."""

        class _NeverListed(InMemoryAgentRegistry):
            def descriptors(self):
                raise AssertionError("the registry was listed for the tags of an agent this process hosts")

        billing = _Agent("billing", tools=["invoice", "refund"], tags=["finance"])
        runtime = Runtime(InMemorySessionStore(), registry=_NeverListed())
        runtime.register(billing)
        return runtime, billing

    TAG_POLICY = {
        "grants": [{"subjects": ["user:alice"], "agents": ["tag:finance"], "level": "write"}],
        "tools": [{"agent": "billing", "tiers": {"refund": "admin"}}],
    }

    def test_a_tag_grant_decides_a_run_of_a_hosted_agent_without_listing_the_registry(self, authorization):
        # Over a shared registry a listing is a scan of the store. A run is of a hosted agent, whose tags are its
        # own descriptor's: the check before the run, the gate's decision and the run's tool filter list nothing.
        from agentkernel.core.service import AgentService

        authorization(**self.TAG_POLICY)
        runtime, billing = self._hosting_billing()

        with runtime:
            AgentService.ensure_agent_available("billing", ALICE, hosted=True)
            level = AccessGate.get().authorize_agent(ALICE, "billing")
            tool_filter = AccessGate.get().tool_filter(ALICE, billing, level)

        assert level == WRITE
        assert tool_filter.allowed == frozenset({"invoice"})
        assert tool_filter.reasons == {"refund": "Tool 'refund' requires level admin; the current principal has write"}

    @pytest.mark.asyncio
    async def test_the_check_before_a_run_holds_the_event_loop_for_no_store_read(self, authorization):
        # `ChatService.execute` reaches the synchronous check from the server's loop, which waits for the answer:
        # for a hosted agent that answer takes no read of the registry.
        from agentkernel.core.service import AgentService

        authorization(**self.TAG_POLICY)
        runtime, _ = self._hosting_billing()

        with runtime:
            AgentService.ensure_agent_available("billing", ALICE, hosted=True)
            with pytest.raises(AgentNotFoundError, match="^Agent 'billing' not found$"):
                AgentService.ensure_agent_available("billing", BOB, hosted=True)
