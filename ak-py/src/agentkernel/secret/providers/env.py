"""EnvSecretProvider — the default backend: the process environment."""

import os

from ..base import SecretProvider


class EnvSecretProvider(SecretProvider):
    """The default backend: reads the environment variable named by the key. An empty value is a miss."""

    def get_secret(self, key: str) -> str | None:
        return os.environ.get(key) or None

    def describe(self, key: str) -> str | None:
        """Nothing beyond the environment variable, which SecretManager already names."""
        return None
