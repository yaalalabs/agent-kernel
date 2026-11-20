"""SpendLedgerFactory: builds the SpendLedger named by ``cost.budgets.ledger.type``."""

import importlib
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ...core.util.factory import AKConfigError, require_extra, resolve_dotted
from ..model import BudgetPeriod
from .base import SpendLedger

if TYPE_CHECKING:
    from ...core.config import _CostLedgerConfig


# type -> (pip extra, module, class); each reads its own block, cost.budgets.ledger.<type>.
_BACKENDS = {
    "redis": ("redis", ".redis", "RedisSpendLedger"),
    "valkey": ("valkey", ".valkey", "ValkeySpendLedger"),
    "dynamodb": ("aws", ".dynamodb", "DynamoDBSpendLedger"),
    "cosmosdb": ("azure", ".cosmosdb", "CosmosDBSpendLedger"),
    "firestore": ("gcp", ".firestore", "FirestoreSpendLedger"),
}


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
        if key in _BACKENDS:
            extra, module, class_name = _BACKENDS[key]
            block = getattr(config, key)
            if block is None:
                raise AKConfigError(f"cost.budgets.ledger.type {key} needs a cost.budgets.ledger.{key} block")
            with require_extra(extra, f"cost.budgets.ledger.type: {key}"):
                backend = getattr(importlib.import_module(module, __package__), class_name)
            ledger: SpendLedger = backend(block, periods)  # a backend takes its own block first
            return ledger
        if "." not in key:
            raise AKConfigError(
                f"unknown cost.budgets.ledger.type '{config.type}'; expected one of in_memory, redis, valkey, dynamodb, cosmosdb, "
                "firestore or a dotted path to a SpendLedger subclass"
            )
        # A bring-your-own ledger reads its own settings; it is given the periods to bucket into.
        return resolve_dotted(config.type, base=SpendLedger)(periods)
