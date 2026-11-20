"""Attribution (spec §9): DefaultAttributor, the AttributorContract, and AttributorFactory's bring-your-own path."""

import pytest

import agentkernel.cost as cost
from agentkernel.core.config import _CostAttributionConfig
from agentkernel.core.model import Principal
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import Attribution, AttributionContext, Attributor, AttributorFactory, DefaultAttributor
from agentkernel.cost.testing import AttributorContract


class PrefixingAttributor(Attributor):
    """A bring-your-own attributor that keeps identity providers apart: ``<provider><sep><subject>``."""

    def resolve(self, ctx: AttributionContext) -> Attribution:
        principal = ctx.principal or Principal.anonymous()
        separator = (self.config.model_extra or {}).get("separator", "|")
        return Attribution(
            user_id=f"{principal.provider}{separator}{principal.subject}",
            agent_id=ctx.agent_name,
            session_id=ctx.session_id,
            request_id=ctx.request_id,
        )


_BYO_TYPE = f"{__name__}.PrefixingAttributor"


def _context(principal: Principal | None, **overrides) -> AttributionContext:
    return AttributionContext(**({"principal": principal, "agent_name": "support", "session_id": "s-1", "request_id": "r-1"} | overrides))


class TestDefaultAttributorContract(AttributorContract):
    @pytest.fixture
    def attributor(self) -> Attributor:
        return DefaultAttributor(_CostAttributionConfig())


class TestPrefixingAttributorContract(AttributorContract):
    @pytest.fixture
    def attributor(self) -> Attributor:
        return PrefixingAttributor(_CostAttributionConfig(type=_BYO_TYPE, separator=":"))


class TestDefaultAttributor:
    @pytest.mark.parametrize("principal", [None, Principal.anonymous()])
    def test_no_or_anonymous_principal_is_anonymous(self, principal):
        assert DefaultAttributor(_CostAttributionConfig()).resolve(_context(principal)).user_id == "anonymous"

    def test_a_messaging_principal_is_budgeted_per_sender(self):
        sender = Principal(subject="U024BE7LH", provider="messaging:slack", namespace="T0001")

        assert DefaultAttributor(_CostAttributionConfig()).resolve(_context(sender)).user_id == "U024BE7LH"

    def test_the_actor_is_never_the_user(self):
        user = Principal(subject="user-123", provider="oidc", namespace="https://issuer.example")
        run_principal = user.with_actor(Principal(subject="support", kind="agent", provider="agent"))

        assert DefaultAttributor(_CostAttributionConfig()).resolve(_context(run_principal)).user_id == "user-123"

    def test_run_ids_pass_through(self):
        principal = Principal(subject="user-123", provider="oidc")

        assert DefaultAttributor(_CostAttributionConfig()).resolve(_context(principal)) == Attribution(
            user_id="user-123", agent_id="support", session_id="s-1", request_id="r-1"
        )
        assert DefaultAttributor(_CostAttributionConfig()).resolve(
            _context(principal, agent_name=None, session_id=None, request_id=None)
        ) == Attribution(user_id="user-123")


class TestAttributorFactory:
    @pytest.mark.parametrize("type_", ["default", "DEFAULT"])
    def test_default(self, type_):
        assert type(AttributorFactory.create(_CostAttributionConfig(type=type_))) is DefaultAttributor

    def test_a_dotted_path_gets_its_own_settings(self):
        attributor = AttributorFactory.create(_CostAttributionConfig(type=_BYO_TYPE, separator="#"))

        assert isinstance(attributor, PrefixingAttributor)
        assert attributor.resolve(_context(Principal(subject="u1", provider="oidc"))).user_id == "oidc#u1"

    @pytest.mark.parametrize(("type_", "message"), [("custom", "unknown cost.attribution.type"), ("datetime.datetime", "not a Attributor subclass")])
    def test_refused_types(self, type_, message):
        with pytest.raises(AKConfigError, match=message):
            AttributorFactory.create(_CostAttributionConfig(type=type_))

    def test_exported(self):
        assert {"AttributionContext", "Attributor", "AttributorFactory", "DefaultAttributor"} <= set(cost.__all__)
