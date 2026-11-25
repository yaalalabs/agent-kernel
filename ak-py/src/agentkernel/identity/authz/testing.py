"""Public testing helpers for authorizers. Imports pytest, so import from test code only."""

from typing import Any, ClassVar

import pytest

from ...core.model import AccessLevel, AgentDescriptor, Principal
from .base import Authorizer


class AuthorizerContract:
    """Conformance suite every Authorizer subclasses. Override the ``authorizer`` fixture.

    Not prefixed ``Test`` so pytest does not collect it on its own. The suite states one policy
    (``GRANTS`` and ``TOOLS``, over the agents in ``DESCRIPTORS``) in the static backend's terms, and
    asserts what each principal below may do under it. A backend that keeps its policy somewhere else
    (a policy engine, a relationship store) loads the equivalent policy in its fixture; the assertions
    stay as they are.

    What the policy says:

    - An admin role holds ``admin`` on every agent, an operator role ``write`` on the Kubernetes agent.
    - Two groups hold ``write`` on the support agent and the FAQ agent.
    - Every authenticated caller holds ``read`` on the support agent, and everyone (anonymous callers
      included) ``read`` on the FAQ agent.
    - The user ``dave`` holds ``write`` on the agents tagged ``support``; callers the ``oidc`` provider
      authenticated hold ``read`` on the agents tagged ``ops``; every messaging sender holds ``read`` on
      the billing agent; and a grant on a tag no agent carries gives nobody anything.
    - The support agent tiers three tools and denies one; the Kubernetes agent has an allow-list, one
      entry of which it also denies.
    """

    DESCRIPTORS: ClassVar[list[AgentDescriptor]] = [
        AgentDescriptor(id="faq", name="faq", tags=["frontline"]),
        AgentDescriptor(id="support-triage", name="support-triage", tags=["frontline", "support"]),
        AgentDescriptor(id="billing", name="billing", tags=["support"]),
        AgentDescriptor(id="k8s-troubleshooter", name="k8s-troubleshooter", tags=["ops"]),
    ]
    AGENT_IDS: ClassVar[list[str]] = ["faq", "support-triage", "billing", "k8s-troubleshooter"]

    GRANTS: ClassVar[list[dict[str, Any]]] = [
        {"subjects": "role:admin", "agents": "*", "level": "admin"},
        {"subjects": "role:operator", "agents": "k8s-troubleshooter", "level": "write"},
        {"subjects": ["group:support", "group:cx"], "agents": ["support-triage", "faq"], "level": "write"},
        {"subjects": "authenticated", "agents": "support-triage", "level": "read"},
        {"subjects": "*", "agents": "faq", "level": "read"},
        {"subjects": "user:dave", "agents": "tag:support", "level": "write"},
        {"subjects": "provider:messaging:", "agents": "billing", "level": "read"},
        {"subjects": "provider:oidc", "agents": "tag:ops", "level": "read"},
        {"subjects": "*", "agents": "tag:retired", "level": "admin"},
    ]
    TOOLS: ClassVar[list[dict[str, Any]]] = [
        {
            "agent": "support-triage",
            "tiers": {"lookup_ticket": "read", "create_ticket": "write", "refund": "admin"},
            "deny": ["delete_ticket"],
        },
        {
            "agent": "k8s-troubleshooter",
            "tiers": {"kubectl_apply": "write"},
            "allow": ["kubectl_get", "kubectl_apply", "kubectl_exec"],
            "deny": ["kubectl_exec"],
        },
    ]

    ANONYMOUS: ClassVar[Principal] = Principal.anonymous()
    # Authenticated, and nothing else: no group, no role.
    ERIN: ClassVar[Principal] = Principal(subject="erin", provider="oidc", namespace="https://idp.example")
    DAVE: ClassVar[Principal] = Principal(subject="dave", provider="static", namespace="static")
    BOB: ClassVar[Principal] = Principal(subject="bob", provider="static", namespace="static", groups=["support"])
    ALICE: ClassVar[Principal] = Principal(
        subject="alice", provider="oidc", namespace="https://idp.example", groups=["sre-oncall"], roles=["operator"]
    )
    CAROL: ClassVar[Principal] = Principal(subject="carol", provider="static", namespace="static", roles=["admin"])
    # A Slack sender whose platform id happens to be the subject a user grant names.
    SLACK_DAVE: ClassVar[Principal] = Principal(subject="dave", provider="messaging:slack", namespace="T123")
    # A provider whose name only starts like another's.
    OIDC_LOOKALIKE: ClassVar[Principal] = Principal(subject="mallory", provider="oidc-staging", namespace="https://staging.example")

    PRINCIPALS: ClassVar[list[Principal]] = [ANONYMOUS, ERIN, DAVE, BOB, ALICE, CAROL, SLACK_DAVE, OIDC_LOOKALIKE]

    READ: ClassVar[AccessLevel] = AccessLevel.READ
    WRITE: ClassVar[AccessLevel] = AccessLevel.WRITE
    ADMIN: ClassVar[AccessLevel] = AccessLevel.ADMIN

    @pytest.fixture
    def authorizer(self) -> Authorizer:
        """The authorizer under contract, holding the policy above; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `authorizer` fixture")

    async def _levels(self, authorizer: Authorizer, principal: Principal) -> dict[str, AccessLevel | None]:
        return {agent_id: await authorizer.agent_level(principal, agent_id) for agent_id in self.AGENT_IDS}

    async def _allowed(self, authorizer: Authorizer, principal: Principal, agent_id: str, tools: list[str]) -> dict[str, bool]:
        return {tool: (await authorizer.check_tool(principal, agent_id, tool)).allowed for tool in tools}

    # Agent levels: the subject forms

    @pytest.mark.asyncio
    async def test_contract_everyone_includes_the_anonymous_principal(self, authorizer):
        assert await authorizer.agent_level(self.ANONYMOUS, "faq") == self.READ

    @pytest.mark.asyncio
    async def test_contract_the_anonymous_principal_holds_only_what_everyone_holds(self, authorizer):
        assert await self._levels(authorizer, self.ANONYMOUS) == {
            "faq": self.READ,
            "support-triage": None,
            "billing": None,
            "k8s-troubleshooter": None,
        }

    @pytest.mark.asyncio
    async def test_contract_authenticated_is_any_principal_a_provider_or_an_edge_vouched_for(self, authorizer):
        assert await authorizer.agent_level(self.ERIN, "support-triage") == self.READ
        # A messaging sender counts: its platform identified it, even where the platform verified nothing.
        assert await authorizer.agent_level(self.SLACK_DAVE, "support-triage") == self.READ

    @pytest.mark.asyncio
    async def test_contract_a_user_grant_matches_the_subject_a_provider_authenticated(self, authorizer):
        assert await authorizer.agent_level(self.DAVE, "billing") == self.WRITE

    @pytest.mark.asyncio
    async def test_contract_a_user_grant_never_matches_a_messaging_sender_with_that_subject(self, authorizer):
        # A platform id could collide with a configured subject, so an edge sender is granted through its provider.
        assert await authorizer.agent_level(self.SLACK_DAVE, "billing") == self.READ
        assert await authorizer.agent_level(self.SLACK_DAVE, "support-triage") == self.READ

    @pytest.mark.asyncio
    async def test_contract_a_group_grant_matches_a_member_of_the_group(self, authorizer):
        assert await authorizer.agent_level(self.BOB, "support-triage") == self.WRITE
        assert await authorizer.agent_level(self.ALICE, "billing") is None  # her group is named by no grant

    @pytest.mark.asyncio
    async def test_contract_a_role_grant_matches_a_holder_of_the_role(self, authorizer):
        assert await authorizer.agent_level(self.ALICE, "k8s-troubleshooter") == self.WRITE
        assert await authorizer.agent_level(self.BOB, "k8s-troubleshooter") is None

    @pytest.mark.asyncio
    async def test_contract_a_provider_grant_matches_the_provider_by_its_exact_name(self, authorizer):
        assert await authorizer.agent_level(self.ERIN, "k8s-troubleshooter") == self.READ
        assert await authorizer.agent_level(self.OIDC_LOOKALIKE, "k8s-troubleshooter") is None

    @pytest.mark.asyncio
    async def test_contract_a_provider_grant_ending_in_a_colon_matches_by_prefix(self, authorizer):
        assert await authorizer.agent_level(self.SLACK_DAVE, "billing") == self.READ
        assert await authorizer.agent_level(self.ERIN, "billing") is None

    # Agent levels: the agent entries, and how grants combine

    @pytest.mark.asyncio
    async def test_contract_a_wildcard_agent_entry_covers_every_agent(self, authorizer):
        assert await self._levels(authorizer, self.CAROL) == {agent_id: self.ADMIN for agent_id in self.AGENT_IDS}

    @pytest.mark.asyncio
    async def test_contract_a_tag_entry_covers_the_agents_carrying_the_tag_and_no_other(self, authorizer):
        assert await self._levels(authorizer, self.DAVE) == {
            "faq": self.READ,  # tagged frontline only: what everyone holds
            "support-triage": self.WRITE,
            "billing": self.WRITE,
            "k8s-troubleshooter": None,
        }

    @pytest.mark.asyncio
    async def test_contract_a_tag_no_agent_carries_matches_nothing(self, authorizer):
        # The policy grants everyone admin on the agents tagged `retired`; there are none.
        assert await authorizer.agent_level(self.ANONYMOUS, "billing") is None
        assert await authorizer.agent_level(self.ANONYMOUS, "faq") == self.READ

    @pytest.mark.asyncio
    async def test_contract_a_list_grant_applies_to_every_subject_and_agent_it_names(self, authorizer):
        assert await authorizer.agent_level(self.BOB, "faq") == self.WRITE
        assert await authorizer.agent_level(self.BOB, "support-triage") == self.WRITE

    @pytest.mark.asyncio
    async def test_contract_the_highest_matching_level_wins(self, authorizer):
        # Read as an oidc caller on the ops tag, write as an operator.
        assert await authorizer.agent_level(self.ALICE, "k8s-troubleshooter") == self.WRITE
        # Read as an authenticated caller, write through the user grant.
        assert await authorizer.agent_level(self.DAVE, "support-triage") == self.WRITE

    @pytest.mark.asyncio
    async def test_contract_no_matching_grant_is_no_level(self, authorizer):
        assert await authorizer.agent_level(self.ERIN, "billing") is None

    # Tools

    @pytest.mark.asyncio
    async def test_contract_a_tool_is_offered_when_its_tier_is_at_or_below_the_level(self, authorizer):
        tools = ["lookup_ticket", "create_ticket", "refund"]

        assert await self._allowed(authorizer, self.ERIN, "support-triage", tools) == {"lookup_ticket": True, "create_ticket": False, "refund": False}
        assert await self._allowed(authorizer, self.DAVE, "support-triage", tools) == {"lookup_ticket": True, "create_ticket": True, "refund": False}
        assert await self._allowed(authorizer, self.CAROL, "support-triage", tools) == {"lookup_ticket": True, "create_ticket": True, "refund": True}

    @pytest.mark.asyncio
    async def test_contract_a_tool_with_no_tier_is_a_read_tool(self, authorizer):
        assert (await authorizer.check_tool(self.ERIN, "support-triage", "summarize")).allowed
        assert (await authorizer.check_tool(self.DAVE, "billing", "charge")).allowed  # an agent with no tool policy at all

    @pytest.mark.asyncio
    async def test_contract_no_level_on_the_agent_denies_every_tool(self, authorizer):
        assert await self._allowed(authorizer, self.ANONYMOUS, "support-triage", ["lookup_ticket", "summarize"]) == {
            "lookup_ticket": False,
            "summarize": False,
        }

    @pytest.mark.asyncio
    async def test_contract_a_denied_tool_is_refused_at_every_level(self, authorizer):
        assert not (await authorizer.check_tool(self.CAROL, "support-triage", "delete_ticket")).allowed

    @pytest.mark.asyncio
    async def test_contract_an_allow_list_limits_the_offer_to_the_tools_it_names(self, authorizer):
        assert await self._allowed(authorizer, self.CAROL, "k8s-troubleshooter", ["kubectl_get", "kubectl_apply", "kubectl_delete"]) == {
            "kubectl_get": True,
            "kubectl_apply": True,
            "kubectl_delete": False,
        }

    @pytest.mark.asyncio
    async def test_contract_an_allowed_tool_still_needs_its_tier(self, authorizer):
        assert await self._allowed(authorizer, self.ERIN, "k8s-troubleshooter", ["kubectl_get", "kubectl_apply"]) == {
            "kubectl_get": True,
            "kubectl_apply": False,
        }

    @pytest.mark.asyncio
    async def test_contract_deny_wins_over_allow(self, authorizer):
        assert not (await authorizer.check_tool(self.CAROL, "k8s-troubleshooter", "kubectl_exec")).allowed

    @pytest.mark.asyncio
    async def test_contract_a_refusal_says_why_and_an_approval_needs_no_reason(self, authorizer):
        refused = await authorizer.check_tool(self.ERIN, "support-triage", "refund")
        approved = await authorizer.check_tool(self.ERIN, "support-triage", "lookup_ticket")

        assert not refused.allowed and refused.reason
        assert approved.allowed

    @pytest.mark.asyncio
    async def test_contract_filter_tools_keeps_the_allowed_tools_in_the_order_given(self, authorizer):
        tools = ["refund", "create_ticket", "delete_ticket", "summarize", "lookup_ticket"]

        assert await authorizer.filter_tools(self.DAVE, "support-triage", tools) == ["create_ticket", "summarize", "lookup_ticket"]
        assert await authorizer.filter_tools(self.ANONYMOUS, "support-triage", tools) == []

    @pytest.mark.asyncio
    async def test_contract_filter_tools_agrees_with_check_tool(self, authorizer):
        tools = ["kubectl_get", "kubectl_apply", "kubectl_exec", "kubectl_delete"]
        for principal in self.PRINCIPALS:
            checked = [tool for tool in tools if (await authorizer.check_tool(principal, "k8s-troubleshooter", tool)).allowed]
            assert await authorizer.filter_tools(principal, "k8s-troubleshooter", tools) == checked, principal.subject

    # Listing

    @pytest.mark.asyncio
    async def test_contract_visible_agents_are_the_candidates_the_principal_holds_a_level_on(self, authorizer):
        assert await authorizer.visible_agents(self.ANONYMOUS, self.AGENT_IDS) == ["faq"]
        assert await authorizer.visible_agents(self.DAVE, self.AGENT_IDS) == ["faq", "support-triage", "billing"]
        assert await authorizer.visible_agents(self.CAROL, self.AGENT_IDS) == self.AGENT_IDS

    @pytest.mark.asyncio
    async def test_contract_visible_agents_agrees_with_a_walk_of_the_candidates_and_keeps_their_order(self, authorizer):
        candidates = list(reversed(self.AGENT_IDS))
        for principal in self.PRINCIPALS:
            walked = [agent_id for agent_id in candidates if await authorizer.agent_level(principal, agent_id) is not None]
            assert await authorizer.visible_agents(principal, candidates) == walked, principal.subject

    @pytest.mark.asyncio
    async def test_contract_visible_agents_names_only_candidates(self, authorizer):
        assert await authorizer.visible_agents(self.CAROL, ["billing"]) == ["billing"]
        assert await authorizer.visible_agents(self.CAROL, []) == []

    def test_contract_capabilities_are_declared(self, authorizer):
        assert isinstance(authorizer.capabilities.lists_resources, bool)
