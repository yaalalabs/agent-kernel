"""Shared Valkey connection driver. Requires the ``valkey`` extra."""

import valkey

from .redis_like import _RedisLikeDriver


class ValkeyDriver(_RedisLikeDriver):
    """
    Valkey connection driver: see :class:`_RedisLikeDriver` for the connection
    lifecycle and command surface.
    """

    _backend_name = "Valkey"
    _error_class = valkey.ValkeyError

    def _from_url(self, url: str, **kwargs):
        return valkey.from_url(url, **kwargs)
