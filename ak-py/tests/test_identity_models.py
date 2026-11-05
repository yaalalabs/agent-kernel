"""
The identity models (spec `docs/specs/603-identity-rbac-registry/`, iteration 1).

These are the types every later iteration and the omnichannel work build on, so this file pins
their shape rather than any behaviour around them: `AccessLevel` is a total order over exactly
three members, `Principal` is frozen and copied by its helpers, `ToolFilter` answers for a name it
was never told about, and `AgentDescriptor` treats a missing `surfaces` list as every surface.
"""

import json

import pytest
from pydantic import ValidationError

from agentkernel.core.model import (
    AccessLevel,
    AgentDescriptor,
    AgentIdentitySpec,
    AgentSkillDescriptor,
    BaseChatRequest,
    Principal,
    SessionOwner,
    SystemTool,
    ToolFilter,
)
from agentkernel.integration.adapter.base import InboundRequest


def _principal(**overrides) -> Principal:
    fields = {"subject": "alice", "provider": "oidc", "namespace": "https://issuer.example"}
    fields.update(overrides)
    return Principal(**fields)


class TestAccessLevel:
    def test_orders_read_below_write_below_admin(self):
        assert AccessLevel.READ < AccessLevel.WRITE < AccessLevel.ADMIN
        assert AccessLevel.ADMIN > AccessLevel.WRITE > AccessLevel.READ
        assert AccessLevel.WRITE <= AccessLevel.WRITE
        assert AccessLevel.WRITE >= AccessLevel.WRITE
        assert not AccessLevel.ADMIN < AccessLevel.READ

    def test_parses_from_its_string_value(self):
        assert AccessLevel("write") is AccessLevel.WRITE
        assert AccessLevel.READ == "read"

    def test_refuses_to_order_against_anything_but_a_level(self):
        # A plain string would otherwise compare alphabetically ("admin" < "read"), which is the
        # opposite of the capability order, so the comparison is refused rather than guessed.
        with pytest.raises(TypeError):
            AccessLevel.ADMIN < "read"  # type: ignore[operator]


class TestPrincipal:
    def test_anonymous_carries_the_reserved_subject_and_provider_and_no_namespace(self):
        anonymous = Principal.anonymous()
        assert (anonymous.subject, anonymous.provider, anonymous.namespace) == ("anonymous", "anonymous", None)
        assert anonymous.is_anonymous

    def test_an_authenticated_principal_is_not_anonymous(self):
        assert not _principal().is_anonymous

    def test_defaults(self):
        principal = _principal()
        assert principal.kind == "user"
        assert principal.groups == []
        assert principal.roles == []
        assert principal.claims == {}
        assert principal.actor is None
        assert principal.credential_ref is None

    def test_is_frozen(self):
        principal = _principal()
        with pytest.raises(ValidationError):
            principal.subject = "mallory"  # type: ignore[misc]

    def test_with_actor_returns_a_copy_and_leaves_the_original_untouched(self):
        user = _principal()
        agent = Principal(subject="planner", kind="agent", provider="registry")
        acting = agent.with_actor(user)
        assert acting.actor == user
        assert acting.subject == "planner"
        assert agent.actor is None

    def test_with_credential_ref_sets_and_clears_on_copies(self):
        principal = _principal()
        retained = principal.with_credential_ref("cred-1")
        assert retained.credential_ref == "cred-1"
        assert principal.credential_ref is None
        assert retained.with_credential_ref(None).credential_ref is None

    def test_round_trips_through_json_with_its_actor(self):
        acting = Principal(subject="planner", kind="agent", provider="registry").with_actor(_principal(groups=["ops"]))
        restored = Principal.model_validate(json.loads(acting.model_dump_json()))
        assert restored == acting
        assert restored.actor is not None and restored.actor.groups == ["ops"]

    def test_kind_is_one_of_user_agent_service(self):
        with pytest.raises(ValidationError):
            _principal(kind="robot")


class TestSessionOwner:
    def test_namespace_is_optional_and_equal_owners_compare_equal(self):
        assert SessionOwner(subject="alice", provider="static").namespace is None
        assert SessionOwner(subject="alice", provider="oidc", namespace="https://issuer.example") == SessionOwner(
            subject="alice", provider="oidc", namespace="https://issuer.example"
        )


class TestToolFilter:
    def test_allows_only_the_listed_tools(self):
        tool_filter = ToolFilter(level=AccessLevel.READ, allowed=["search"], reasons={"deploy": "needs write"})
        assert tool_filter.allows("search")
        assert not tool_filter.allows("deploy")
        assert not tool_filter.allows("never_heard_of")

    def test_reason_is_the_recorded_one_for_a_denied_tool(self):
        tool_filter = ToolFilter(
            level=AccessLevel.READ, allowed=[], reasons={"deploy": "Tool 'deploy' requires level write; the current principal has read"}
        )
        assert tool_filter.reason("deploy") == "Tool 'deploy' requires level write; the current principal has read"

    def test_reason_is_generic_for_an_unlisted_tool(self):
        tool_filter = ToolFilter(level=AccessLevel.READ, allowed=[])
        assert tool_filter.reason("never_heard_of") == "Tool 'never_heard_of' is not available to the current principal"

    def test_allowed_is_a_frozenset_and_the_filter_is_frozen(self):
        tool_filter = ToolFilter(level=AccessLevel.WRITE, allowed=["a", "a", "b"])
        assert tool_filter.allowed == frozenset({"a", "b"})
        with pytest.raises(ValidationError):
            tool_filter.level = AccessLevel.ADMIN  # type: ignore[misc]


class TestAgentDescriptor:
    def test_defaults(self):
        descriptor = AgentDescriptor(id="planner", name="Planner")
        assert descriptor.version == "0.0.0"
        assert descriptor.description == ""
        assert descriptor.owner is None
        assert descriptor.tags == []
        assert descriptor.visibility == "private"
        assert descriptor.surfaces is None
        assert descriptor.skills == []
        assert descriptor.tools == []
        assert descriptor.runner == ""
        assert descriptor.supports_streaming is True
        assert descriptor.identity == AgentIdentitySpec()
        assert descriptor.updated_at is None

    def test_identity_spec_defaults_to_no_subject_and_no_client(self):
        spec = AgentIdentitySpec()
        assert (spec.subject, spec.client_id, spec.client_secret_key) == (None, None, None)

    def test_skill_descriptor_defaults(self):
        skill = AgentSkillDescriptor(id="plan", name="Plan")
        assert (skill.description, skill.tags) == ("", [])

    def test_no_surfaces_list_means_every_surface(self):
        descriptor = AgentDescriptor(id="planner", name="Planner")
        assert all(descriptor.exposed_on(surface) for surface in ("rest", "a2a", "mcp", "agui"))

    def test_a_surfaces_list_exposes_only_those(self):
        descriptor = AgentDescriptor(id="planner", name="Planner", surfaces=["mcp"])
        assert descriptor.exposed_on("mcp")
        assert not descriptor.exposed_on("a2a")
        assert not descriptor.exposed_on("rest")

    def test_an_empty_surfaces_list_exposes_nothing(self):
        assert not AgentDescriptor(id="planner", name="Planner", surfaces=[]).exposed_on("rest")

    def test_surfaces_and_visibility_are_restricted(self):
        with pytest.raises(ValidationError):
            AgentDescriptor(id="planner", name="Planner", surfaces=["grpc"])
        with pytest.raises(ValidationError):
            AgentDescriptor(id="planner", name="Planner", visibility="secret")


class TestSystemToolTier:
    def test_defaults_to_read(self):
        assert SystemTool(name="search", description="", func=lambda: None).tier is AccessLevel.READ

    def test_accepts_a_declared_level_by_value(self):
        assert SystemTool(name="deploy", description="", func=lambda: None, tier="write").tier is AccessLevel.WRITE


class TestRequestFields:
    def test_chat_request_principal_defaults_to_none_and_accepts_a_principal(self):
        assert BaseChatRequest(prompt="hi").principal is None
        assert BaseChatRequest(prompt="hi", principal=_principal()).principal == _principal()

    def test_a_principal_never_reaches_the_agent_as_context(self):
        from agentkernel.core.chat_service import RequestBuilder
        from agentkernel.core.model import BaseRunRequest

        request = BaseRunRequest(prompt="hi", session_id="s1", principal=_principal())

        built = RequestBuilder.from_base_request_sync(request)

        # The builder appends an AgentRequestAny for every field it does not know; the principal is
        # the surface's envelope, never something the user asked the agent.
        assert [type(r).__name__ for r in built] == ["AgentRequestText"]

    def test_inbound_request_namespace_and_claims_default_empty(self):
        request = InboundRequest(session_id="s", request_id="r", requests=[])
        assert request.namespace is None
        assert request.claims == {}

    def test_inbound_request_claims_are_not_shared_between_instances(self):
        first = InboundRequest(session_id="s", request_id="r", requests=[])
        first.claims["authentication_results"] = "spf=pass"
        assert InboundRequest(session_id="s", request_id="r2", requests=[]).claims == {}


class TestExports:
    def test_the_models_are_exported_from_agentkernel_core(self):
        import agentkernel.core as core

        for name in ("AccessLevel", "Principal", "SessionOwner", "ToolFilter", "AgentDescriptor", "AgentSkillDescriptor", "AgentIdentitySpec"):
            assert getattr(core, name) is getattr(__import__("agentkernel.core.model", fromlist=[name]), name)
