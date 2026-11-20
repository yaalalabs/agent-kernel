"""``FirestoreSpendLedger``: one document per user, written on its update time (the ``gcp`` extra)."""

import asyncio
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from google.api_core.exceptions import AlreadyExists, FailedPrecondition, GoogleAPIError
from google.cloud import firestore

from ...core.util.driver.firestore import FirestoreDriver
from ..errors import LedgerError
from ..model import BudgetPeriod
from .base import LedgerDocument, SpendLedger, _utc_now

if TYPE_CHECKING:
    from ...core.config import _CostLedgerFirestoreConfig


class FirestoreSpendLedger(SpendLedger):
    """Document ``{collection}/{user_id}`` with fields ``doc``, ``version`` and ``expiry_time`` (a datetime a Firestore
    TTL policy can use).

    A write is conditioned on the update time of the snapshot it checked, which is a compare-and-set in one write.
    TTL policies delete late, so an expired document reads as absent and a write from version 0 may replace it.
    """

    def __init__(self, config: "_CostLedgerFirestoreConfig", periods: Iterable[BudgetPeriod], *, clock: Callable[[], datetime] = _utc_now) -> None:
        super().__init__(periods, ttl=config.ttl, clock=clock)
        self._driver = FirestoreDriver(collection_name=config.collection_name, project_id=config.project_id, database_id=config.database_id)

    async def load(self, user_id: str) -> LedgerDocument | None:
        snapshot = await self._call(lambda: self._ref(user_id).get())
        if not snapshot.exists or self._expired(snapshot):
            return None
        return LedgerDocument.model_validate_json(snapshot.get("doc"))

    async def compare_and_set(self, user_id: str, expected_version: int, doc: LedgerDocument, expires_at: datetime) -> bool:
        snapshot = await self._call(lambda: self._ref(user_id).get())
        data = {"doc": doc.model_dump_json(), "version": doc.version, "expiry_time": expires_at}
        try:
            if not snapshot.exists:
                if expected_version:
                    return False
                await self._call(lambda: self._ref(user_id).create(data))
                return True
            replaceable = int(snapshot.get("version")) == expected_version if expected_version else self._expired(snapshot)
            if not replaceable:
                return False
            option = firestore.Client.write_option(last_update_time=snapshot.update_time)
            await self._call(lambda: self._ref(user_id).update(data, option=option))
            return True
        except LedgerError as exc:
            if isinstance(exc.__cause__, (AlreadyExists, FailedPrecondition)):
                return False  # another writer created or changed it first
            raise

    def _ref(self, user_id: str) -> Any:
        return self._driver.collection.document(user_id)

    def _expired(self, snapshot: Any) -> bool:
        return bool(snapshot.get("expiry_time") <= self._clock())

    @staticmethod
    async def _call(operation: Callable[[], Any]) -> Any:
        """Run on a worker thread, where the driver also connects on first use."""
        try:
            return await asyncio.to_thread(operation)
        except GoogleAPIError as exc:
            raise LedgerError(f"spend ledger {type(exc).__name__}") from exc
