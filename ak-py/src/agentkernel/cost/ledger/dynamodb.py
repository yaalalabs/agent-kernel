"""``DynamoDBSpendLedger``: one item per user, written with a conditional ``put_item`` (the ``aws`` extra)."""

import asyncio
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from botocore.exceptions import BotoCoreError, ClientError

from ...core.util.driver.dynamodb import DynamoDBDriver
from ..errors import LedgerError
from ..model import BudgetPeriod
from .base import LedgerDocument, SpendLedger, _utc_now

if TYPE_CHECKING:
    from ...core.config import _CostLedgerDynamoDBConfig


class DynamoDBSpendLedger(SpendLedger):
    """Item ``{user_id, doc, version, expiry_time}``; ``expiry_time`` is the table's TTL attribute (epoch seconds).

    DynamoDB deletes expired items late (up to two days), so an expired item reads as absent, and a write from version
    0 may replace it.
    """

    def __init__(self, config: "_CostLedgerDynamoDBConfig", periods: Iterable[BudgetPeriod], *, clock: Callable[[], datetime] = _utc_now) -> None:
        super().__init__(periods, ttl=config.ttl, clock=clock)
        self._driver = DynamoDBDriver(table_name=config.table_name, partition_key="user_id")

    async def load(self, user_id: str) -> LedgerDocument | None:
        item = (await self._call(lambda: self._driver.table.get_item(Key={"user_id": user_id}, ConsistentRead=True))).get("Item")
        if item is None or int(item["expiry_time"]) <= self._now():
            return None
        return LedgerDocument.model_validate_json(item["doc"])

    async def compare_and_set(self, user_id: str, expected_version: int, doc: LedgerDocument, expires_at: datetime) -> bool:
        if expected_version:
            condition, values = "version = :v", {":v": expected_version}
        else:
            condition, values = "attribute_not_exists(user_id) OR expiry_time <= :now", {":now": self._now()}
        item = {"user_id": user_id, "doc": doc.model_dump_json(), "version": doc.version, "expiry_time": int(expires_at.timestamp())}
        try:
            await self._call(lambda: self._driver.table.put_item(Item=item, ConditionExpression=condition, ExpressionAttributeValues=values))
        except LedgerError as exc:
            cause = exc.__cause__
            if isinstance(cause, ClientError) and cause.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def _now(self) -> int:
        return int(self._clock().timestamp())

    @staticmethod
    async def _call(operation: Callable[[], Any]) -> Any:
        """Run on a worker thread, where the driver also connects on first use."""
        try:
            return await asyncio.to_thread(operation)
        except (BotoCoreError, ClientError) as exc:
            raise LedgerError(f"spend ledger {type(exc).__name__}") from exc
