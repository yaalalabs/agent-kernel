"""In-process credential store: the default, for development and single-process deployments."""

import logging
import threading
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
    # Held by every change, so a touch never writes back an entry another thread replaced or deleted.
    _lock: ClassVar[threading.Lock] = threading.Lock()
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
        with self._lock:
            self._entries[key] = (data, expires_at)

    def _read(self, key: str) -> bytes | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        data, expires_at = entry
        if expires_at <= time.time():
            with self._lock:
                # Only the entry this read saw: one renewed or replaced since the lookup stays.
                if self._entries.get(key) is entry:
                    del self._entries[key]
            return None
        return data

    def _touch(self, key: str, expires_at: float) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[1] > time.time():
                self._entries[key] = (entry[0], expires_at)

    def _remove(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def _clear(self) -> None:
        with self._lock:
            self._entries.clear()
