"""Pricing (spec §10): passthrough and static sources, the PricingSourceContract, and PricingSourceFactory."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

import agentkernel.cost as cost
from agentkernel.core.config import _CostPricingConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import (
    ModelSpend,
    ModelUsage,
    PassthroughPricingSource,
    PricingSource,
    PricingSourceFactory,
    SpendTotal,
    StaticPricingSource,
)
from agentkernel.cost.testing import PricingSourceContract

_RATES = {"gpt-4o-mini": {"input": "0.15", "output": "0.60", "cached_input": "0.075"}}


def _static(models: dict | None = None, markup: str = "1", **extra) -> StaticPricingSource:
    return StaticPricingSource(_CostPricingConfig(type="static", static={"markup": markup, "models": models or {}}, **extra))


def _usage(model: str | None = "gpt-4o-mini", provider: str | None = "openai", **counts) -> ModelUsage:
    values = {"input_tokens": None, "output_tokens": None, "cached_input_tokens": None, "provider_cost": None} | counts
    return ModelUsage(
        user_id="u",
        agent_id=None,
        session_id=None,
        request_id=None,
        provider=provider,
        model=model,
        billed_cost=None,
        currency="USD",
        timestamp=datetime(2026, 1, 5, tzinfo=timezone.utc),
        row_id="r1",
        **values,
    )


class TestPassthroughContract(PricingSourceContract):
    @pytest.fixture
    def source(self) -> PricingSource:
        return PassthroughPricingSource(_CostPricingConfig())


class TestStaticContract(PricingSourceContract):
    rated_model = "gpt-4o-mini"

    @pytest.fixture
    def source(self) -> PricingSource:
        return _static(_RATES, markup="1.2")


class TestStaticNoCachedRateContract(PricingSourceContract):
    rated_model = "gpt-4o-mini"

    @pytest.fixture
    def source(self) -> PricingSource:
        return _static({"gpt-4o-mini": {"input": "0.15", "output": "0.60"}})


class TestStaticFormula:
    def test_a_million_input_tokens_cost_the_input_rate(self):
        assert _static(_RATES).bill(_usage(input_tokens=1_000_000, output_tokens=0)) == Decimal("0.15")

    def test_cached_tokens_use_the_cached_rate(self):
        # 600k uncached x 0.15 + 400k cached x 0.075 + 200k output x 0.60 = 0.09 + 0.03 + 0.12
        bill = _static(_RATES).bill(_usage(input_tokens=1_000_000, cached_input_tokens=400_000, output_tokens=200_000))

        assert bill == Decimal("0.24")

    def test_cached_tokens_fall_back_to_the_input_rate(self):
        source = _static({"gpt-4o-mini": {"input": "0.15", "output": "0.60"}})

        assert source.bill(_usage(input_tokens=1_000_000, cached_input_tokens=400_000, output_tokens=0)) == Decimal("0.15")

    def test_markup_multiplies(self):
        assert _static(_RATES, markup="1.5").bill(_usage(input_tokens=1_000_000, output_tokens=0)) == Decimal("0.225")

    def test_more_cached_than_input_never_goes_negative(self):
        # A gateway that counts input without the cache: the cached part is billed, nothing is subtracted.
        assert _static(_RATES).bill(_usage(input_tokens=100_000, cached_input_tokens=400_000, output_tokens=0)) == Decimal("0.03")

    def test_unknown_counts_with_a_rate_are_unknown(self):
        assert _static(_RATES).bill(_usage(provider_cost=Decimal("1"))) is None

    def test_bill_total_uses_the_same_formula(self):
        total = SpendTotal(
            currency="USD",
            by_model={
                "openai/gpt-4o-mini": ModelSpend(
                    model="gpt-4o-mini", provider="openai", requests=3, input_tokens=1_000_000, cached_input_tokens=400_000, output_tokens=200_000
                ),
                "openai/unrated": ModelSpend(model="unrated", provider="openai", requests=1, provider_cost=Decimal("2")),
            },
        )

        assert _static(_RATES, markup="2").bill_total(total) == Decimal("0.24") * 2 + Decimal("2") * 2


class TestStaticKeys:
    def test_provider_and_model_beats_the_bare_model(self):
        source = _static({"gpt-4o": {"input": "1", "output": "1"}, "openai/gpt-4o": {"input": "2", "output": "2"}})

        assert source.bill(_usage(model="gpt-4o", input_tokens=1_000_000, output_tokens=0)) == Decimal("2")

    @pytest.mark.parametrize("provider", [None, "azure"])
    def test_the_bare_model_matches_otherwise(self, provider):
        source = _static({"gpt-4o": {"input": "1", "output": "1"}, "openai/gpt-4o": {"input": "2", "output": "2"}})

        assert source.bill(_usage(model="gpt-4o", provider=provider, input_tokens=1_000_000, output_tokens=0)) == Decimal("1")

    def test_an_unrated_model_bills_its_cost_times_markup(self):
        source = _static(_RATES, markup="1.1")

        assert source.bill(_usage(model="claude", provider_cost=Decimal("0.5"), input_tokens=10)) == Decimal("0.55")
        assert source.bill(_usage(model="claude", input_tokens=10)) is None
        assert source.bill(_usage(model=None, provider_cost=Decimal("0.5"))) == Decimal("0.55")


class TestBillsAtCost:
    def test_passthrough(self):
        assert PassthroughPricingSource(_CostPricingConfig()).bills_at_cost is True

    @pytest.mark.parametrize(("models", "markup", "expected"), [({}, "1", True), (_RATES, "1", False), ({}, "1.1", False)])
    def test_static(self, models, markup, expected):
        assert _static(models, markup=markup).bills_at_cost is expected

    def test_static_without_a_static_block(self):
        assert StaticPricingSource(_CostPricingConfig(type="static")).bills_at_cost is True


class TestConfig:
    def test_a_typo_beside_static_is_refused(self):
        with pytest.raises(AKConfigError, match="statc"):
            _static(_RATES, statc={"markup": "2"})


class TestPricingSourceFactory:
    @pytest.mark.parametrize(("type_", "expected"), [("passthrough", PassthroughPricingSource), ("STATIC", StaticPricingSource)])
    def test_built_ins(self, type_, expected):
        assert type(PricingSourceFactory.create(_CostPricingConfig(type=type_))) is expected

    def test_a_dotted_path(self):
        source = PricingSourceFactory.create(_CostPricingConfig(type="agentkernel.cost.pricing.PassthroughPricingSource"))

        assert isinstance(source, PassthroughPricingSource)

    @pytest.mark.parametrize(("type_", "message"), [("tiered", "unknown cost.pricing.type"), ("datetime.datetime", "not a PricingSource subclass")])
    def test_refused_types(self, type_, message):
        with pytest.raises(AKConfigError, match=message):
            PricingSourceFactory.create(_CostPricingConfig(type=type_))

    def test_exported(self):
        assert {"PassthroughPricingSource", "PricingSource", "PricingSourceFactory", "StaticPricingSource"} <= set(cost.__all__)
