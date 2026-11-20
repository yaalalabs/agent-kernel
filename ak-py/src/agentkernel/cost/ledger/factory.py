"""SpendLedgerFactory: builds the SpendLedger named by ``cost.budgets.ledger.type``."""

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ...core.util.factory import AKConfigError, resolve_dotted
from ..model import BudgetPeriod
from .base import SpendLedger

if TYPE_CHECKING:
    from ...core.config import _CostLedgerConfig


class SpendLedgerFactory:
    """Creates the configured ledger. It holds no instance: ``CostManager`` owns the one it builds."""

    _log = logging.getLogger("ak.cost.ledger.factory")

    @staticmethod
    def create(config: "_CostLedgerConfig | None", periods: Iterable[BudgetPeriod]) -> SpendLedger:
        """Build the ledger the ``cost.budgets.ledger`` block names, bucketing into ``periods``.

        :param config: The ledger block; None means in-memory.
        :param periods: The period kinds of the budgets in force.
        :raises AKConfigError: If the type is neither a built-in nor a dotted path to a SpendLedger subclass.
        """
        if config is None:
            SpendLedgerFactory._log.warning(
                "cost.budgets.ledger is not set: using an in-memory spend ledger, which is per process and lost on restart"
            )
            from .in_memory import InMemorySpendLedger

            return InMemorySpendLedger(periods)
        SpendLedgerFactory._log.info(f"Building '{config.type}' spend ledger")
        key = config.type.lower()
        if key == "in_memory":
            from .in_memory import InMemorySpendLedger

            return InMemorySpendLedger(periods)
        if "." not in key:
            raise AKConfigError(
                f"unknown cost.budgets.ledger.type '{config.type}'; expected one of in_memory, redis, valkey, dynamodb, cosmosdb, "
                "firestore or a dotted path to a SpendLedger subclass"
            )
        # A bring-your-own ledger reads its own settings; it is given the periods to bucket into.
        return resolve_dotted(config.type, base=SpendLedger)(periods)
