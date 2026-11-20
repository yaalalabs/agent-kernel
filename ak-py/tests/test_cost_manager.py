"""CostManager (spec §11.5, §11.6, §15): construction and capability checks, the startup probe and its backoff, the
singleton, attribution, the RunMeter check, and the refusal walk over exception chains."""

import logging
from decimal import Decimal
from types import SimpleNamespace

import pytest

import agentkernel.cost.manager as manager_module
from agentkernel.core.config import _CostConfig
from agentkernel.core.meter import BudgetDecision, NoOpRunMeter, RunMeterFactory
from agentkernel.core.model import Principal
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import (
    Attribution,
    CostManager,
    DefaultUsageView,
    GatewayCapabilities,
    LedgerSpendFlow,
    SpendTotal,
    StaticBudgetPolicy,
    UsageRetrievalError,
)
from agentkernel.cost.budget import UNVERIFIED_DENY_MESSAGE

_GATEWAY = {"type": "fake", "base_url": "http://gateway.test"}
_WINDOWED = GatewayCapabilities(usage_retrieval=True, windowed_spend=True)
_LEDGERED = GatewayCapabilities(usage_retrieval=True, native_user_budget=True)


class _Refused(Exception):
    pass


class _ManagedGateway:
    name = "fake"

    def __init__(self, capabilities: GatewayCapabilities = _WINDOWED, probe_failures=()) -> None:
        self.capabilities = capabilities
        self.probe_failures = list(probe_failures)
        self.probes = 0
        self.closed = 0
        self.synced: list = []

    async def probe(self) -> None:
        self.probes += 1
        if self.probe_failures:
            raise self.probe_failures.pop(0)

    async def close(self) -> None:
        self.closed += 1

    async def total_spend(self, user_id, window):
        return SpendTotal(currency="USD", by_model={})

    async def sync_budget_definitions(self, limits) -> None:
        self.synced.append(("definitions", list(limits)))

    async def sync_budgets(self, budgets) -> None:
        self.synced.append(("budgets", dict(budgets)))

    def is_budget_refusal(self, error: BaseException) -> bool:
        return isinstance(error, _Refused)

    def attribution_headers(self, attribution: Attribution) -> dict[str, str]:
        return {"x-user": attribution.user_id or ""}


@pytest.fixture
def gateway(monkeypatch):
    fake = _ManagedGateway()
    monkeypatch.setattr(manager_module.LLMGatewayFactory, "create", staticmethod(lambda config: fake))
    yield fake
    CostManager.reset()


def _manager(**cost) -> CostManager:
    return CostManager(_CostConfig(gateway=_GATEWAY, **cost))


def _join(manager: CostManager) -> None:
    thread = manager.native._thread
    assert thread is not None
    thread.join(5)
    assert not thread.is_alive()


_BUDGET = {"default": {"amount": "10"}}


class TestConstruction:
    def test_parts_are_built_and_a_windowed_gateway_needs_no_ledger(self, gateway):
        manager = _manager(budgets=_BUDGET)

        assert isinstance(manager.policy, StaticBudgetPolicy) and isinstance(manager.view, DefaultUsageView)
        assert manager.policy._reader._ledger_flow is None
        assert gateway.probes == 1 and manager._probe_ok

    def test_a_gateway_without_windowed_spend_reads_through_a_ledger(self, gateway):
        gateway.capabilities = _LEDGERED

        manager = _manager(budgets=_BUDGET | {"default": {"amount": "10", "action": "warn"}})

        assert isinstance(manager.policy._reader._ledger_flow, LedgerSpendFlow)

    def test_a_ledger_block_on_a_windowed_gateway_is_ignored_with_a_warning(self, gateway, caplog):
        caplog.set_level(logging.WARNING, logger="ak.cost.manager")

        manager = _manager(budgets=_BUDGET | {"ledger": {"type": "in_memory"}})

        assert manager.policy._reader._ledger_flow is None and "is ignored" in caplog.text


class TestCapabilityChecks:
    @pytest.mark.parametrize(
        ("capabilities", "budgets", "pricing", "message"),
        [
            (GatewayCapabilities(), _BUDGET, {}, "enforce or report spend"),
            (_WINDOWED, {"default": {"amount": "10", "currency": "EUR"}}, {}, "EUR budget"),
            (GatewayCapabilities(native_user_budget=True), {"default": {"amount": "10", "action": "warn"}}, {}, "needs spend reads"),
            (
                GatewayCapabilities(windowed_spend=True, currencies=frozenset({"USD", "EUR"})),
                {"default": {"amount": "10", "currency": "EUR"}},
                {"type": "static"},
                "static pricing",
            ),
        ],
    )
    def test_each_mismatch_is_refused_and_the_gateway_closed(self, gateway, capabilities, budgets, pricing, message):
        gateway.capabilities = capabilities

        with pytest.raises(AKConfigError, match=message):
            _manager(budgets=budgets, pricing=pricing)
        assert gateway.closed == 1

    def test_no_budgets_need_nothing(self, gateway):
        gateway.capabilities = GatewayCapabilities()

        assert _manager().policy.limit_for("alice") is None


class TestProbe:
    @pytest.mark.parametrize("error", [AKConfigError("needs LiteLLM 1.111"), UsageRetrievalError("401", status=401, auth=True)])
    def test_a_fatal_answer_fails_construction(self, gateway, error):
        gateway.probe_failures = [error]

        with pytest.raises(AKConfigError):
            _manager()
        assert gateway.closed == 1

    @pytest.mark.asyncio
    async def test_an_unavailable_gateway_is_probed_in_the_background(self, gateway, caplog, monkeypatch):
        caplog.set_level(logging.ERROR, logger="ak.cost.manager")
        gate = manager_module.threading.Event()
        gateway.capabilities = _LEDGERED
        gateway.probe_failures = [UsageRetrievalError("503", status=503)]
        original_probe = gateway.probe

        async def held_probe():
            if gateway.probes >= 1:
                assert gate.wait(5)  # the background retry waits until the test has checked the outage
            await original_probe()

        gateway.probe = held_probe
        manager = _manager(budgets={"default": {"amount": "10"}, "on_error": "block"})

        assert "did not answer its startup probe" in caplog.text and manager._probe_ok is False
        decision = await manager.policy.check(Attribution(user_id="alice"))
        assert decision == BudgetDecision.deny(UNVERIFIED_DENY_MESSAGE)  # unverified while the probe has not passed

        gate.set()
        _join(manager)
        assert manager._probe_ok is True
        assert ("budgets", {"ak-system": None}) in gateway.synced  # the native sync ran after the probe

    def test_a_successful_probe_starts_the_native_sync(self, gateway):
        gateway.capabilities = _LEDGERED

        manager = _manager(budgets={"default": {"amount": "10"}})

        assert gateway.synced[0][0] == "definitions" and manager.native._ready.is_set()


class TestSingleton:
    def test_no_cost_block_means_none(self, gateway, monkeypatch):
        monkeypatch.setattr(manager_module.AKConfig, "get", classmethod(lambda cls: SimpleNamespace(cost=None)))

        assert CostManager.get() is None
        with pytest.raises(AKConfigError, match="requires a cost block"):
            CostManager.require()

    def test_built_once_and_reset_closes(self, gateway, monkeypatch):
        config = _CostConfig(gateway=_GATEWAY)
        monkeypatch.setattr(manager_module.AKConfig, "get", classmethod(lambda cls: SimpleNamespace(cost=config)))

        first = CostManager.get()
        assert CostManager.get() is first and CostManager.require() is first and gateway.probes == 1

        CostManager.reset()
        assert gateway.closed == 1 and CostManager._instance is None

    def test_the_run_meter_stays_the_no_op_one(self, gateway, monkeypatch):
        """Task 4 wires CostManager into runs; until then a cost block changes nothing."""
        config = _CostConfig(gateway=_GATEWAY)
        monkeypatch.setattr(manager_module.AKConfig, "get", classmethod(lambda cls: SimpleNamespace(cost=config)))
        RunMeterFactory.reset()

        assert isinstance(RunMeterFactory.get(), NoOpRunMeter)
        RunMeterFactory.reset()


class TestAttribution:
    @pytest.mark.asyncio
    async def test_check_bills_the_session_principal_through_the_attributor(self, gateway):
        manager = _manager()
        seen = []

        async def check(attribution):
            seen.append(attribution)
            return BudgetDecision.allow()

        manager.policy.check = check
        principal = Principal(subject="alice", provider="oidc").with_actor(Principal(subject="support", kind="agent", provider="agent"))
        session = SimpleNamespace(id="s-1", get_principal=lambda: principal, get_request_id=lambda: "r-1")

        await manager.check(session, SimpleNamespace(name="support"))

        assert seen == [Attribution(user_id="alice", agent_id="support", session_id="s-1", request_id="r-1")]

    def test_outside_a_run(self, gateway):
        manager = _manager()

        assert manager.current_attribution() is None
        with pytest.raises(RuntimeError):
            manager.attribution_headers()
        assert manager.user_id_for(None) is None and manager.attribution_for(None, "s", "r") is None
        assert manager.user_id_for(Principal(subject="alice", provider="oidc")) == "alice"


class TestIsBudgetRefusal:
    @staticmethod
    def _chained(cause: BaseException, via: str) -> Exception:
        outer = RuntimeError("framework error")
        setattr(outer, via, cause)
        return outer

    @pytest.mark.parametrize("via", ["__cause__", "__context__"])
    def test_a_refusal_anywhere_in_the_chain(self, gateway, via):
        assert _manager().is_budget_refusal(self._chained(self._chained(_Refused(), via), via)) is True

    def test_no_refusal(self, gateway):
        assert _manager().is_budget_refusal(self._chained(ValueError("x"), "__cause__")) is False

    def test_a_cycle_is_walked_once(self, gateway):
        manager = _manager()
        visited = []
        manager.gateway.is_budget_refusal = lambda link: visited.append(link) or False
        a, b = RuntimeError("a"), RuntimeError("b")
        a.__cause__, b.__cause__ = b, a

        assert manager.is_budget_refusal(a) is False
        assert visited == [a, b]  # each link once, not round the cycle until the cap

    def test_the_walk_stops_after_sixteen_links(self, gateway):
        manager = _manager()
        visited = []
        manager.gateway.is_budget_refusal = lambda link: visited.append(link) or isinstance(link, _Refused)
        error: BaseException = _Refused()
        for n in range(20):
            error = self._chained(error, "__cause__")

        assert manager.is_budget_refusal(error) is False  # the refusal is 21 links down
        assert len(visited) == 16
