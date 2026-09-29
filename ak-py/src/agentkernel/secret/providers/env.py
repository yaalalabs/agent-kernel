"""EnvSecretProvider — the default backend: the process environment."""

import os
from typing import Optional

from ..base import SecretProvider


class EnvSecretProvider(SecretProvider):
    """The default backend: reads the environment variable named by the key. An empty value is a miss."""

    def get_secret(self, key: str) -> Optional[str]:
        return os.environ.get(key) or None
