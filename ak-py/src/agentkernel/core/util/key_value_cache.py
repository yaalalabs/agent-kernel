"""Key-value store for storing serializable data."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: Dict[str, Any] = Field(default_factory=dict, description="Internal storage dictionary")

    def set(self, key: str, value: Any) -> None:
        """Store a value with the given key.

        :param key: The key to store the value under
        :param value: The value to store (must be JSON-serializable)
        :raises ValueError: If the key is empty or None
        """
        if not key:
            raise ValueError("Key cannot be empty or None")
        self.data[key] = value

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """Retrieve a value by key.

        :param key: The key to retrieve the value for
        :param default: The default value to return if key is not found
        :return: The stored value, or the default if the key doesn't exist
        """
        return self.data.get(key, default)

    def delete(self, key: str) -> bool:
        """Delete a key-value pair.

        :param key: The key to delete
        :return: True if the key was found and deleted, False otherwise
        """
        if key in self.data:
            del self.data[key]
            return True
        return False

    def has(self, key: str) -> bool:
        """Check if a key exists in the store.

        :param key: The key to check for
        :return: True if the key exists, False otherwise
        """
        return key in self.data

    def clear(self) -> None:
        """Clear all data from the store."""
        self.data.clear()

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

    def update(self, other: Dict[str, Any]) -> None:
        """Update the store with key-value pairs from a dictionary.

        :param other: A dictionary of key-value pairs to add/update
        """
        self.data.update(other)

    def __len__(self) -> int:
        """Return the number of items in the store."""
        return len(self.data)

    def __contains__(self, key: str) -> bool:
        """Check if a key exists using the 'in' operator."""
        return key in self.data

    def __getitem__(self, key: str) -> Any:
        """Get a value using dictionary-style access."""
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set a value using dictionary-style access."""
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        """Delete a value using dictionary-style access."""
        if key not in self.data:
            raise KeyError(key)
        del self.data[key]
