"""Spend ledger (spec §12): the SpendLedgerContract on the in-memory ledger, and SpendLedgerFactory."""

import logging

import pytest

import agentkernel.cost as cost
from agentkernel.core.config import _CostLedgerConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import BudgetPeriod, InMemorySpendLedger, SpendLedger, SpendLedgerFactory
from agentkernel.cost.testing import SpendLedgerContract


class TestInMemorySpendLedgerContract(SpendLedgerContract):
    @pytest.fixture
    def ledger(self, clock) -> SpendLedger:
        return InMemorySpendLedger(list(BudgetPeriod), clock=clock)


class TestSpendLedger:
    def test_a_ledger_needs_a_period(self):
        with pytest.raises(ValueError, match="at least one budget"):
            InMemorySpendLedger([])


class TestSpendLedgerFactory:
    def test_no_ledger_block_is_in_memory_with_a_warning(self, caplog):
        caplog.set_level(logging.WARNING, logger="ak.cost.ledger.factory")

        ledger = SpendLedgerFactory.create(None, [BudgetPeriod.MONTHLY])

        assert isinstance(ledger, InMemorySpendLedger)
        assert "per process and lost on restart" in caplog.text

    @pytest.mark.parametrize("type_", ["in_memory", "IN_MEMORY"])
    def test_in_memory(self, type_):
        assert isinstance(SpendLedgerFactory.create(_CostLedgerConfig(type=type_), [BudgetPeriod.DAILY]), InMemorySpendLedger)

    def test_a_dotted_path_gets_the_periods(self):
        ledger = SpendLedgerFactory.create(_CostLedgerConfig(type="agentkernel.cost.ledger.in_memory.InMemorySpendLedger"), [BudgetPeriod.WEEKLY])

        assert isinstance(ledger, InMemorySpendLedger) and ledger._periods == [BudgetPeriod.WEEKLY]

    @pytest.mark.parametrize(
        ("type_", "message"), [("sqlite", "unknown cost.budgets.ledger.type"), ("datetime.datetime", "not a SpendLedger subclass")]
    )
    def test_refused_types(self, type_, message):
        with pytest.raises(AKConfigError, match=message):
            SpendLedgerFactory.create(_CostLedgerConfig(type=type_), [BudgetPeriod.DAILY])

    def test_exported(self):
        assert {"InMemorySpendLedger", "LedgerDocument", "SpendLedger", "SpendLedgerFactory"} <= set(cost.__all__)
