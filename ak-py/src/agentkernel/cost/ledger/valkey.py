"""``ValkeySpendLedger``: the spend ledger on Valkey (the ``valkey`` extra)."""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING

import valkey

from ...core.util.driver.valkey import ValkeyDriver
from ..model import BudgetPeriod
from .base import _utc_now
from .redis_like import _RedisLikeSpendLedger

if TYPE_CHECKING:
    from ...core.config import _CostLedgerValkeyConfig


class ValkeySpendLedger(_RedisLikeSpendLedger):
    def __init__(self, config: "_CostLedgerValkeyConfig", periods: Iterable[BudgetPeriod], *, clock: Callable[[], datetime] = _utc_now) -> None:
        super().__init__(periods, ttl=config.ttl, clock=clock)
        self._driver = ValkeyDriver(url=config.url, prefix=config.prefix)  # no driver ttl: each write sets its own
        self._errors = valkey.ValkeyError
