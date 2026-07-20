"""Shared Redis connection driver. Requires the ``redis`` extra."""

import redis

from .redis_like import _RedisLikeDriver


class RedisDriver(_RedisLikeDriver):
    """
    Redis connection driver: see :class:`_RedisLikeDriver` for the connection
    lifecycle and command surface.
    """

    _backend_name = "Redis"
    _error_class = redis.RedisError

    def _from_url(self, url: str, **kwargs):
        return redis.from_url(url, **kwargs)
