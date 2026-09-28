"""Typed errors of the secret-resolution capability."""


class SecretError(Exception):
    """A secret could not be resolved because the backend failed. A provider miss is not an error."""


class SecretNotFoundError(SecretError):
    """No layer had the key, and no ``default`` was supplied."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"secret '{key}' not found: no '{key}' environment variable and no provider entry")
