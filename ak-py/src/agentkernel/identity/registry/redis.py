"""Redis-backed agent registry. Requires the ``redis`` extra."""

import logging

from ...core.util.driver.redis import RedisDriver
from .redis_like import _RedisLikeAgentRegistry


class RedisAgentRegistry(_RedisLikeAgentRegistry):
    """Redis-backed implementation of the AgentRegistry interface."""

    def __init__(self, url: str, prefix: str = "ak:registry:"):
        """
        Initializes the registry. Nothing connects until the first read or write.
        :param url: The Redis connection URL.
        :param prefix: The key prefix every registry key sits under.
        """
        super().__init__(RedisDriver(url=url, prefix=prefix), logging.getLogger("ak.identity.registry.redis"))
