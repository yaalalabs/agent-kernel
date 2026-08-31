"""Valkey-backed scheduled-task store."""

import logging

from ...core.config import AKConfig
from ...core.util.driver.valkey import ValkeyDriver
from .redis_like import _RedisLikeScheduleStore


class ValkeyScheduleStore(_RedisLikeScheduleStore):
    """Valkey-backed implementation of the ScheduleStore interface."""

    def __init__(self):
        self._log = logging.getLogger("ak.schedule.store.valkey")
        schedule_config = AKConfig.get().schedule
        cfg = schedule_config.store.valkey if schedule_config is not None else None
        if cfg is None:
            raise ValueError("AKConfig.schedule.store.valkey must be set to use ValkeyScheduleStore")
        self._prefix = cfg.prefix
        self._driver = ValkeyDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))
