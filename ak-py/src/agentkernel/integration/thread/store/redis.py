import logging

from ....core.config import AKConfig
from ....core.util.driver.redis import RedisDriver
from .redis_like import _RedisLikeThreadStore


class RedisThreadStore(_RedisLikeThreadStore):
    """
    Redis-backed implementation of the ThreadStore interface.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.redis")
        cfg = AKConfig.get().thread.redis
        if cfg is None:
            raise ValueError("AKConfig.thread.redis must be set to use RedisThreadStore")
        self._prefix = cfg.prefix
        self._driver = RedisDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))
