"""Pricing: what a user is billed for gateway usage (spec §10).

``passthrough`` bills the gateway's provider cost. ``static`` bills from per-model token rates (USD per 1M tokens),
times an optional markup, and falls back to the provider cost for a model it has no rate for.
"""

import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

from ..core.config import _CostStaticModelRate, _CostStaticPricingConfig
from ..core.util.factory import AKConfigError, resolve_dotted
from .model import ModelUsage, SpendTotal

if TYPE_CHECKING:
    from ..core.config import _CostPricingConfig

_PER_RATE_UNIT = Decimal(1_000_000)  # rates are per 1M tokens


class PricingSource(ABC):
    """Turns usage into a billed amount.

    ``bills_at_cost`` is true when every bill equals the provider cost, which is when a gateway's native budget (kept
    in provider cost) enforces the same amount Agent Kernel would (§11.4). A bring-your-own source reads its own
    settings from ``config.model_extra``.
    """

    bills_at_cost: bool

    def __init__(self, config: "_CostPricingConfig") -> None:
        self.config = config

    @abstractmethod
    def bill(self, usage: ModelUsage) -> Decimal | None:
        """The amount billed for one model call; ``None`` when it cannot be priced."""

    @abstractmethod
    def bill_total(self, total: SpendTotal) -> Decimal:
        """The amount billed for aggregated spend; equals the sum of ``bill`` over the same rows."""


class PassthroughPricingSource(PricingSource):
    """Bills exactly what the gateway reports as provider cost."""

    def __init__(self, config: "_CostPricingConfig") -> None:
        super().__init__(config)
        self.bills_at_cost = True

    def bill(self, usage: ModelUsage) -> Decimal | None:
        return usage.provider_cost

    def bill_total(self, total: SpendTotal) -> Decimal:
        return sum((spend.provider_cost for spend in total.by_model.values()), Decimal(0))


class StaticPricingSource(PricingSource):
    """Bills from ``pricing.static`` rates in USD per 1M tokens, times ``markup``.

    A model key matches ``provider/model`` first, then the bare model. A model without a rate is billed its provider
    cost times ``markup``. The rates are USD; ``CostManager`` checks that the gateway reports USD.
    """

    def __init__(self, config: "_CostPricingConfig") -> None:
        super().__init__(config)
        # The pricing block allows extras for bring-your-own sources, so a typo here (``statc``) would pass silently.
        extras = sorted(config.model_extra or {})
        if extras:
            raise AKConfigError(f"cost.pricing has unknown keys for type static: {', '.join(extras)}")
        self._static = config.static or _CostStaticPricingConfig()
        self.bills_at_cost = not self._static.models and self._static.markup == 1

    def bill(self, usage: ModelUsage) -> Decimal | None:
        rate = self._rate(usage.provider, usage.model)
        if rate is None:
            return None if usage.provider_cost is None else usage.provider_cost * self._static.markup
        if usage.input_tokens is None and usage.output_tokens is None and usage.cached_input_tokens is None:
            return None
        return self._charge(rate, usage.input_tokens or 0, usage.cached_input_tokens or 0, usage.output_tokens or 0)

    def bill_total(self, total: SpendTotal) -> Decimal:
        billed = Decimal(0)
        for spend in total.by_model.values():
            rate = self._rate(spend.provider, spend.model)
            if rate is None:
                billed += spend.provider_cost * self._static.markup
            else:
                billed += self._charge(rate, spend.input_tokens, spend.cached_input_tokens, spend.output_tokens)
        return billed

    def _rate(self, provider: str | None, model: str | None) -> _CostStaticModelRate | None:
        if model is None:
            return None
        models = self._static.models
        return (models.get(f"{provider}/{model}") if provider else None) or models.get(model)

    def _charge(self, rate: _CostStaticModelRate, input_tokens: int, cached: int, output_tokens: int) -> Decimal:
        """Cached tokens are part of the input count and charged once, at the cached rate (else the input rate).

        A gateway that counts input without the cache would make ``input - cached`` negative; it is clamped at 0 so the
        cached part is still billed and nothing goes negative.
        """
        cached_rate = rate.cached_input if rate.cached_input is not None else rate.input
        units = max(input_tokens - cached, 0) * rate.input + cached * cached_rate + output_tokens * rate.output
        return units / _PER_RATE_UNIT * self._static.markup


class PricingSourceFactory:
    """Creates the configured pricing source. It holds no instance: ``CostManager`` owns the one it builds."""

    _log = logging.getLogger("ak.cost.pricing")

    @staticmethod
    def create(config: "_CostPricingConfig") -> PricingSource:
        """Build the pricing source the ``cost.pricing`` block names.

        :raises AKConfigError: If the type is not passthrough, static or a dotted path to a PricingSource subclass, or
            the static settings carry unknown keys.
        """
        PricingSourceFactory._log.info(f"Building '{config.type}' pricing source")
        key = config.type.lower()
        if key == "passthrough":
            return PassthroughPricingSource(config)
        if key == "static":
            return StaticPricingSource(config)
        if "." not in key:
            raise AKConfigError(
                f"unknown cost.pricing.type '{config.type}'; expected passthrough, static or a dotted path to a PricingSource subclass"
            )
        return resolve_dotted(config.type, base=PricingSource)(config)
