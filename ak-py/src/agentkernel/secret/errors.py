"""Typed errors of the secret-resolution capability."""

from typing import Optional


class SecretError(Exception):
    """A secret could not be resolved because the backend failed. A provider miss is not an error."""


class SecretNotFoundError(SecretError):
    """No layer had the key, and no ``default`` was supplied."""

    def __init__(self, key: str, sources: Optional[str] = None) -> None:
        """
        :param key: The key no layer had.
        :param sources: Every place the key can be set (``SecretManager.describe``); named in the message.
        """
        self.key = key
        if sources:
            super().__init__(f"secret '{key}' not found: set {sources}")
        else:
            super().__init__(f"secret '{key}' not found: no '{key}' environment variable and no provider entry")
