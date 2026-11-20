"""``_RedisLikeSpendLedger``: one JSON value per user under ``{prefix}{user_id}`` (spec §12.4)."""

import asyncio
import math
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ...core.util.driver.redis_like import _RedisLikeDriver
from ..errors import LedgerError
from .base import LedgerDocument, SpendLedger


class _RedisLikeSpendLedger(SpendLedger):
    """Shared body of the Redis-protocol ledgers. A subclass sets ``_driver`` and ``_errors`` in ``__init__``.

    ``EX`` expires a document exactly, so an expired document is simply absent.
    """

    _driver: _RedisLikeDriver
    _errors: type[BaseException]

    async def load(self, user_id: str) -> LedgerDocument | None:
        raw = await self._call(self._driver.get, self._driver.key(user_id))
        return None if raw is None else LedgerDocument.model_validate_json(raw)

    async def compare_and_set(self, user_id: str, expected_version: int, doc: LedgerDocument, expires_at: datetime) -> bool:
        key = self._driver.key(user_id)
        # The script compares exact bytes, so the value the version was checked on is what it compares: a write
        # landing between the two round trips makes the script refuse instead of clobbering it.
        raw = await self._call(self._driver.get, key)
        stored_version = LedgerDocument.model_validate_json(raw).version if raw is not None else 0
        if stored_version != expected_version:
            return False
        seconds = max(math.ceil((expires_at - self._clock()).total_seconds()), 1)
        return bool(await self._call(self._driver.compare_and_set, key, raw, doc.model_dump_json().encode(), seconds))

    async def _call(self, method: Callable[..., Any], *args: Any) -> Any:
        try:
            return await asyncio.to_thread(method, *args)
        except self._errors as exc:
            raise LedgerError(f"spend ledger {type(exc).__name__}") from exc
