import logging

from ....core.config import AKConfig
from ....core.util.driver.valkey import ValkeyDriver
from .redis_like import _RedisLikeThreadStore


class ValkeyThreadStore(_RedisLikeThreadStore):
    """
    Valkey-backed implementation of the ThreadStore interface.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.valkey")
        cfg = AKConfig.get().thread.valkey
        if cfg is None:
            raise ValueError("AKConfig.thread.valkey must be set to use ValkeyThreadStore")
        self._prefix = cfg.prefix
        self._driver = ValkeyDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))
