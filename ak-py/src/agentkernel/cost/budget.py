"""Budgets: whether a user's run may go ahead, given their spend this period (spec §11.1-11.3)."""

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..core.meter import BudgetDecision
from ..core.util.factory import AKConfigError, resolve_dotted
from .errors import LedgerBehindError, LedgerError, UnsupportedCapabilityError, UsageRetrievalError, UsageTruncatedError
from .gateway.base import LLMGateway
from .model import SYSTEM_USER_ID, Attribution, BudgetLimit, SpendTotal, UsageWindow
from .pricing import PricingSource

if TYPE_CHECKING:
    from ..core.config import _CostBudgetsConfig

DEFAULT_DENY_MESSAGE = "Your usage budget for this period has been reached."
UNVERIFIED_DENY_MESSAGE = "Your usage budget could not be verified. Please try again later."
READ_TIMEOUT = 10.0  # seconds a spend read may take before on_error applies
# What a failed spend read can raise; each goes to budgets.on_error. Anything else is a bug and propagates.
ON_ERROR_EXCEPTIONS = (UsageRetrievalError, UsageTruncatedError, UnsupportedCapabilityError, LedgerError, TimeoutError)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SpendReader:
    """A user's spend over a window: the gateway's own aggregate when it has one, else the spend ledger (§12.3)."""

    _log = logging.getLogger("ak.cost.budget")

    def __init__(self, gateway: LLMGateway, *, ledger_flow: Any = None) -> None:
        """
        :param gateway: The configured gateway.
        :param ledger_flow: Reads ledger spend for gateways without ``windowed_spend``; its ``read(user_id, period,
            window)`` returns a ``SpendTotal``.
        """
        self._gateway = gateway
        self._ledger_flow = ledger_flow
        self._warned_unpriced: set[tuple[str, str]] = set()
        self._warned_lock = threading.Lock()

    async def spend(self, user_id: str, window: UsageWindow, limit: BudgetLimit) -> SpendTotal:
        """
        :raises UsageRetrievalError: If the spend is in another currency than the limit, or the read failed.
        :raises UnsupportedCapabilityError: If the gateway has no windowed spend and there is no ledger.
        """
        if self._gateway.capabilities.windowed_spend:
            total = await self._gateway.total_spend(user_id, window)
        elif self._ledger_flow is not None:
            total = await self._ledger_flow.read(user_id, limit.period, window)
        else:
            raise UnsupportedCapabilityError(self._gateway.name, "windowed_spend")
        if total.currency != limit.currency:
            raise UsageRetrievalError(f"spend is in {total.currency}, the budget in {limit.currency}", gateway=self._gateway.name)
        self._warn_unpriced(user_id, total)
        return total

    def _warn_unpriced(self, user_id: str, total: SpendTotal) -> None:
        """Unpriced requests count as zero; say so once per user and model per process."""
        for model, spend in total.by_model.items():
            if spend.unpriced_requests > 0:
                with self._warned_lock:
                    if (user_id, model) in self._warned_unpriced:
                        continue
                    self._warned_unpriced.add((user_id, model))
                self._log.warning(
                    f"{spend.unpriced_requests} requests by user '{user_id}' to '{model}' have no cost; they count as 0 toward the budget"
                )


class BudgetPolicy(ABC):
    """Decides whether a user's run may go ahead. A bring-your-own policy receives the same constructor arguments."""

    def __init__(
        self,
        config: "_CostBudgetsConfig | None",
        reader: SpendReader,
        pricing: PricingSource,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.config = config
        self._reader = reader
        self._pricing = pricing
        self._clock = clock

    @abstractmethod
    async def check(self, attribution: Attribution) -> BudgetDecision:
        """The decision for a run billed to ``attribution``."""

    def limit_for(self, user_id: str) -> BudgetLimit | None:
        """The user's own budget, else the default, else none."""
        if self.config is None:
            return None
        return self.config.users.get(user_id) or self.config.default


class NoBudgetPolicy(BudgetPolicy):
    """No budgets: every run goes ahead, and nothing is read."""

    async def check(self, attribution: Attribution) -> BudgetDecision:
        return BudgetDecision.allow()


class StaticBudgetPolicy(BudgetPolicy):
    """The configured ``budgets.default`` and ``budgets.users`` limits, checked against this period's billed spend."""

    _log = logging.getLogger("ak.cost.budget")

    async def check(self, attribution: Attribution) -> BudgetDecision:
        user_id = attribution.user_id
        if user_id is None or user_id == SYSTEM_USER_ID:
            return BudgetDecision.allow()
        limit = self.limit_for(user_id)
        if limit is None:
            return BudgetDecision.allow()
        now = self._clock()
        window = UsageWindow(start=limit.period.start_of(now), end=now)
        try:
            spent = self._pricing.bill_total(await asyncio.wait_for(self._reader.spend(user_id, window, limit), READ_TIMEOUT))
        except ON_ERROR_EXCEPTIONS as exc:
            return self._on_error(user_id, exc)
        if spent < limit.amount:
            return BudgetDecision.allow()
        if limit.action == "warn":
            return BudgetDecision.warn(
                f"budget reached: user={user_id} period={limit.period.value} start={window.start:%Y-%m-%d} "
                f"spend={spent} amount={limit.amount} {limit.currency}"
            )
        return BudgetDecision.deny(limit.message or DEFAULT_DENY_MESSAGE)

    def _on_error(self, user_id: str, error: BaseException) -> BudgetDecision:
        """The spend could not be read. The log names the error's type only: its text may hold gateway responses."""
        what = "spend ledger still catching up" if isinstance(error, LedgerBehindError) else f"spend read failed ({type(error).__name__})"
        if self.config is not None and self.config.on_error == "allow":
            self._log.warning(f"Budget check for user '{user_id}': {what}; allowed (on_error: allow)")
            return BudgetDecision.allow()
        self._log.error(f"Budget check for user '{user_id}': {what}; denied (on_error: block)")
        return BudgetDecision.deny(UNVERIFIED_DENY_MESSAGE)


class BudgetPolicyFactory:
    """Creates the configured budget policy. It holds no instance: ``CostManager`` owns the one it builds."""

    _log = logging.getLogger("ak.cost.budget")

    @staticmethod
    def create(config: "_CostBudgetsConfig | None", reader: SpendReader, pricing: PricingSource) -> BudgetPolicy:
        """Build the policy ``cost.budgets.policy.type`` names; no budgets block means no budgets.

        :raises AKConfigError: If the type is neither static, none nor a dotted path to a BudgetPolicy subclass.
        """
        if config is None:
            return NoBudgetPolicy(config, reader, pricing)
        policy_type = config.policy.type
        BudgetPolicyFactory._log.info(f"Building '{policy_type}' budget policy")
        key = policy_type.lower()
        if key == "static":
            return StaticBudgetPolicy(config, reader, pricing)
        if key == "none":
            return NoBudgetPolicy(config, reader, pricing)
        if "." not in key:
            raise AKConfigError(
                f"unknown cost.budgets.policy.type '{policy_type}'; expected static, none or a dotted path to a BudgetPolicy subclass"
            )
        return resolve_dotted(policy_type, base=BudgetPolicy)(config, reader, pricing)
