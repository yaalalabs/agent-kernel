"""Valkey-backed agent registry. Requires the ``valkey`` extra."""

import logging

from ...core.util.driver.valkey import ValkeyDriver
from .redis_like import _RedisLikeAgentRegistry


class ValkeyAgentRegistry(_RedisLikeAgentRegistry):
    """Valkey-backed implementation of the AgentRegistry interface."""

    def __init__(self, url: str, prefix: str = "ak:registry:"):
        """
        Initializes the registry. Nothing connects until the first read or write.
        :param url: The Valkey connection URL.
        :param prefix: The key prefix every registry key sits under.
        """
        super().__init__(ValkeyDriver(url=url, prefix=prefix), logging.getLogger("ak.identity.registry.valkey"))
