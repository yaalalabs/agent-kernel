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
