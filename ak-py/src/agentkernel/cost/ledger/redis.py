"""``RedisSpendLedger``: the spend ledger on Redis (the ``redis`` extra)."""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING

import redis

from ...core.util.driver.redis import RedisDriver
from ..model import BudgetPeriod
from .base import _utc_now
from .redis_like import _RedisLikeSpendLedger

if TYPE_CHECKING:
    from ...core.config import _CostLedgerRedisConfig


class RedisSpendLedger(_RedisLikeSpendLedger):
    def __init__(self, config: "_CostLedgerRedisConfig", periods: Iterable[BudgetPeriod], *, clock: Callable[[], datetime] = _utc_now) -> None:
        super().__init__(periods, ttl=config.ttl, clock=clock)
        self._driver = RedisDriver(url=config.url, prefix=config.prefix)  # no driver ttl: each write sets its own
        self._errors = redis.RedisError
