"""Key-value store for storing serializable data."""

import logging
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

_log = logging.getLogger("ak.core.key_value_cache")


class KeyValueCache(BaseModel):
    """A generic key-value store for storing serializable data.

    This class provides a simple interface for storing and retrieving
    serializable data using a dictionary backend. All data must be
    JSON-serializable.

    Examples:
        >>> store = KeyValueCache()
        >>> store.set("name", "John")
        >>> store.get("name")
        'John'
        >>> store.set("config", {"debug": True, "timeout": 30})
        >>> store.get("config")
        {'debug': True, 'timeout': 30}

    Keys starting with ``ak.`` are reserved for Agent Kernel. Application code can read them, but
    ``set``, ``delete`` and ``update`` refuse them and ``clear`` leaves them in place, so the
    principal the runtime publishes cannot be forged and a pending human-in-the-loop decision is
    not discarded by an application clearing its cache. The runtime writes them through the
    private ``_set_reserved``, ``_delete_reserved`` and ``_clear_all``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    RESERVED_PREFIX: ClassVar[str] = "ak."

    data: dict[str, Any] = Field(default_factory=dict, description="Internal storage dictionary")

    def set(self, key: str, value: Any) -> None:
        """Store a value with the given key.

        :param key: The key to store the value under
        :param value: The value to store (must be JSON-serializable)
        :raises ValueError: If the key is empty or None, or reserved for Agent Kernel
        """
        if not key:
            raise ValueError("Key cannot be empty or None")
        self._refuse_reserved(key)
        self.data[key] = value
        _log.debug(f"Set key {key}: {type(value).__name__}")

    def get(self, key: str, default: Any | None = None) -> Any:
        """Retrieve a value by key.

        :param key: The key to retrieve the value for
        :param default: The default value to return if key is not found
        :return: The stored value, or the default if the key doesn't exist
        """
        _log.debug(f"Get key {key}: found={key in self.data}")
        return self.data.get(key, default)

    def delete(self, key: str) -> bool:
        """Delete a key-value pair.

        :param key: The key to delete
        :return: True if the key was found and deleted, False otherwise
        :raises ValueError: If the key is reserved for Agent Kernel
        """
        self._refuse_reserved(key)
        return self._delete_reserved(key)

    def has(self, key: str) -> bool:
        """Check if a key exists in the store.

        :param key: The key to check for
        :return: True if the key exists, False otherwise
        """
        return key in self.data

    def clear(self) -> None:
        """Clear every application key from the store; the reserved ``ak.`` keys survive."""
        for key in [key for key in self.data if not self._is_reserved(key)]:
            del self.data[key]
        _log.debug("Cleared application keys")

    def keys(self) -> list[str]:
        """Get all keys in the store.

        :return: A list of all keys
        """
        return list(self.data.keys())

    def values(self) -> list[Any]:
        """Get all values in the store.

        :return: A list of all values
        """
        return list(self.data.values())

    def items(self) -> list[tuple[str, Any]]:
        """Get all key-value pairs in the store.

        :return: A list of (key, value) tuples
        """
        return list(self.data.items())

    def update(self, other: dict[str, Any]) -> None:
        """Update the store with key-value pairs from a dictionary.

        :param other: A dictionary of key-value pairs to add/update
        :raises ValueError: If any key is reserved for Agent Kernel; nothing is written then
        """
        for key in other:
            self._refuse_reserved(key)
        self.data.update(other)
        _log.debug(f"Updated keys: {list(other)}")

    def __len__(self) -> int:
        """Return the number of items in the store."""
        return len(self.data)

    def __contains__(self, key: str) -> bool:
        """Check if a key exists using the 'in' operator."""
        return key in self.data

    def __getitem__(self, key: str) -> Any:
        """Get a value using dictionary-style access."""
        value = self.data[key]
        _log.debug(f"Get key {key}: found=True")
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        """Set a value using dictionary-style access."""
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        """Delete a value using dictionary-style access."""
        self._refuse_reserved(key)
        if key not in self.data:
            raise KeyError(key)
        del self.data[key]
        _log.debug(f"Deleted key {key}")

    @classmethod
    def _is_reserved(cls, key: str) -> bool:
        return key.startswith(cls.RESERVED_PREFIX)

    @classmethod
    def _refuse_reserved(cls, key: str) -> None:
        if cls._is_reserved(key):
            raise ValueError(f"'{key}' is reserved for Agent Kernel: keys starting with '{cls.RESERVED_PREFIX}' are written by the runtime only")

    def _set_reserved(self, key: str, value: Any) -> None:
        """Store a reserved value. Runtime-owned writers only; application code uses ``set``."""
        self.data[key] = value
        _log.debug(f"Set reserved key {key}: {type(value).__name__}")

    def _delete_reserved(self, key: str) -> bool:
        """Delete any key, reserved or not. Runtime-owned writers only.

        :return: True if the key was found and deleted, False otherwise
        """
        if key in self.data:
            del self.data[key]
            _log.debug(f"Deleted key {key}")
            return True
        _log.debug(f"Delete skipped, key {key} not found")
        return False

    def _clear_all(self) -> None:
        """Clear every key, reserved ones included: what the runtime calls when a run ends."""
        self.data.clear()
        _log.debug("Cleared all keys")
