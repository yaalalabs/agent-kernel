"""``LedgerSpendFlow``: a user's spend for a budget check on a gateway without windowed spend (spec §12.3).

Settled rows (older than ``SETTLE_LAG``) are applied to the spend ledger batch by batch, each batch committed as soon
as it is read. The unsettled tail is re-read from the gateway on every check and never stored, so a gateway that
writes rows late is still counted. A check that cannot finish in ``CATCH_UP_BUDGET`` raises rather than return a
partial total; the progress it committed is kept for the next check.
"""

import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from ..errors import LedgerBehindError, LedgerConflictError
from ..gateway.base import LLMGateway
from ..model import BudgetPeriod, ModelUsage, SpendCursor, SpendTotal, UsageWindow
from .base import SpendLedger

SETTLE_LAG = timedelta(minutes=10)  # rows newer than this are re-read each check, not stored
CATCH_UP_BUDGET = 5.0  # seconds a check may spend reading the gateway, inside the 10 s policy bound


class LedgerSpendFlow:
    """Reads ledger spend for ``SpendReader``: ``read(user_id, period, window)``."""

    def __init__(
        self,
        gateway: LLMGateway,
        ledger: SpendLedger,
        periods: Iterable[BudgetPeriod],
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        :param periods: The period kinds of the budgets in force; nothing before the start of the longest is read.
        :param monotonic: A monotonic clock for the catch-up deadline, injectable for tests.
        """
        self._gateway = gateway
        self._ledger = ledger
        self._periods = sorted(set(periods))
        self._monotonic = monotonic

    async def read(self, user_id: str, period: BudgetPeriod, window: UsageWindow) -> SpendTotal:
        """The user's spend in ``period`` up to ``window.end``: settled ledger buckets plus the unsettled tail.

        :raises LedgerBehindError: If the ledger could not catch up within ``CATCH_UP_BUDGET``.
        :raises LedgerConflictError: If another process won the ledger write twice during this read.
        """
        now = window.end
        settle = now - SETTLE_LAG
        deadline = self._monotonic() + CATCH_UP_BUDGET
        # Rows before the start of every period in force cannot count toward a current budget.
        floor = SpendCursor(timestamp=min(p.start_of(now) for p in self._periods), ids_at_timestamp=frozenset())

        stored = await self._ledger.cursor(user_id)
        cursor = self._from(stored, floor)
        conflicts = 0
        while True:
            rows, next_cursor, caught_up = await self._gateway.fetch_usage_since(user_id, cursor, settle)
            if rows:
                if not await self._ledger.add(user_id, rows, stored, next_cursor or cursor):
                    conflicts += 1  # another process committed first: continue from its cursor
                    if conflicts > 1:
                        raise LedgerConflictError(f"spend ledger of user '{user_id}' changed under two writes in one check")
                    stored = await self._ledger.cursor(user_id)
                    cursor = self._from(stored, floor)
                    continue
                stored = next_cursor
            cursor = next_cursor or cursor
            if caught_up:
                break
            if self._monotonic() > deadline:
                raise LedgerBehindError(user_id, cursor)

        unsettled = [
            row
            for row in await self._read_all(user_id, SpendCursor(timestamp=settle, ids_at_timestamp=frozenset()), now, deadline)
            # A row at exactly the settle line was committed above.
            if row.timestamp > settle and row.timestamp >= period.start_of(now)
        ]
        settled = await self._ledger.read(user_id, period, period.start_of(now))
        return settled.merge(SpendTotal.from_rows(unsettled, settled.currency))

    async def _read_all(self, user_id: str, cursor: SpendCursor, until: datetime, deadline: float) -> list[ModelUsage]:
        rows: list[ModelUsage] = []
        while True:
            batch, next_cursor, caught_up = await self._gateway.fetch_usage_since(user_id, cursor, until)
            rows += batch
            cursor = next_cursor or cursor
            if caught_up:
                return rows
            if self._monotonic() > deadline:
                raise LedgerBehindError(user_id, cursor)

    @staticmethod
    def _from(stored: SpendCursor | None, floor: SpendCursor) -> SpendCursor:
        """Where to read from: the stored cursor, unless it is older than the longest period in force."""
        return stored if stored is not None and stored.timestamp >= floor.timestamp else floor
