"""Redis-backed scheduled-task store."""

import logging

from ...core.config import AKConfig
from ...core.util.driver.redis import RedisDriver
from .redis_like import _RedisLikeScheduleStore


class RedisScheduleStore(_RedisLikeScheduleStore):
    """Redis-backed implementation of the ScheduleStore interface."""

    def __init__(self):
        self._log = logging.getLogger("ak.schedule.store.redis")
        schedule_config = AKConfig.get().schedule
        cfg = schedule_config.store.redis if schedule_config is not None else None
        if cfg is None:
            raise ValueError("AKConfig.schedule.store.redis must be set to use RedisScheduleStore")
        self._prefix = cfg.prefix
        self._driver = RedisDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))
