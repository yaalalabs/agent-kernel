"""The authorizer contract, the static backend and the factory that selects one (#603).

Nothing consults an authorizer yet: these tests drive it directly. `AuthorizerContract` holds what every
backend must answer; the rest is what only the static backend has (its grant grammar, its tool tiers, its
reasons), how it is built from its own `authorization.static` block, and how the factory builds an
authorizer from the `authorization` block alone.
"""

import threading

import pytest

from agentkernel.core.config import _AuthorizationConfig, _GrantConfig, _StaticAuthorizerConfig, _ToolPolicyConfig
from agentkernel.core.model import AccessLevel, AgentDescriptor, Principal, SystemTool
from agentkernel.core.registry import InMemoryAgentRegistry
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity.authz.base import Authorizer, AuthorizerCapabilities, Decision
from agentkernel.identity.authz.factory import AuthorizerFactory
from agentkernel.identity.authz.static import GrantTable, StaticAuthorizer, SubjectMatcher
from agentkernel.identity.authz.testing import AuthorizerContract
from agentkernel.identity.registry.testing import ContractAgent

READ, WRITE, ADMIN = AccessLevel.READ, AccessLevel.WRITE, AccessLevel.ADMIN

ALICE = Principal(subject="alice", provider="oidc", namespace="https://idp.example", groups=["support"], roles=["operator"])
ANONYMOUS = Principal.anonymous()


def _no_descriptors() -> list[AgentDescriptor]:
    return []


def _authorizer(grants=(), tools=(), descriptors=_no_descriptors, system_tiers=None) -> StaticAuthorizer:
    return StaticAuthorizer(grants=grants, tools=tools, descriptor_lookup=descriptors, system_tiers=system_tiers)


class TestStaticAuthorizerContract(AuthorizerContract):
    @pytest.fixture
    def authorizer(self):
        return StaticAuthorizer(grants=self.GRANTS, tools=self.TOOLS, descriptor_lookup=lambda: list(self.DESCRIPTORS))


class TestStaticAuthorizerContractFromConfig(AuthorizerContract):
    """The same policy read from an `authorization` block, the way a deployment states it."""

    @pytest.fixture
    def authorizer(self):
        block = _AuthorizationConfig.model_validate({"static": {"grants": self.GRANTS, "tools": self.TOOLS}})
        return StaticAuthorizer.from_config(block, descriptor_lookup=lambda: list(self.DESCRIPTORS), system_tiers=lambda agent_id: {})


class TestAuthorizerDefaults:
    """What a backend gets from the base class by answering only the two questions it must."""

    class _OnlyTheTwoQuestions(Authorizer):
        def __init__(self):
            self.asked: list[tuple[str, str, str | None]] = []

        async def agent_level(self, principal, agent_id):
            self.asked.append(("level", agent_id, None))
            return {"faq": READ, "billing": WRITE}.get(agent_id)

        async def check_tool(self, principal, agent_id, tool):
            self.asked.append(("tool", agent_id, tool))
            return Decision(allowed=tool.startswith("get_"), reason="" if tool.startswith("get_") else "not a read tool")

    def test_an_authorizer_must_answer_the_level_and_the_tool_question(self):
        with pytest.raises(TypeError):
            Authorizer()

    @pytest.mark.asyncio
    async def test_filter_tools_asks_check_tool_for_each_tool(self):
        authorizer = self._OnlyTheTwoQuestions()

        assert await authorizer.filter_tools(ALICE, "faq", ["get_a", "set_b", "get_c"]) == ["get_a", "get_c"]
        assert authorizer.asked == [("tool", "faq", "get_a"), ("tool", "faq", "set_b"), ("tool", "faq", "get_c")]

    @pytest.mark.asyncio
    async def test_visible_agents_are_the_candidates_with_a_level(self):
        authorizer = self._OnlyTheTwoQuestions()

        assert await authorizer.visible_agents(ALICE, ["billing", "ghost", "faq"]) == ["billing", "faq"]

    def test_a_backend_walks_the_candidates_unless_it_says_it_can_list(self):
        assert Authorizer.capabilities == AuthorizerCapabilities(lists_resources=False)
        assert StaticAuthorizer.capabilities.lists_resources is False

    def test_a_decision_needs_no_reason_to_allow(self):
        assert Decision(allowed=True).reason == ""


class TestSubjectMatcher:
    @pytest.mark.parametrize(
        "form, principal, expected",
        [
            ("*", ANONYMOUS, True),
            ("*", ALICE, True),
            ("authenticated", ALICE, True),
            ("authenticated", ANONYMOUS, False),
            ("user:alice", ALICE, True),
            ("user:bob", ALICE, False),
            ("group:support", ALICE, True),
            ("group:ops", ALICE, False),
            ("role:operator", ALICE, True),
            ("role:admin", ALICE, False),
            ("provider:oidc", ALICE, True),
            ("provider:oid", ALICE, False),
            ("provider:static", ALICE, False),
        ],
    )
    def test_each_form_matches_the_principals_it_names(self, form, principal, expected):
        assert SubjectMatcher.matches(form, principal) is expected

    def test_a_provider_name_ending_in_a_colon_matches_every_provider_under_it(self):
        slack = Principal(subject="U1", provider="messaging:slack", namespace="T1")
        livekit = Principal(subject="p1", provider="realtime:livekit", namespace="key")

        assert SubjectMatcher.matches("provider:messaging:", slack)
        assert SubjectMatcher.matches("provider:messaging:slack", slack)
        assert not SubjectMatcher.matches("provider:messaging:", livekit)
        assert not SubjectMatcher.matches("provider:messaging", slack)  # no colon: an exact name, which this is not

    def test_a_user_grant_never_matches_a_shared_channel_sender(self):
        # The subject of a messaging or realtime principal is a platform id, which the platform may not have
        # verified and which could collide with a configured subject.
        for provider in ("messaging:slack", "realtime:livekit"):
            assert not SubjectMatcher.matches("user:alice", Principal(subject="alice", provider=provider, namespace="scope"))

    def test_a_user_grant_never_matches_the_anonymous_principal(self):
        # The anonymous principal's subject is the word `anonymous`; a user of that name is somebody else.
        assert not SubjectMatcher.matches("user:anonymous", ANONYMOUS)
        assert SubjectMatcher.matches("user:anonymous", Principal(subject="anonymous", provider="oidc", namespace="https://idp.example"))

    def test_a_user_grant_matches_a_service_principal_the_same_way(self):
        service = Principal(subject="svc-reports", kind="service", provider="oidc", namespace="https://idp.example")

        assert SubjectMatcher.matches("user:svc-reports", service)

    @pytest.mark.parametrize("form", ["*", "authenticated", "user:alice", "group:support", "role:admin", "provider:oidc", "provider:messaging:"])
    def test_the_six_forms_are_valid(self, form):
        assert SubjectMatcher.is_valid(form)

    @pytest.mark.parametrize("form", ["", "alice", "team:support", "user:", "group:", "role:", "provider:", "Authenticated", "everyone"])
    def test_anything_else_is_not_a_subject(self, form):
        assert not SubjectMatcher.is_valid(form)

    def test_a_form_that_is_not_a_subject_matches_nobody(self):
        assert not SubjectMatcher.matches("team:support", ALICE)


class TestGrantTable:
    def test_a_grant_is_normalized_from_a_mapping(self):
        table = GrantTable([{"subjects": "group:support", "agents": "faq", "level": "write"}])

        [grant] = table.grants
        assert (grant.subjects, grant.agents, grant.level) == (["group:support"], ["faq"], WRITE)
        assert len(table) == 1

    def test_a_grant_from_the_configuration_block_is_taken_as_it_is(self):
        configured = _GrantConfig(subjects=["role:admin"], agents=["*"], level=ADMIN)

        assert GrantTable([configured]).grants == (configured,)

    def test_no_grants_is_an_empty_table(self):
        assert len(GrantTable([])) == 0

    @pytest.mark.parametrize(
        "grant, problem",
        [
            ({"subjects": "team:support", "agents": "faq", "level": "read"}, "team:support"),
            ({"subjects": ["group:support", "user:"], "agents": "faq", "level": "read"}, "user:"),
            ({"subjects": [], "agents": "faq", "level": "read"}, "subjects"),
            ({"subjects": "*", "agents": [], "level": "read"}, "agents"),
            ({"subjects": "*", "agents": "tag:", "level": "read"}, "tag:"),
            ({"subjects": "*", "agents": "", "level": "read"}, "agents"),
            ({"subjects": "*", "agents": "faq", "level": "owner"}, "level"),
            ({"subjects": "*", "agents": "faq"}, "level"),
            ({"subjects": "*", "agent": "faq", "agents": "faq", "level": "read"}, "agent"),
        ],
        ids=[
            "unknown-subject-form",
            "subject-form-with-no-name",
            "no-subjects",
            "no-agents",
            "tag-with-no-name",
            "empty-agent-id",
            "unknown-level",
            "no-level",
            "unknown-key",
        ],
    )
    def test_an_unusable_grant_is_a_configuration_error_naming_the_grant(self, grant, problem):
        usable = {"subjects": "*", "agents": "faq", "level": "read"}

        with pytest.raises(AKConfigError, match=r"authorization\.static\.grants\[1\]") as error:
            GrantTable([usable, grant])

        assert problem in str(error.value)

    def test_the_error_lists_the_forms_a_subject_may_take(self):
        with pytest.raises(AKConfigError, match="'authenticated'.*'user:<subject>'.*'group:<name>'.*'role:<name>'.*'provider:<name>'"):
            GrantTable([{"subjects": "support", "agents": "faq", "level": "read"}])


class TestStaticAgentLevels:
    """What the contract does not cover: the static backend's own corners."""

    @pytest.mark.asyncio
    async def test_a_wildcard_grant_covers_an_agent_the_registry_does_not_know(self):
        authorizer = _authorizer(grants=[{"subjects": "role:operator", "agents": "*", "level": "write"}])

        assert await authorizer.agent_level(ALICE, "not-registered-yet") == WRITE

    @pytest.mark.asyncio
    async def test_an_agent_id_is_matched_exactly(self):
        authorizer = _authorizer(grants=[{"subjects": "*", "agents": "Billing", "level": "read"}])

        assert await authorizer.agent_level(ALICE, "Billing") == READ
        assert await authorizer.agent_level(ALICE, "billing") is None

    @pytest.mark.asyncio
    async def test_a_tag_is_resolved_when_the_question_is_asked_not_when_the_authorizer_is_built(self):
        known: list[AgentDescriptor] = []
        authorizer = _authorizer(grants=[{"subjects": "*", "agents": "tag:support", "level": "read"}], descriptors=lambda: list(known))

        assert await authorizer.agent_level(ALICE, "billing") is None

        known.append(AgentDescriptor(id="billing", name="billing", tags=["support"]))

        assert await authorizer.agent_level(ALICE, "billing") == READ

    @pytest.mark.asyncio
    async def test_the_registry_is_not_read_when_no_grant_of_the_principal_selects_by_tag(self):
        reads = []

        def descriptors():
            reads.append(1)
            return [AgentDescriptor(id="billing", name="billing", tags=["support"])]

        authorizer = _authorizer(
            grants=[
                {"subjects": "group:support", "agents": "billing", "level": "write"},
                {"subjects": "role:admin", "agents": "tag:support", "level": "admin"},  # not a role alice holds
            ],
            descriptors=descriptors,
        )

        assert await authorizer.agent_level(ALICE, "billing") == WRITE
        assert reads == []

    @pytest.mark.asyncio
    async def test_the_registry_is_read_once_for_a_question_however_many_grants_select_by_tag(self):
        reads = []

        def descriptors():
            reads.append(1)
            return [AgentDescriptor(id="billing", name="billing", tags=["support", "finance"])]

        authorizer = _authorizer(
            grants=[
                {"subjects": "*", "agents": ["tag:support", "tag:frontline"], "level": "read"},
                {"subjects": "authenticated", "agents": "tag:finance", "level": "write"},
            ],
            descriptors=descriptors,
        )

        assert await authorizer.agent_level(ALICE, "billing") == WRITE
        assert reads == [1]

    @pytest.mark.asyncio
    async def test_a_registry_read_does_not_hold_the_event_loop(self):
        # Over a shared registry the listing is a blocking store read; it runs off the loop.
        loop_thread = threading.get_ident()
        read_on: list[int] = []

        def descriptors():
            read_on.append(threading.get_ident())
            return []

        authorizer = _authorizer(grants=[{"subjects": "*", "agents": "tag:support", "level": "read"}], descriptors=descriptors)

        await authorizer.agent_level(ALICE, "billing")

        assert read_on and read_on[0] != loop_thread

    @pytest.mark.asyncio
    async def test_a_listing_reads_the_registry_once_however_many_candidates_it_is_given(self):
        reads = []

        def descriptors():
            reads.append(1)
            return [AgentDescriptor(id=f"agent-{n}", name=f"agent-{n}", tags=["support"] if n % 2 else []) for n in range(6)]

        authorizer = _authorizer(grants=[{"subjects": "*", "agents": "tag:support", "level": "read"}], descriptors=descriptors)

        visible = await authorizer.visible_agents(ALICE, [f"agent-{n}" for n in range(6)])

        assert visible == ["agent-1", "agent-3", "agent-5"]
        assert reads == [1]

    @pytest.mark.asyncio
    async def test_a_listing_reads_nothing_for_a_principal_no_tag_grant_names(self):
        reads = []

        def descriptors():
            reads.append(1)
            return []

        authorizer = _authorizer(
            grants=[{"subjects": "role:admin", "agents": "tag:support", "level": "read"}, {"subjects": "*", "agents": "faq", "level": "read"}],
            descriptors=descriptors,
        )

        assert await authorizer.visible_agents(ALICE, ["faq", "billing"]) == ["faq"]
        assert reads == []


class TestStaticToolDecisions:
    GRANTS = [
        {"subjects": "group:support", "agents": "*", "level": "write"},
        {"subjects": "role:admin", "agents": "*", "level": "admin"},
    ]
    VIEWER = Principal(subject="vera", provider="oidc", namespace="https://idp.example")

    @pytest.mark.asyncio
    async def test_a_denied_tool_says_it_is_denied_for_the_agent(self):
        authorizer = _authorizer(self.GRANTS, tools=[{"agent": "support-triage", "deny": ["delete_ticket"]}])

        decision = await authorizer.check_tool(ALICE, "support-triage", "delete_ticket")

        assert decision == Decision(allowed=False, reason="Tool 'delete_ticket' is denied for agent 'support-triage'")

    @pytest.mark.asyncio
    async def test_a_tool_outside_the_allow_list_says_so(self):
        authorizer = _authorizer(self.GRANTS, tools=[{"agent": "support-triage", "allow": ["lookup_ticket"]}])

        decision = await authorizer.check_tool(ALICE, "support-triage", "create_ticket")

        assert decision == Decision(allowed=False, reason="Tool 'create_ticket' is not in the allow-list of agent 'support-triage'")

    @pytest.mark.asyncio
    async def test_a_tool_above_the_level_names_the_tier_and_the_level_held(self):
        authorizer = _authorizer(self.GRANTS, tools=[{"agent": "support-triage", "tiers": {"refund": "admin"}}])

        decision = await authorizer.check_tool(ALICE, "support-triage", "refund")

        assert decision == Decision(allowed=False, reason="Tool 'refund' requires level admin; the current principal has write")

    @pytest.mark.asyncio
    async def test_a_principal_with_no_level_is_told_it_has_none(self):
        authorizer = _authorizer(self.GRANTS)

        decision = await authorizer.check_tool(self.VIEWER, "support-triage", "lookup_ticket")

        assert decision == Decision(allowed=False, reason="Tool 'lookup_ticket' requires level read; the current principal has none")

    @pytest.mark.asyncio
    async def test_an_allowed_tool_carries_no_reason(self):
        assert await _authorizer(self.GRANTS).check_tool(ALICE, "support-triage", "lookup_ticket") == Decision(allowed=True)

    @pytest.mark.asyncio
    async def test_a_denial_is_reported_before_the_level_is_looked_at(self):
        # The same reason whoever asks: a denied tool is not something a higher level would unlock.
        authorizer = _authorizer(self.GRANTS, tools=[{"agent": "support-triage", "deny": ["delete_ticket"]}])

        decision = await authorizer.check_tool(self.VIEWER, "support-triage", "delete_ticket")

        assert decision.reason == "Tool 'delete_ticket' is denied for agent 'support-triage'"

    @pytest.mark.asyncio
    async def test_an_empty_allow_list_offers_no_tool(self):
        authorizer = _authorizer(self.GRANTS, tools=[{"agent": "support-triage", "allow": []}])

        assert await authorizer.filter_tools(ALICE, "support-triage", ["lookup_ticket", "create_ticket"]) == []

    @pytest.mark.asyncio
    async def test_a_policy_applies_to_its_own_agent_only(self):
        authorizer = _authorizer(self.GRANTS, tools=[{"agent": "support-triage", "tiers": {"export": "admin"}, "deny": ["purge"]}])

        assert await authorizer.filter_tools(ALICE, "billing", ["export", "purge"]) == ["export", "purge"]

    @pytest.mark.asyncio
    async def test_a_policy_from_the_configuration_block_is_taken_as_it_is(self):
        configured = _ToolPolicyConfig(agent="support-triage", tiers={"refund": ADMIN})

        decision = await _authorizer(self.GRANTS, tools=[configured]).check_tool(ALICE, "support-triage", "refund")

        assert not decision.allowed

    def test_two_policies_for_one_agent_are_a_configuration_error(self):
        # Which allow-list would win is not something to guess at.
        with pytest.raises(AKConfigError, match=r"authorization\.static\.tools\[1\].*'support-triage'"):
            _authorizer(self.GRANTS, tools=[{"agent": "support-triage"}, {"agent": "support-triage", "deny": ["purge"]}])

    def test_an_unusable_policy_is_a_configuration_error_naming_the_policy(self):
        with pytest.raises(AKConfigError, match=r"authorization\.static\.tools\[0\]"):
            _authorizer(self.GRANTS, tools=[{"agent": "support-triage", "tiers": {"refund": "owner"}}])


class TestSystemToolTiers:
    """A tool Agent Kernel attaches declares its own tier; the policy's `tiers` entry is the override."""

    GRANTS = [
        {"subjects": "authenticated", "agents": "*", "level": "read"},
        {"subjects": "group:support", "agents": "*", "level": "write"},
    ]
    READER = Principal(subject="rae", provider="oidc", namespace="https://idp.example")

    @staticmethod
    def _system_tiers(agent_id: str) -> dict[str, AccessLevel]:
        return {"execute_code": WRITE, "analyze_attachments": READ} if agent_id == "coder" else {}

    @pytest.mark.asyncio
    async def test_a_system_tool_keeps_the_tier_it_declares(self):
        authorizer = _authorizer(self.GRANTS, system_tiers=self._system_tiers)

        refused = await authorizer.check_tool(self.READER, "coder", "execute_code")

        assert refused == Decision(allowed=False, reason="Tool 'execute_code' requires level write; the current principal has read")
        assert (await authorizer.check_tool(self.READER, "coder", "analyze_attachments")).allowed
        assert (await authorizer.check_tool(ALICE, "coder", "execute_code")).allowed

    @pytest.mark.asyncio
    async def test_a_tiers_entry_overrides_the_declared_tier(self):
        policy = [{"agent": "coder", "tiers": {"execute_code": "read", "analyze_attachments": "admin"}}]
        authorizer = _authorizer(self.GRANTS, tools=policy, system_tiers=self._system_tiers)

        assert (await authorizer.check_tool(self.READER, "coder", "execute_code")).allowed
        assert not (await authorizer.check_tool(ALICE, "coder", "analyze_attachments")).allowed

    @pytest.mark.asyncio
    async def test_the_declared_tier_is_that_of_the_agent_asked_about(self):
        # An application tool of the same name on an agent that has no such system tool is a read tool.
        authorizer = _authorizer(self.GRANTS, system_tiers=self._system_tiers)

        assert (await authorizer.check_tool(self.READER, "reporter", "execute_code")).allowed

    @pytest.mark.asyncio
    async def test_a_tool_that_declares_nothing_is_a_read_tool(self):
        authorizer = _authorizer(self.GRANTS, system_tiers=self._system_tiers)

        assert (await authorizer.check_tool(self.READER, "coder", "lookup_ticket")).allowed

    @pytest.mark.asyncio
    async def test_filter_tools_asks_for_the_level_and_the_declared_tiers_once(self):
        asked: list[str] = []
        reads: list[int] = []

        def system_tiers(agent_id):
            asked.append(agent_id)
            return {"execute_code": WRITE}

        def descriptors():
            reads.append(1)
            return [AgentDescriptor(id="coder", name="coder", tags=["sandboxed"])]

        grants = [{"subjects": "authenticated", "agents": "tag:sandboxed", "level": "read"}]
        authorizer = _authorizer(grants, descriptors=descriptors, system_tiers=system_tiers)

        allowed = await authorizer.filter_tools(self.READER, "coder", ["lookup_ticket", "execute_code", "summarize"])

        assert allowed == ["lookup_ticket", "summarize"]
        assert (asked, reads) == (["coder"], [1])


class TestEmptyGrants:
    def test_a_block_with_no_grants_warns_once_that_every_agent_is_denied(self, caplog):
        with caplog.at_level("WARNING", logger="ak.identity.authz.static"):
            _authorizer(grants=[])

        [warning] = [record.getMessage() for record in caplog.records]
        assert "authorization.static.grants" in warning and "denied" in warning

    @pytest.mark.asyncio
    async def test_with_no_grants_nobody_holds_a_level_on_anything(self):
        authorizer = _authorizer(grants=[])

        assert await authorizer.agent_level(ALICE, "faq") is None
        assert await authorizer.agent_level(ANONYMOUS, "faq") is None
        assert not (await authorizer.check_tool(ALICE, "faq", "lookup")).allowed

    def test_a_block_with_grants_is_not_warned_about(self, caplog):
        with caplog.at_level("WARNING", logger="ak.identity.authz.static"):
            _authorizer(grants=[{"subjects": "*", "agents": "faq", "level": "read"}])

        assert [record.getMessage() for record in caplog.records] == []


class TestStaticFromConfig:
    """The static backend reads its policy from its own section of the block, `authorization.static`."""

    @pytest.mark.asyncio
    async def test_the_policy_is_the_static_section_of_the_block(self):
        block = _AuthorizationConfig.model_validate(
            {
                "static": {
                    "grants": [{"subjects": "group:support", "agents": "faq", "level": "write"}],
                    "tools": [{"agent": "faq", "deny": ["purge"]}],
                }
            }
        )

        authorizer = StaticAuthorizer.from_config(block, descriptor_lookup=_no_descriptors)

        assert await authorizer.agent_level(ALICE, "faq") == WRITE
        assert not (await authorizer.check_tool(ALICE, "faq", "purge")).allowed

    @pytest.mark.asyncio
    async def test_the_lookups_it_is_given_are_the_ones_it_asks(self):
        block = _AuthorizationConfig.model_validate({"static": {"grants": [{"subjects": "*", "agents": "tag:sandboxed", "level": "read"}]}})

        authorizer = StaticAuthorizer.from_config(
            block,
            descriptor_lookup=lambda: [AgentDescriptor(id="coder", name="coder", tags=["sandboxed"])],
            system_tiers=lambda agent_id: {"execute_code": WRITE},
        )

        assert await authorizer.agent_level(ALICE, "coder") == READ
        assert not (await authorizer.check_tool(ALICE, "coder", "execute_code")).allowed

    def test_a_block_with_no_static_section_is_a_configuration_error(self):
        # The configuration refuses this when it is loaded; a block built some other way is refused here.
        block = _AuthorizationConfig.model_construct(type="static", static=None)

        with pytest.raises(AKConfigError, match=r"authorization\.type static requires the authorization\.static block"):
            StaticAuthorizer.from_config(block, descriptor_lookup=_no_descriptors)

    def test_an_empty_static_section_is_a_policy_with_no_grants(self, caplog):
        with caplog.at_level("WARNING", logger="ak.identity.authz.static"):
            StaticAuthorizer.from_config(_AuthorizationConfig(static=_StaticAuthorizerConfig()), descriptor_lookup=_no_descriptors)

        assert ["authorization.static.grants is empty" in record.getMessage() for record in caplog.records] == [True]


class RecordingAuthorizer(Authorizer):
    """A bring-your-own authorizer: it is handed the whole `authorization` block."""

    def __init__(self, config):
        self.config = config

    async def agent_level(self, principal, agent_id):
        return ADMIN

    async def check_tool(self, principal, agent_id, tool):
        return Decision(allowed=True)


class NotAnAuthorizer:
    def __init__(self, config):
        pass


class TestAuthorizerFactory:
    @pytest.fixture(autouse=True)
    def _fresh_factory(self):
        AuthorizerFactory.reset()
        yield
        AuthorizerFactory.reset()

    @staticmethod
    def _configure(monkeypatch, authorization):
        class _Cfg:
            identity = None
            registry = None

        _Cfg.authorization = authorization
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))

    @pytest.mark.asyncio
    async def test_the_static_type_builds_the_static_authorizer_from_the_block(self):
        block = _AuthorizationConfig.model_validate(
            {
                "static": {
                    "grants": [{"subjects": "group:support", "agents": "faq", "level": "write"}],
                    "tools": [{"agent": "faq", "deny": ["purge"]}],
                }
            }
        )

        authorizer = AuthorizerFactory.create(block)

        assert isinstance(authorizer, StaticAuthorizer)
        assert await authorizer.agent_level(ALICE, "faq") == WRITE
        assert not (await authorizer.check_tool(ALICE, "faq", "purge")).allowed

    def test_the_type_is_matched_whatever_its_case(self):
        assert isinstance(AuthorizerFactory.create(_AuthorizationConfig(type="Static", static={})), StaticAuthorizer)

    @pytest.mark.asyncio
    async def test_a_static_authorizer_built_from_the_block_alone_reads_the_current_runtimes_registry(self):
        # The factory hands a backend the block and nothing else: what the static one looks up, it finds itself.
        block = _AuthorizationConfig.model_validate({"static": {"grants": [{"subjects": "*", "agents": "tag:support", "level": "write"}]}})
        registry = InMemoryAgentRegistry()
        registry.register(AgentDescriptor(id="billing", name="billing", tags=["support"]), ContractAgent("billing"))
        authorizer = AuthorizerFactory.create(block)

        with Runtime(InMemorySessionStore(), registry=registry):
            assert await authorizer.agent_level(ALICE, "billing") == WRITE

    @pytest.mark.parametrize("name", ["casbin", "openfga", "cedar", "authzen"])
    def test_a_reserved_engine_name_says_it_is_not_shipped_yet(self, name):
        with pytest.raises(AKConfigError, match=f"authorization.type: {name} is not shipped yet; use a dotted path"):
            AuthorizerFactory.create(_AuthorizationConfig(type=name))

    def test_a_dotted_path_builds_that_authorizer_with_the_whole_block(self):
        block = _AuthorizationConfig.model_validate({"type": f"{__name__}.RecordingAuthorizer", "endpoint": "https://pdp.acme.test"})

        authorizer = AuthorizerFactory.create(block)

        assert isinstance(authorizer, RecordingAuthorizer)
        assert authorizer.config is block
        assert authorizer.config.model_extra == {"endpoint": "https://pdp.acme.test"}

    def test_a_dotted_path_that_is_not_an_authorizer_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="not a Authorizer subclass"):
            AuthorizerFactory.create(_AuthorizationConfig(type=f"{__name__}.NotAnAuthorizer"))

    def test_a_dotted_path_that_cannot_be_imported_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="could not import"):
            AuthorizerFactory.create(_AuthorizationConfig(type="acme.authz.Missing"))

    def test_an_unknown_short_name_lists_what_is_available(self):
        with pytest.raises(AKConfigError, match="unknown authorization type 'rbac'.*static.*dotted path"):
            AuthorizerFactory.create(_AuthorizationConfig(type="rbac"))

    def test_an_unusable_policy_fails_when_the_authorizer_is_built(self):
        block = _AuthorizationConfig.model_validate({"static": {"grants": [{"subjects": "team:support", "agents": "faq", "level": "read"}]}})

        with pytest.raises(AKConfigError, match=r"authorization\.static\.grants\[0\]"):
            AuthorizerFactory.create(block)

    def test_get_is_none_without_an_authorization_block(self, monkeypatch):
        self._configure(monkeypatch, None)

        assert AuthorizerFactory.get() is None

    def test_get_builds_the_authorizer_once_and_reset_drops_it(self, monkeypatch):
        self._configure(monkeypatch, _AuthorizationConfig.model_validate({"static": {"grants": [{"subjects": "*", "agents": "*", "level": "read"}]}}))

        first = AuthorizerFactory.get()

        assert isinstance(first, StaticAuthorizer)
        assert AuthorizerFactory.get() is first
        AuthorizerFactory.reset()
        assert AuthorizerFactory.get() is not first

    def test_get_builds_one_authorizer_for_every_thread_that_asks_at_once(self, monkeypatch):
        self._configure(monkeypatch, _AuthorizationConfig.model_validate({"static": {"grants": [{"subjects": "*", "agents": "*", "level": "read"}]}}))
        built: list[Authorizer] = []
        start = threading.Barrier(8)

        def ask():
            start.wait()
            built.append(AuthorizerFactory.get())

        threads = [threading.Thread(target=ask) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(built) == 8 and len({id(authorizer) for authorizer in built}) == 1

    @pytest.mark.asyncio
    async def test_the_shared_authorizer_resolves_a_tag_against_the_current_runtimes_registry(self, monkeypatch):
        self._configure(
            monkeypatch, _AuthorizationConfig.model_validate({"static": {"grants": [{"subjects": "*", "agents": "tag:support", "level": "write"}]}})
        )
        registry = InMemoryAgentRegistry()
        registry.register(AgentDescriptor(id="billing", name="billing", tags=["support"]), ContractAgent("billing"))
        registry.register(AgentDescriptor(id="faq", name="faq"), ContractAgent("faq"))

        with Runtime(InMemorySessionStore(), registry=registry):
            authorizer = AuthorizerFactory.get()

            assert await authorizer.agent_level(ALICE, "billing") == WRITE
            assert await authorizer.agent_level(ALICE, "faq") is None

    @pytest.mark.asyncio
    async def test_the_shared_authorizer_follows_the_runtime_that_is_current_when_it_is_asked(self, monkeypatch):
        self._configure(
            monkeypatch, _AuthorizationConfig.model_validate({"static": {"grants": [{"subjects": "*", "agents": "tag:support", "level": "write"}]}})
        )
        tagged, untagged = InMemoryAgentRegistry(), InMemoryAgentRegistry()
        tagged.register(AgentDescriptor(id="billing", name="billing", tags=["support"]), ContractAgent("billing"))
        untagged.register(AgentDescriptor(id="billing", name="billing"), ContractAgent("billing"))
        authorizer = AuthorizerFactory.get()

        with Runtime(InMemorySessionStore(), registry=tagged):
            assert await authorizer.agent_level(ALICE, "billing") == WRITE
        with Runtime(InMemorySessionStore(), registry=untagged):
            assert await authorizer.agent_level(ALICE, "billing") is None

    @pytest.mark.asyncio
    async def test_the_shared_authorizer_reads_the_tier_a_system_tool_of_the_agent_declares(self, monkeypatch):
        self._configure(monkeypatch, _AuthorizationConfig.model_validate({"static": {"grants": [{"subjects": "*", "agents": "*", "level": "read"}]}}))

        def system_tools(agent_name=None):
            tool = SystemTool(name="execute_code", description="", func=lambda: None, tier=WRITE)
            return [tool] if agent_name == "coder" else []

        monkeypatch.setattr("agentkernel.core.tool.SystemToolFactory.get_all", staticmethod(system_tools))
        authorizer = AuthorizerFactory.get()

        assert not (await authorizer.check_tool(ALICE, "coder", "execute_code")).allowed
        assert (await authorizer.check_tool(ALICE, "reporter", "execute_code")).allowed


class TestExports:
    def test_the_identity_package_exports_the_authorizer_names(self):
        import agentkernel.identity as identity

        assert identity.Authorizer is Authorizer
        assert identity.AuthorizerCapabilities is AuthorizerCapabilities
        assert identity.Decision is Decision
        assert identity.AuthorizerFactory is AuthorizerFactory
        assert identity.StaticAuthorizer is StaticAuthorizer
        assert "AuthorizerContract" not in identity.__all__

    def test_importing_the_package_does_not_load_the_authorizers(self):
        import subprocess
        import sys

        code = "import sys, agentkernel.identity; print(any(name.startswith('agentkernel.identity.authz') for name in sys.modules))"
        loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()

        assert loaded == "False"
