"""``InMemorySpendLedger``: a process-local ledger, for a single process or tests (spec §12.4)."""

import threading
from collections.abc import Callable, Iterable
from datetime import datetime

from ..model import BudgetPeriod
from .base import LedgerDocument, SpendLedger, _utc_now


class InMemorySpendLedger(SpendLedger):
    """Documents in a dict behind a lock; an expired one is dropped when read. Lost on restart, and not shared
    between processes, so each process keeps its own view of spend."""

    def __init__(self, periods: Iterable[BudgetPeriod], *, ttl: int = 0, clock: Callable[[], datetime] = _utc_now) -> None:
        super().__init__(periods, ttl=ttl, clock=clock)
        self._documents: dict[str, tuple[LedgerDocument, datetime]] = {}
        self._lock = threading.Lock()

    async def load(self, user_id: str) -> LedgerDocument | None:
        with self._lock:
            doc = self._live(user_id)
            # A copy, so a caller editing it can never change what is stored before its compare-and-set.
            return doc.model_copy(deep=True) if doc else None

    async def compare_and_set(self, user_id: str, expected_version: int, doc: LedgerDocument, expires_at: datetime) -> bool:
        with self._lock:
            current = self._live(user_id)
            if (current.version if current else 0) != expected_version:
                return False
            self._documents[user_id] = (doc.model_copy(deep=True), expires_at)
            return True

    def _live(self, user_id: str) -> LedgerDocument | None:
        """The stored document unless it has expired; an expired one is dropped. Call under the lock."""
        entry = self._documents.get(user_id)
        if entry is None:
            return None
        doc, expires_at = entry
        if self._clock() >= expires_at:
            del self._documents[user_id]
            return None
        return doc
