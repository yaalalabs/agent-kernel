"""``CosmosDBSpendLedger``: one Table API entity per user, replaced on its etag (the ``azure`` extra)."""

import asyncio
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from azure.core import MatchConditions
from azure.core.exceptions import AzureError, ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import UpdateMode

from ...core.util.driver.cosmosdb import CosmosDBDriver
from ..errors import LedgerError
from ..model import BudgetPeriod
from .base import LedgerDocument, SpendLedger, _utc_now

if TYPE_CHECKING:
    from ...core.config import _CostLedgerCosmosDBConfig

_ROW_KEY = "ledger"


class CosmosDBSpendLedger(SpendLedger):
    """Entity ``{PartitionKey: user_id, RowKey: "ledger", doc, version, expiry_time}``.

    The Table API has no TTL, so ``expiry_time`` (epoch seconds) is checked on read, and a write from version 0 may
    replace an expired entity.
    """

    def __init__(self, config: "_CostLedgerCosmosDBConfig", periods: Iterable[BudgetPeriod], *, clock: Callable[[], datetime] = _utc_now) -> None:
        super().__init__(periods, ttl=config.ttl, clock=clock)
        self._driver = CosmosDBDriver(connection_string=config.connection_string, table_name=config.table_name)

    async def load(self, user_id: str) -> LedgerDocument | None:
        entity = await self._entity(user_id)
        return None if entity is None or self._expired(entity) else LedgerDocument.model_validate_json(entity["doc"])

    async def compare_and_set(self, user_id: str, expected_version: int, doc: LedgerDocument, expires_at: datetime) -> bool:
        entity = await self._entity(user_id)
        new = {
            "PartitionKey": user_id,
            "RowKey": _ROW_KEY,
            "doc": doc.model_dump_json(),
            "version": doc.version,
            "expiry_time": int(expires_at.timestamp()),
        }
        try:
            if entity is None:
                if expected_version:
                    return False
                await self._call(lambda: self._driver.table_client.create_entity(entity=new))
                return True
            replaceable = int(entity["version"]) == expected_version if expected_version else self._expired(entity)
            if not replaceable:
                return False
            etag = entity.metadata["etag"]
            await self._call(
                lambda: self._driver.table_client.update_entity(
                    entity=new, mode=UpdateMode.REPLACE, etag=etag, match_condition=MatchConditions.IfNotModified
                )
            )
            return True
        except LedgerError as exc:
            if isinstance(exc.__cause__, (ResourceExistsError, ResourceModifiedError)):
                return False  # another writer created or changed it first
            raise

    async def _entity(self, user_id: str) -> Any:
        try:
            return await self._call(lambda: self._driver.table_client.get_entity(partition_key=user_id, row_key=_ROW_KEY))
        except LedgerError as exc:
            if isinstance(exc.__cause__, ResourceNotFoundError):
                return None
            raise

    def _expired(self, entity: Any) -> bool:
        return int(entity["expiry_time"]) <= int(self._clock().timestamp())

    @staticmethod
    async def _call(operation: Callable[[], Any]) -> Any:
        """Run on a worker thread, where the driver also connects on first use."""
        try:
            return await asyncio.to_thread(operation)
        except AzureError as exc:
            raise LedgerError(f"spend ledger {type(exc).__name__}") from exc
