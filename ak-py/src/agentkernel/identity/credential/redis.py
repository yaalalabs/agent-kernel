"""Redis-backed credential store. Requires the ``redis`` extra."""

from ...core.util.driver.redis import RedisDriver
from .redis_like import _RedisLikeCredentialStore
from .store import CredentialCipher


class RedisCredentialStore(_RedisLikeCredentialStore):
    """Credentials in Redis, encrypted, each expiring with its token."""

    def __init__(self, url: str, prefix: str, cipher: CredentialCipher | None):
        """
        Nothing connects until the first read or write.

        :param url: The Redis connection URL.
        :param prefix: The key prefix every credential sits under.
        :param cipher: What values are encrypted with; required.
        """
        super().__init__(RedisDriver(url=url, prefix=prefix), cipher)
