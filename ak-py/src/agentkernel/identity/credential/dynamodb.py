"""DynamoDB-backed credential store. Requires the ``aws`` extra.

Expected table schema:
    Partition Key: ``credential_key`` (S)
    Sort Key:      none
    TTL attribute: ``expiry_time``

Item layout (one item per credential):
    credential_key -> the partition key
    value          -> the ciphertext (B)
    expires_at     -> when the credential expires, in epoch seconds; what a read checks
    expiry_time    -> the same, rounded up to whole seconds, for DynamoDB's own TTL

DynamoDB removes an expired item when it gets to it, which can be long after it expired, so a read checks
``expires_at`` itself rather than trusting the item to be gone.
"""

import math
import time

from ...core.util.driver.dynamodb import DynamoDBDriver
from .store import CredentialCipher, CredentialStore


class DynamoDBCredentialStore(CredentialStore):
    """Credentials in DynamoDB, encrypted, each expiring with its token."""

    def __init__(self, table_name: str, cipher: CredentialCipher | None):
        """
        Nothing connects until the first read or write.

        :param table_name: The table, keyed by ``credential_key`` with TTL on ``expiry_time``.
        :param cipher: What values are encrypted with; required.
        """
        super().__init__(cipher)
        # No store-wide TTL: each item carries the expiry of its own credential.
        self._driver = DynamoDBDriver(table_name=table_name, partition_key="credential_key")

    def _write(self, key: str, data: bytes, expires_at: float) -> None:
        self._driver.put({"credential_key": key, "value": data, "expires_at": expires_at, "expiry_time": math.ceil(expires_at)})

    def _read(self, key: str) -> bytes | None:
        item = self._driver.get(key)
        if item is None or item["expires_at"] <= time.time():
            return None
        # boto3 hands a binary attribute back as a Binary wrapper, which bytes() unwraps.
        return bytes(item["value"])

    def _remove(self, key: str) -> None:
        self._driver.delete(key)

    def _clear(self) -> None:
        self._driver.clear_all()
