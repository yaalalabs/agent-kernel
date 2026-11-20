"""``SpendLedger``: one document of per-period spend aggregates per user, updated by compare-and-set (spec §12.1-12.2)."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from ..model import BudgetPeriod, ModelSpend, ModelUsage, SpendCursor, SpendTotal


class LedgerDocument(BaseModel):
    """A user's settled spend: the cursor it has applied up to, and aggregates per period and model.

    A bucket key is ``"<period>|<period start iso>|<provider>/<model>"``. One document per user keeps every update a
    single-document compare-and-set, so no backend needs multi-key transactions.
    """

    version: int = 0
    cursor: SpendCursor | None = None
    currency: str = "USD"
    buckets: dict[str, ModelSpend] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SpendLedger(ABC):
    """Stores ``LedgerDocument``s. A backend implements ``load`` and ``compare_and_set``; the rest is shared.

    Two processes pulling the same gateway rows never double-count: ``add`` writes only if the stored cursor is the
    one the caller read from, and only if no other write landed since its load.
    """

    def __init__(self, periods: Iterable[BudgetPeriod], *, ttl: int = 0, clock: Callable[[], datetime] = _utc_now) -> None:
        """
        :param periods: The period kinds of the budgets in force; each row is bucketed into every one of them.
        :param ttl: Seconds a document lives after its last write; 0 derives it from the periods.
        :param clock: The current UTC time, injectable for tests.
        """
        self._periods = sorted(set(periods))
        if not self._periods:
            raise ValueError("a spend ledger needs the period of at least one budget")
        self._ttl = ttl
        self._clock = clock

    @abstractmethod
    async def load(self, user_id: str) -> LedgerDocument | None:
        """The user's document, or None when there is none (or it has expired).

        :raises LedgerError: On a backend failure.
        """

    @abstractmethod
    async def compare_and_set(self, user_id: str, expected_version: int, doc: LedgerDocument, expires_at: datetime) -> bool:
        """Store ``doc`` if the stored version is still ``expected_version`` (an absent document is version 0).

        :return: False when another writer got there first; nothing is written then.
        :raises LedgerError: On a backend failure.
        """

    async def cursor(self, user_id: str) -> SpendCursor | None:
        doc = await self.load(user_id)
        return doc.cursor if doc else None

    async def add(self, user_id: str, rows: list[ModelUsage], expected_cursor: SpendCursor | None, next_cursor: SpendCursor) -> bool:
        """Apply settled rows and move the cursor, unless the ledger moved on since ``expected_cursor`` was read.

        :return: False on a stale cursor or a lost compare-and-set; nothing is added then.
        :raises UsageRetrievalError: If a row is in another currency than the document.
        """
        doc = await self.load(user_id) or LedgerDocument()
        if doc.cursor != expected_cursor:
            return False
        expected_version = doc.version
        for row in rows:
            (spend,) = SpendTotal.from_rows([row], doc.currency).by_model.values()
            for period in self._periods:
                key = f"{period.value}|{period.start_of(row.timestamp).isoformat()}|{SpendTotal.key(row.provider, row.model)}"
                doc.buckets[key] = doc.buckets[key].add(spend) if key in doc.buckets else spend
        now = self._clock()
        doc.buckets = {key: spend for key, spend in doc.buckets.items() if self._retained(key, now)}
        doc.cursor = next_cursor
        doc.version = expected_version + 1
        return await self.compare_and_set(user_id, expected_version, doc, self._expires_at(now))

    async def read(self, user_id: str, period: BudgetPeriod, period_start: datetime) -> SpendTotal:
        """The settled spend of the period that starts at (or contains) ``period_start``."""
        doc = await self.load(user_id)
        if doc is None:
            return SpendTotal(currency="USD", by_model={})
        prefix = f"{period.value}|{period.start_of(period_start).isoformat()}|"
        by_model = {key.removeprefix(prefix): spend for key, spend in doc.buckets.items() if key.startswith(prefix)}
        return SpendTotal(currency=doc.currency, by_model=by_model)

    def _retained(self, key: str, now: datetime) -> bool:
        """Keep the current and the previous period: a bucket goes once the period after it has ended."""
        period, start = key.split("|", 2)[:2]
        budget_period = BudgetPeriod(period)
        return now < budget_period.end_of(budget_period.end_of(datetime.fromisoformat(start)))

    def _expires_at(self, now: datetime) -> datetime:
        """A document outlives its newest bucket by one period, unless the backend sets a fixed ttl."""
        if self._ttl > 0:
            return now + timedelta(seconds=self._ttl)
        return max(period.end_of(period.end_of(now)) for period in self._periods)
