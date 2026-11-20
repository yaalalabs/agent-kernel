"""Budgets (spec §11.1-11.3): StaticBudgetPolicy and the BudgetPolicyContract, NoBudgetPolicy, on_error and the read
bound, SpendReader, and BudgetPolicyFactory."""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import agentkernel.cost as cost
import agentkernel.cost.budget as budget_module
from agentkernel.core.config import _CostBudgetsConfig, _CostPricingConfig
from agentkernel.core.meter import BudgetDecision
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import (
    Attribution,
    BudgetLimit,
    BudgetPeriod,
    BudgetPolicy,
    BudgetPolicyFactory,
    GatewayCapabilities,
    LedgerBehindError,
    LedgerConflictError,
    LedgerError,
    ModelSpend,
    NoBudgetPolicy,
    PassthroughPricingSource,
    SpendCursor,
    SpendReader,
    SpendTotal,
    StaticBudgetPolicy,
    StaticPricingSource,
    UnsupportedCapabilityError,
    UsageRetrievalError,
    UsageTruncatedError,
    UsageWindow,
)
from agentkernel.cost.budget import UNVERIFIED_DENY_MESSAGE
from agentkernel.cost.testing import BudgetPolicyContract

_NOW = datetime(2026, 1, 28, 12, 0, tzinfo=timezone.utc)
_TEN = BudgetLimit(amount=Decimal("10"))


def _total(cost_: Decimal, model: str = "gpt-4o", currency: str = "USD", unpriced: int = 0) -> SpendTotal:
    spend = ModelSpend(model=model, provider="openai", requests=1, provider_cost=cost_, unpriced_requests=unpriced)
    return SpendTotal(currency=currency, by_model={SpendTotal.key("openai", model): spend})


class _FakeReader:
    """Returns one model's spend of ``result``, or raises it; records each read."""

    def __init__(self) -> None:
        self.result: Decimal | BaseException = Decimal(0)
        self.calls: list[tuple[str, UsageWindow, BudgetLimit]] = []

    async def spend(self, user_id: str, window: UsageWindow, limit: BudgetLimit) -> SpendTotal:
        self.calls.append((user_id, window, limit))
        if isinstance(self.result, BaseException):
            raise self.result
        return _total(self.result)


def _policy(on_error: str = "block", pricing=None, **config) -> StaticBudgetPolicy:
    reader = _FakeReader()
    budgets = _CostBudgetsConfig(on_error=on_error, **({"default": _TEN} | config))
    return StaticBudgetPolicy(budgets, reader, pricing or PassthroughPricingSource(_CostPricingConfig()), clock=lambda: _NOW)


class TestStaticBudgetPolicyContract(BudgetPolicyContract):
    def make_policy(self, limit, on_error):
        return _policy(on_error, default=limit)

    def spend(self, policy, result):
        policy._reader.result = result

    def reads(self, policy):
        return len(policy._reader.calls)


class TestLimits:
    @pytest.mark.asyncio
    async def test_a_users_entry_beats_the_default(self):
        policy = _policy(users={"alice": BudgetLimit(amount=Decimal("100"))})
        policy._reader.result = Decimal("50")

        assert await policy.check(Attribution(user_id="alice")) == BudgetDecision.allow()
        assert (await policy.check(Attribution(user_id="bob"))).kind == "deny"  # the default of 10

    @pytest.mark.asyncio
    async def test_without_a_default_an_unlisted_user_is_allowed_unread(self):
        policy = _policy(default=None, users={"alice": _TEN})

        assert await policy.check(Attribution(user_id="bob")) == BudgetDecision.allow()
        assert policy._reader.calls == []

    @pytest.mark.asyncio
    async def test_the_window_is_this_period_up_to_now(self):
        policy = _policy(default=BudgetLimit(amount=Decimal("10"), period=BudgetPeriod.WEEKLY))

        await policy.check(Attribution(user_id="alice"))

        ((_, window, _),) = policy._reader.calls
        assert window == UsageWindow(start=datetime(2026, 1, 26, tzinfo=timezone.utc), end=_NOW)  # Monday 00:00 UTC

    @pytest.mark.asyncio
    async def test_spend_is_billed_through_the_pricing_source(self):
        pricing = StaticPricingSource(_CostPricingConfig(type="static", static={"markup": "1.2"}))
        policy = _policy(pricing=pricing, default=BudgetLimit(amount=Decimal("1")))
        policy._reader.result = Decimal("0.9")  # billed 1.08

        assert (await policy.check(Attribution(user_id="alice"))).kind == "deny"

    @pytest.mark.asyncio
    async def test_the_warn_message_carries_the_numbers(self):
        policy = _policy(default=BudgetLimit(amount=Decimal("10"), action="warn"))
        policy._reader.result = Decimal("10.5")

        decision = await policy.check(Attribution(user_id="alice"))

        assert decision == BudgetDecision.warn("budget reached: user=alice period=monthly start=2026-01-01 spend=10.5 amount=10 USD")


class TestOnError:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            UsageRetrievalError("x"),
            UsageTruncatedError("x"),
            UnsupportedCapabilityError("litellm", "windowed_spend"),
            LedgerError("x"),
            LedgerConflictError("x"),
            LedgerBehindError("alice", SpendCursor(timestamp=_NOW, ids_at_timestamp=frozenset())),
            TimeoutError(),
        ],
    )
    @pytest.mark.parametrize(("on_error", "expected"), [("block", BudgetDecision.deny(UNVERIFIED_DENY_MESSAGE)), ("allow", BudgetDecision.allow())])
    async def test_each_read_failure_follows_on_error(self, error, on_error, expected):
        policy = _policy(on_error)
        policy._reader.result = error

        assert await policy.check(Attribution(user_id="alice")) == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("on_error", "level"), [("block", logging.ERROR), ("allow", logging.WARNING)])
    async def test_the_log_names_user_and_type_never_the_text(self, caplog, on_error, level):
        caplog.set_level(logging.WARNING, logger="ak.cost.budget")
        policy = _policy(on_error)
        policy._reader.result = UsageRetrievalError("response body with secrets")

        await policy.check(Attribution(user_id="alice"))

        (record,) = caplog.records
        assert record.levelno == level
        assert "alice" in record.message and "UsageRetrievalError" in record.message and "secrets" not in record.message

    @pytest.mark.asyncio
    async def test_a_ledger_still_catching_up_says_so(self, caplog):
        caplog.set_level(logging.ERROR, logger="ak.cost.budget")
        policy = _policy()
        policy._reader.result = LedgerBehindError("alice", SpendCursor(timestamp=_NOW, ids_at_timestamp=frozenset()))

        await policy.check(Attribution(user_id="alice"))

        assert "catching up" in caplog.text

    @pytest.mark.asyncio
    async def test_any_other_error_is_a_bug_and_propagates(self):
        policy = _policy()
        policy._reader.result = ValueError("bug")

        with pytest.raises(ValueError):
            await policy.check(Attribution(user_id="alice"))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("on_error", "kind"), [("block", "deny"), ("allow", "allow")])
    async def test_a_slow_read_is_cut_off(self, monkeypatch, on_error, kind):
        monkeypatch.setattr(budget_module, "READ_TIMEOUT", 0.05)
        policy = _policy(on_error)

        async def slow(*args):
            await asyncio.sleep(5)

        policy._reader.spend = slow

        assert (await policy.check(Attribution(user_id="alice"))).kind == kind


class TestNoBudgetPolicy:
    @pytest.mark.asyncio
    async def test_always_allows_and_reads_nothing(self):
        reader = _FakeReader()
        policy = NoBudgetPolicy(None, reader, PassthroughPricingSource(_CostPricingConfig()))

        assert await policy.check(Attribution(user_id="alice")) == BudgetDecision.allow()
        assert reader.calls == [] and policy.limit_for("alice") is None


def _gateway(windowed: bool, total: SpendTotal | None = None):
    return SimpleNamespace(name="fake", capabilities=GatewayCapabilities(windowed_spend=windowed), total_spend=AsyncMock(return_value=total))


class TestSpendReader:
    _WINDOW = UsageWindow(start=datetime(2026, 1, 1, tzinfo=timezone.utc), end=_NOW)

    @pytest.mark.asyncio
    async def test_a_windowed_gateway_aggregates(self):
        gateway = _gateway(True, _total(Decimal("3")))

        assert await SpendReader(gateway).spend("alice", self._WINDOW, _TEN) == _total(Decimal("3"))
        gateway.total_spend.assert_awaited_once_with("alice", self._WINDOW)

    @pytest.mark.asyncio
    async def test_otherwise_the_ledger_flow_reads(self):
        flow = SimpleNamespace(read=AsyncMock(return_value=_total(Decimal("2"))))

        assert await SpendReader(_gateway(False), ledger_flow=flow).spend("alice", self._WINDOW, _TEN) == _total(Decimal("2"))
        flow.read.assert_awaited_once_with("alice", BudgetPeriod.MONTHLY, self._WINDOW)

    @pytest.mark.asyncio
    async def test_no_windowed_spend_and_no_ledger_is_unsupported(self):
        with pytest.raises(UnsupportedCapabilityError):
            await SpendReader(_gateway(False)).spend("alice", self._WINDOW, _TEN)

    @pytest.mark.asyncio
    async def test_another_currency_is_a_retrieval_error(self):
        with pytest.raises(UsageRetrievalError, match="EUR"):
            await SpendReader(_gateway(True, _total(Decimal("3"), currency="EUR"))).spend("alice", self._WINDOW, _TEN)

    @pytest.mark.asyncio
    async def test_unpriced_requests_warn_once_per_user_and_model(self, caplog):
        caplog.set_level(logging.WARNING, logger="ak.cost.budget")
        gateway = _gateway(True, _total(Decimal("0"), unpriced=2))
        reader = SpendReader(gateway)

        await reader.spend("alice", self._WINDOW, _TEN)
        await reader.spend("alice", self._WINDOW, _TEN)
        gateway.total_spend.return_value = _total(Decimal("0"), model="gpt-4o-mini", unpriced=1)
        await reader.spend("alice", self._WINDOW, _TEN)

        assert [r.message.split(" have")[0] for r in caplog.records] == [
            "2 requests by user 'alice' to 'openai/gpt-4o'",
            "1 requests by user 'alice' to 'openai/gpt-4o-mini'",
        ]


class _CustomPolicy(BudgetPolicy):
    async def check(self, attribution):
        return BudgetDecision.allow()


class TestBudgetPolicyFactory:
    _ARGS = (_FakeReader(), PassthroughPricingSource(_CostPricingConfig()))

    def test_no_budgets_block_means_no_budgets(self):
        assert isinstance(BudgetPolicyFactory.create(None, *self._ARGS), NoBudgetPolicy)

    @pytest.mark.parametrize(("type_", "expected"), [("static", StaticBudgetPolicy), ("STATIC", StaticBudgetPolicy), ("none", NoBudgetPolicy)])
    def test_built_ins(self, type_, expected):
        assert type(BudgetPolicyFactory.create(_CostBudgetsConfig(policy={"type": type_}), *self._ARGS)) is expected

    def test_a_dotted_path_gets_the_same_arguments(self):
        config = _CostBudgetsConfig(policy={"type": f"{__name__}._CustomPolicy", "tier": "gold"})

        policy = BudgetPolicyFactory.create(config, *self._ARGS)

        assert isinstance(policy, _CustomPolicy) and policy.config is config and policy._reader is self._ARGS[0]

    def test_an_unknown_type_is_refused(self):
        with pytest.raises(AKConfigError, match="unknown cost.budgets.policy.type"):
            BudgetPolicyFactory.create(_CostBudgetsConfig(policy={"type": "tiered"}), *self._ARGS)

    def test_exported(self):
        assert {"BudgetPolicy", "BudgetPolicyFactory", "NoBudgetPolicy", "SpendReader", "StaticBudgetPolicy"} <= set(cost.__all__)


# NativeBudgetSync (§11.4): budgets the gateway enforces itself.

import threading

from agentkernel.cost import SYSTEM_USER_ID, NativeBudgetSync


class _NativeGateway:
    """Records budget syncs and the thread each ran on; fails from a scripted queue; can hold user writes."""

    name = "fake"

    def __init__(self, native: bool = True) -> None:
        self.capabilities = GatewayCapabilities(native_user_budget=native)
        self.definitions: list[tuple[list, str]] = []
        self.budgets: list[tuple[dict, str]] = []
        self.failures: list[BaseException] = []
        self.user_gate: threading.Event | None = None

    def _maybe_fail(self) -> None:
        if self.failures:
            raise self.failures.pop(0)

    async def sync_budget_definitions(self, limits) -> None:
        self._maybe_fail()
        self.definitions.append((list(limits), threading.current_thread().name))

    async def sync_budgets(self, budgets) -> None:
        if self.user_gate is not None and SYSTEM_USER_ID not in budgets:
            assert self.user_gate.wait(5)
        self._maybe_fail()
        self.budgets.append((dict(budgets), threading.current_thread().name))

    def user_writes(self) -> list[dict]:
        return [budgets for budgets, _ in self.budgets if SYSTEM_USER_ID not in budgets]


_PASSTHROUGH = PassthroughPricingSource(_CostPricingConfig())
_UNAVAILABLE = UsageRetrievalError("503", gateway="fake", status=503)
_REFUSED = UsageRetrievalError("401", gateway="fake", status=401, auth=True)


def _sync(gateway, pricing=_PASSTHROUGH, **budgets) -> NativeBudgetSync:
    config = _CostBudgetsConfig(**({"default": _TEN} | budgets))
    return NativeBudgetSync(gateway, pricing, config, base_delay=0.01, max_delay=0.02)


def _join(sync: NativeBudgetSync) -> None:
    assert sync._thread is not None
    sync._thread.join(5)
    assert not sync._thread.is_alive()


class TestNativeEligibility:
    @pytest.mark.parametrize(
        ("native", "action", "pricing", "expected"),
        [
            (True, "block", _PASSTHROUGH, True),
            (True, "warn", _PASSTHROUGH, False),
            (True, "block", StaticPricingSource(_CostPricingConfig(type="static", static={"markup": "1.1"})), False),
            (True, "block", StaticPricingSource(_CostPricingConfig(type="static", static={"models": {"m": {"input": 1, "output": 1}}})), False),
            (False, "block", _PASSTHROUGH, False),
        ],
    )
    def test_native_only_when_the_gateway_enforces_the_same_amount(self, native, action, pricing, expected):
        sync = NativeBudgetSync(_NativeGateway(native), pricing, None)

        assert sync.eligible(BudgetLimit(amount=Decimal("10"), action=action)) is expected


class TestNativeStartup:
    def test_startup_writes_definitions_and_ak_system_then_users_in_the_background(self):
        gateway = _NativeGateway()
        gateway.user_gate = threading.Event()
        weekly = BudgetLimit(amount=Decimal("5"), period=BudgetPeriod.WEEKLY)
        sync = _sync(gateway, users={f"u{n:03d}": weekly for n in range(120)})

        sync.start()

        ((limits, _),) = gateway.definitions
        assert _TEN in limits and weekly in limits
        assert gateway.budgets[0][0] == {SYSTEM_USER_ID: None}
        assert gateway.user_writes() == [] and not sync.covers("u000")  # held: users are not written at startup

        gateway.user_gate.set()
        _join(sync)

        assert [len(budgets) for budgets in gateway.user_writes()] == [50, 50, 20]
        assert {thread for budgets, thread in gateway.budgets if SYSTEM_USER_ID not in budgets} == {"ak-cost-budget-sync"}
        assert sync.covers("u000") and sync.covers("u119") and not sync.covers("someone-else")

    def test_nothing_native_means_no_calls_and_no_thread(self):
        gateway = _NativeGateway()
        sync = _sync(gateway, default=BudgetLimit(amount=Decimal("10"), action="warn"))

        sync.start()

        assert gateway.definitions == [] and gateway.budgets == [] and sync._thread is None

    @pytest.mark.parametrize("error", [_REFUSED, AKConfigError("LiteLLM rejected POST /budget/new (422)")])
    def test_a_refused_key_or_shape_fails_startup(self, error):
        gateway = _NativeGateway()
        gateway.failures = [error]

        with pytest.raises(AKConfigError):
            _sync(gateway).start()

    def test_an_unavailable_gateway_is_retried_in_the_background(self, caplog):
        caplog.set_level(logging.ERROR, logger="ak.cost.native_budget")
        gateway = _NativeGateway()
        gateway.failures = [_UNAVAILABLE, _UNAVAILABLE]  # startup, then the first background attempt
        sync = _sync(gateway, users={"alice": _TEN})

        sync.start()
        _join(sync)

        assert "retrying in the background" in caplog.text
        assert sync._ready.is_set() and sync.covers("alice")
        assert gateway.budgets[0][0] == {SYSTEM_USER_ID: None} and gateway.user_writes() == [{"alice": _TEN}]

    def test_a_refused_key_in_the_background_stops_the_thread(self):
        gateway = _NativeGateway()
        sync = _sync(gateway, users={"alice": _TEN})
        gateway.user_gate = threading.Event()

        sync.start()
        gateway.failures = [_REFUSED]
        gateway.user_gate.set()
        _join(sync)

        assert gateway.user_writes() == [] and not sync.covers("alice")

    @pytest.mark.asyncio
    async def test_startup_works_inside_a_running_loop(self):
        """The first CostManager.get() can come from a run in the serving loop; run_async_sync would raise here."""
        gateway = _NativeGateway()
        sync = _sync(gateway)

        sync.start()

        assert len(gateway.definitions) == 1 and sync._ready.is_set()


class TestNativeEnsure:
    @pytest.mark.asyncio
    async def test_a_budget_that_is_not_native_is_never_synced(self):
        gateway = _NativeGateway()
        sync = _sync(gateway)
        sync._ready.set()

        assert await sync.ensure("alice", BudgetLimit(amount=Decimal("10"), action="warn")) is False
        assert gateway.budgets == []

    @pytest.mark.asyncio
    async def test_nothing_is_synced_before_the_definitions_are(self):
        gateway = _NativeGateway()

        assert await _sync(gateway).ensure("alice", _TEN) is False
        assert gateway.budgets == []

    @pytest.mark.asyncio
    async def test_a_user_is_synced_once_per_process(self):
        gateway = _NativeGateway()
        sync = _sync(gateway)
        sync.start()

        assert await sync.ensure("alice", _TEN) is True
        assert await sync.ensure("alice", _TEN) is True

        assert gateway.user_writes() == [{"alice": _TEN}]

    @pytest.mark.asyncio
    async def test_a_failure_falls_back_and_is_retried_next_time(self, caplog):
        caplog.set_level(logging.WARNING, logger="ak.cost.native_budget")
        gateway = _NativeGateway()
        sync = _sync(gateway)
        sync.start()
        gateway.failures = [_UNAVAILABLE]

        assert await sync.ensure("alice", _TEN) is False
        assert "alice" in caplog.text and "UsageRetrievalError" in caplog.text
        assert await sync.ensure("alice", _TEN) is True


class TestNativeThroughThePolicy:
    @staticmethod
    def _policy(sync: NativeBudgetSync, **budgets) -> StaticBudgetPolicy:
        reader = _FakeReader()
        reader.result = Decimal("50")  # over budget, if read
        config = _CostBudgetsConfig(**({"default": _TEN} | budgets))
        return StaticBudgetPolicy(config, reader, _PASSTHROUGH, native=sync, clock=lambda: _NOW)

    @pytest.mark.asyncio
    async def test_a_default_user_the_gateway_now_enforces_is_not_read(self):
        sync = _sync(_NativeGateway())
        sync.start()
        policy = self._policy(sync)

        assert await policy.check(Attribution(user_id="alice")) == BudgetDecision.allow()
        assert policy._reader.calls == []

    @pytest.mark.asyncio
    async def test_when_the_sync_fails_the_fallback_check_reads(self):
        gateway = _NativeGateway()
        sync = _sync(gateway)
        sync.start()
        gateway.failures = [_UNAVAILABLE]
        policy = self._policy(sync)

        assert (await policy.check(Attribution(user_id="alice"))).kind == "deny"
        assert len(policy._reader.calls) == 1

    @pytest.mark.asyncio
    async def test_a_users_entry_is_read_until_covered_and_never_ensured(self):
        gateway = _NativeGateway()
        gateway.user_gate = threading.Event()
        sync = _sync(gateway, users={"alice": _TEN})
        sync.start()
        policy = self._policy(sync, users={"alice": _TEN})

        assert (await policy.check(Attribution(user_id="alice"))).kind == "deny"  # not written yet: read
        gateway.user_gate.set()
        _join(sync)
        assert await policy.check(Attribution(user_id="alice")) == BudgetDecision.allow()

        assert len(policy._reader.calls) == 1
        assert gateway.user_writes() == [{"alice": _TEN}]  # only the background write, no lazy upsert

    def test_the_factory_passes_it_on(self):
        sync = _sync(_NativeGateway())

        policy = BudgetPolicyFactory.create(_CostBudgetsConfig(default=_TEN), _FakeReader(), _PASSTHROUGH, native=sync)

        assert policy._native is sync
