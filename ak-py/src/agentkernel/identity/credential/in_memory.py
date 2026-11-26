"""In-process credential store: the default, for development and single-process deployments."""

import logging
import time
from typing import ClassVar

from .store import CredentialCipher, CredentialStore


class InMemoryCredentialStore(CredentialStore):
    """Credentials in this process's memory, shared by every instance in the process.

    The one store that may run without an encryption key, since nothing leaves the process: it then keeps
    credentials as they came and says so once when it is built. An expired entry is dropped when it is read.
    """

    shared: ClassVar[bool] = False
    _entries: ClassVar[dict[str, tuple[bytes, float]]] = {}
    _log = logging.getLogger("ak.identity.credential.in_memory")

    def __init__(self, cipher: CredentialCipher | None = None):
        """
        :param cipher: What values are encrypted with; None keeps them unencrypted in memory.
        """
        super().__init__(cipher)
        if cipher is None:
            self._log.warning(
                "identity.credentials names no encryption_key: credentials are kept unencrypted in this process's memory. "
                "Set one for anything but development"
            )

    def _write(self, key: str, data: bytes, expires_at: float) -> None:
        self._entries[key] = (data, expires_at)

    def _read(self, key: str) -> bytes | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        data, expires_at = entry
        if expires_at <= time.time():
            self._entries.pop(key, None)
            return None
        return data

    def _remove(self, key: str) -> None:
        self._entries.pop(key, None)

    def _clear(self) -> None:
        self._entries.clear()
