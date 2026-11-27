"""Redis-protocol credential store body, shared by the Redis and Valkey backends.

Layout: one key per credential, ``{prefix}{key}``, holding the ciphertext and expiring with it. The value and
its expiry are written in one command (``SET ... PX``), so nothing leaves a credential without its expiry.
A renewal is ``EXPIRE``, which sets nothing on a key that has expired or been deleted.
"""

import math
import time

from ...core.util.driver.redis_like import _RedisLikeDriver
from .store import CredentialCipher, CredentialStore


class _RedisLikeCredentialStore(CredentialStore):
    """Shared credential store body for the Redis-protocol backends.

    ``RedisCredentialStore`` and ``ValkeyCredentialStore`` implement only ``__init__``, building the driver of
    their client library and handing it here, as the registry and schedule stores do.
    """

    def __init__(self, driver: _RedisLikeDriver, cipher: CredentialCipher | None):
        """
        :param driver: The connection driver, built with the store's prefix and no store-wide TTL.
        :param cipher: What values are encrypted with; required, since the store is shared.
        """
        super().__init__(cipher)
        self._driver = driver

    def _write(self, key: str, data: bytes, expires_at: float) -> None:
        self._driver.set_with_expiry(self._driver.key(key), data, expires_at - time.time())

    def _read(self, key: str) -> bytes | None:
        held: bytes | None = self._driver.get(self._driver.key(key))
        return held

    def _touch(self, key: str, expires_at: float) -> None:
        # Whole seconds, rounded up: a renewal may outlast what was asked by under a second, never fall short.
        self._driver.expire_in(self._driver.key(key), math.ceil(expires_at - time.time()))

    def _remove(self, key: str) -> None:
        self._driver.delete(self._driver.key(key))

    def _clear(self) -> None:
        self._driver.clear_prefix()
