"""Valkey-backed credential store. Requires the ``valkey`` extra."""

from ...core.util.driver.valkey import ValkeyDriver
from .redis_like import _RedisLikeCredentialStore
from .store import CredentialCipher


class ValkeyCredentialStore(_RedisLikeCredentialStore):
    """Credentials in Valkey, encrypted, each expiring with its token."""

    def __init__(self, url: str, prefix: str, cipher: CredentialCipher | None):
        """
        Nothing connects until the first read or write.

        :param url: The Valkey connection URL.
        :param prefix: The key prefix every credential sits under.
        :param cipher: What values are encrypted with; required.
        """
        super().__init__(ValkeyDriver(url=url, prefix=prefix), cipher)
